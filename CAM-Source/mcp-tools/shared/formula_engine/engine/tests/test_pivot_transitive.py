"""Scoped diagnostic proposal. No pivot refresh or unseen dependency promise."""
import sys,datetime
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'engine'))
from excel_formula_engine.workbook import Workbook,SheetData

def make(cls):
 w=cls(today=datetime.date(2026,11,11));s=SheetData('S');s.cached={(1,1):10};s.formulas={(1,2):'A1*2',(1,3):'B1+1'};s.max_row=1;s.max_col=4;w.sheets={'s':s};w.sheet_order=['s'];w.pivot_snapshots=[{'name':'AUTHORED','sheet':'P','source_table':None,'source_sheet':'S','source_ref':'B1:C1','source_dirty':False}];return w

def test_baseline_gap_and_candidate_recorded_transitive_path():
 new=make(Workbook)
 assert new.cell_value_now('S',1,3)==21;new.set_value('S',1,1,20);assert new.cell_value_now('S',1,3)==41
 assert new.pivot_snapshots[0]['source_dirty'];assert len(new.notes)==1

def test_unobserved_path_not_falsely_promised():
 w=make(Workbook);w.set_value('S',1,1,20);assert not w.pivot_snapshots[0]['source_dirty']

def test_unrelated_edit_not_dirty():
 w=make(Workbook);assert w.cell_value_now('S',1,3)==21;w.set_value('S',1,4,20);assert not w.pivot_snapshots[0]['source_dirty']

def test_restore_stays_dirty_no_duplicate_note():
 w=make(Workbook);w.cell_value_now('S',1,3);w.set_value('S',1,1,20);w.set_value('S',1,1,10);assert w.cell_value_now('S',1,3)==21;assert w.pivot_snapshots[0]['source_dirty'] and len(w.notes)==1

def test_set_formula_existing_dependents_marks_dirty():
 w=make(Workbook);w.cell_value_now('S',1,3);w.set_formula('S',1,1,'5+5');assert w.pivot_snapshots[0]['source_dirty'];assert w.cell_value_now('S',1,3)==21

def test_current_table_bounds_and_casefold_sheet_binding():
 w=make(Workbook);w.tables={'source':('s',1,2,1,3,0,0)};p=w.pivot_snapshots[0];p.update(source_ref=None,source_sheet=None,source_table='SOURCE')
 w.cell_value_now('S',1,3);w.set_value('S',1,1,20);assert p['source_dirty']

def test_range_recorded_dependent_and_no_pivot_overhead_path():
 w=make(Workbook);w.sheets['s'].formulas[(1,3)]='SUM(A1:A2)';assert w.cell_value_now('S',1,3)==10;w.set_value('S',2,1,20);assert w.pivot_snapshots[0]['source_dirty'];assert w.cell_value_now('S',1,3)==30
 w=make(Workbook);w.pivot_snapshots=[];w._mark_invalidated_pivot_sources_dirty=lambda keys:(_ for _ in ()).throw(AssertionError('called without pivots'));w.set_value('S',1,1,5)
