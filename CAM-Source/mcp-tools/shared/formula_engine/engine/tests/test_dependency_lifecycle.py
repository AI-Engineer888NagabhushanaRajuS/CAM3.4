"""Repeated-edit dependency lifecycle, not app/financial identity."""
import sys,datetime
from pathlib import Path
import pytest
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'engine'))
from excel_formula_engine.workbook import Workbook,SheetData,CalculationBudgetExceeded
from excel_formula_engine.values import is_error

def make():
 w=Workbook(today=datetime.date(2026,11,11))
 for name in ['S','T']:
  w.sheets[name.lower()]=SheetData(name);w.sheet_order.append(name.lower())
 return w

def v(w,r,c=2):return w.cell_value_now('S',r,c)
def edges(w):return sum(len(x)for x in w.rdeps_ranges.values())

def test_repeated_range_edits_do_not_accumulate_duplicates():
 w=make();w.set_value('S',1,1,1);w.set_formula('S',1,2,'SUM(A1:A2)')
 for i in range(1000):
  w.set_value('S',1,1,i);assert v(w,1)==i;assert edges(w)==1
 assert w.deps[('s',1,2)]=={('s',1,1,2,1)}

def test_literal_replacement_detaches_outgoing_not_consumers():
 w=make();w.set_value('S',1,1,3);w.set_formula('S',1,2,'SUM(A1:A2)');w.set_formula('S',1,3,'B1*2');assert v(w,1,3)==6
 w.set_value('S',1,2,10);assert v(w,1,3)==20;assert edges(w)==0
 w.set_value('S',1,1,5);assert ('s',1,2)not in w.deps;assert ('s',1,3)in w.cache

def test_formula_replacement_detaches_range_and_direct_edges():
 w=make();w.set_value('S',1,1,3);w.set_formula('S',1,2,'SUM(A1:A2)+A1');assert v(w,1)==6
 w.set_formula('S',1,2,'10');assert v(w,1)==10;assert not w.rdeps.get(('s',1,1));assert edges(w)==0
 w.set_value('S',1,1,8);assert ('s',1,2)in w.cache

def test_lazy_branch_switch_removes_old_cell_edges():
 w=make()
 for row,value in [(1,True),(2,10),(3,20)]:w.set_value('S',row,1,value)
 w.set_formula('S',1,2,'IF(A1,A2,A3)');assert v(w,1)==10
 w.set_value('S',1,1,False);assert v(w,1)==20;assert ('s',1,2)not in w.rdeps.get(('s',2,1),set())
 w.set_value('S',2,1,999);assert ('s',1,2)in w.cache
 w.set_value('S',3,1,30);assert ('s',1,2)not in w.cache;assert v(w,1)==30

def test_cross_sheet_branch_range_replacement():
 w=make();w.set_value('S',1,1,True);w.set_value('S',2,1,3);w.set_value('T',2,1,7)
 w.set_formula('S',1,2,'IF(A1,SUM(S!A2:A3),SUM(T!A2:A3))');assert v(w,1)==3
 w.set_value('S',1,1,False);assert v(w,1)==7;assert 's'not in w.rdeps_ranges;assert edges(w)==1
 w.set_value('S',3,1,20);assert ('s',1,2)in w.cache
 w.set_value('T',3,1,5);assert v(w,1)==12

def test_two_consumers_shared_range_clear_only_one_owner():
 w=make();w.set_value('S',1,1,3)
 for row in [1,2]:w.set_formula('S',row,2,'SUM(A1:A2)');assert v(w,row)==3
 assert edges(w)==2;w.set_formula('S',1,2,'10');assert v(w,1)==10;assert edges(w)==1
 w.set_value('S',2,1,7);assert v(w,2)==10;assert ('s',1,2)in w.cache

def test_error_result_retains_dependency_until_replaced():
 w=make();w.set_value('S',1,1,0);w.set_formula('S',1,2,'1/A1');assert is_error(v(w,1))
 w.set_value('S',1,1,2);assert v(w,1)==.5
 w.set_formula('S',1,2,'UNKNOWN_FN(A1)');assert is_error(v(w,1));w.set_formula('S',1,2,'10');assert v(w,1)==10
 assert not w.rdeps.get(('s',1,1))

def test_cycle_provisional_edges_recover_then_detach():
 w=make();w.set_formula('S',1,1,'B1+1');w.set_formula('S',1,2,'A1+1');assert is_error(v(w,1))
 assert ('s',1,2)in w.deps[('s',1,1)];assert ('s',1,1)in w.deps[('s',1,2)]
 w.set_value('S',1,1,3);assert v(w,1)==4;assert not w.rdeps.get(('s',1,2))
 w.set_value('S',1,2,8);assert not w.rdeps;assert not w.deps

def test_budget_interruption_retains_dependency_for_retry(monkeypatch):
 import excel_formula_engine.workbook as mod
 w=make();w.set_value('S',1,1,3);w.set_formula('S',1,2,'A1+1');w.set_formula('S',1,3,'B1+1')
 ticks=iter([0,0,2]);monkeypatch.setattr(mod.time,'monotonic',lambda:next(ticks))
 with pytest.raises(CalculationBudgetExceeded):w.cell_value_now('S',1,3,budget_seconds=1)
 assert ('s',1,2)in w.deps[('s',1,3)]
 monkeypatch.undo();w.set_value('S',1,1,5);assert v(w,1,3)==7
 w.set_formula('S',1,3,'10');assert v(w,1,3)==10;w.set_value('S',1,2,999);assert ('s',1,3)in w.cache

def test_old_branch_no_longer_dirties_pivot_source():
 w=make();w.set_value('S',1,1,True);w.set_value('S',2,1,3);w.set_value('S',3,1,7);w.set_formula('S',1,2,'IF(A1,SUM(A2:A2),SUM(A3:A3))');assert v(w,1)==3
 w.set_value('S',1,1,False);assert v(w,1)==7
 w.pivot_snapshots=[{'name':'AUTHORED','sheet':'P','source_table':None,'source_sheet':'S','source_ref':'B1:B1','source_dirty':False}]
 w.set_value('S',2,1,10);assert not w.pivot_snapshots[0]['source_dirty'];assert ('s',1,2)in w.cache
 w.set_value('S',3,1,20);assert w.pivot_snapshots[0]['source_dirty'];assert v(w,1)==20

def test_whole_column_empty_tail_still_invalidates():
 w=make();w.set_value('S',1,1,3);w.set_formula('S',1,2,'SUM(A:A)');assert v(w,1)==3
 for i in range(3):w.set_value('S',1,1,i);assert v(w,1)==i
 assert edges(w)==1;w.set_value('S',1000,1,4);assert v(w,1)==6

def test_transitive_selected_formula_branch_detaches_provisional_edges():
 w=make();w.set_value('S',1,1,True);w.set_formula('S',2,1,'5+5');w.set_formula('S',3,1,'10+10');w.set_formula('S',1,2,'IF(A1,A2,A3)');assert v(w,1)==10
 w.set_value('S',1,1,False);assert v(w,1)==20;assert ('s',1,2)not in w.rdeps.get(('s',2,1),set())
 w.set_formula('S',2,1,'99');assert ('s',1,2)in w.cache
 w.set_formula('S',3,1,'40');assert v(w,1)==40
