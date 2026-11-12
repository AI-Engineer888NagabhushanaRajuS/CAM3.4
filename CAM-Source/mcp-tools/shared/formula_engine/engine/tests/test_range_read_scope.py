"""Transient range read continuation, without cross-call result reuse."""
from pathlib import Path
import sys,datetime
import openpyxl,pytest
from openpyxl.worksheet.formula import ArrayFormula
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook
from excel_formula_engine.workbook import SheetData,CalculationBudgetExceeded
from excel_formula_engine.values import NAME_ERR


class Traced(Workbook):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.reads={};self.scope_peak=(0,0)
    def get_value(self,sheet,row,col,ctx):
        key=(sheet.lower(),row,col);self.reads[key]=self.reads.get(key,0)+1
        scope=self._range_read_scope
        if scope:self.scope_peak=max(self.scope_peak,(len(scope['ranges']),scope['reserved_cells']))
        return super().get_value(sheet,row,col,ctx)


def fixture(tmp_path):
    r=openpyxl.Workbook();s=r.active;s.title='S'
    for row in range(1,11):s.cell(row,1,row);s.cell(row,3,f'=A{row}*2')
    s['D1']='=2';s['F1']='=SUM(A1:A10)+D1+SUM(A1:A10)';s['F2']='=SUM(C1:C10)';s['F3']='=IF(A1>0,SUM(A1:A10),SUM(C1:C10))';s['F4']='=IFERROR(SUM(C1:C10),"caught")'
    p=tmp_path/'ranges.xlsx';r.save(p);return p


def test_completed_range_reused_after_scheduler_restart(tmp_path):
    w=Traced(fixture(tmp_path));assert w.cell_value_now('S',1,6)==112
    assert all(w.reads['s',r,1]==1 for r in range(1,11))
    assert w._range_read_scope is None
    assert ('s',1,1,10,1)in w.deps['s',1,6]


def test_formula_prefix_continues_without_restarting_successful_reads(tmp_path):
    w=Traced(fixture(tmp_path));assert w.cell_value_now('S',2,6)==110
    # Each unresolved cell suspends once, then succeeds once. Earlier values
    # are not reread on each later suspension.
    assert all(w.reads['s',r,3]==2 for r in range(1,11))
    assert len(w.rdeps_ranges['s'])==1
    assert w._range_read_scope is None


def test_edit_recalc_uses_new_values_and_unchanged_invalidation(tmp_path):
    w=Traced(fixture(tmp_path));assert w.cell_value_now('S',1,6)==112
    w.set_value('S',10,1,20);assert w.cell_value_now('S',1,6)==132
    w.set_value('S',10,1,10);assert w.cell_value_now('S',1,6)==112
    w.set_formula('S',4,1,'=30');assert w.cell_value_now('S',1,6)==164
    assert w._range_read_scope is None


def test_budget_suspension_releases_all_transient_state_and_retry(tmp_path):
    w=Traced(fixture(tmp_path))
    with pytest.raises(CalculationBudgetExceeded):w.cell_value_now('S',2,6,budget_seconds=0)
    assert w._range_read_scope is None;assert not w._scheduler_active
    assert w.cell_value_now('S',2,6)==110


def test_exception_releases_prefix_state(tmp_path,monkeypatch):
    w=Traced(fixture(tmp_path));original=w.get_value
    def fail(sheet,row,col,ctx):
        if col==3 and row==5:raise RuntimeError('authored interruption')
        return original(sheet,row,col,ctx)
    monkeypatch.setattr(w,'get_value',fail)
    with pytest.raises(RuntimeError,match='authored interruption'):w.cell_value_now('S',2,6)
    assert w._range_read_scope is None;assert not w._scheduler_active
    monkeypatch.setattr(w,'get_value',original);assert w.cell_value_now('S',2,6)==110


def test_cycles_and_break_recovery_are_not_hidden(tmp_path):
    p=fixture(tmp_path);r=openpyxl.load_workbook(p);r['S']['C5']='=F2';r.save(p);w=Traced(p)
    assert str(w.cell_value_now('S',2,6))=='#CIRC!';assert w.cycle_diagnostics;assert w._range_read_scope is None
    w.set_formula('S',5,3,'=A5*2');assert w.cell_value_now('S',2,6)==110


def test_lazy_branch_does_not_materialize_unselected_ranges(tmp_path):
    w=Traced(fixture(tmp_path));assert w.cell_value_now('S',3,6)==55
    assert not any(col==3 for sh,row,col in w.reads)
    w.set_value('S',1,1,0);assert w.cell_value_now('S',3,6)==108


def test_whole_column_empty_tail_dependencies_survive_scope(tmp_path):
    p=fixture(tmp_path);r=openpyxl.load_workbook(p);r['S']['F5']='=SUM(A:A)+D1';r.save(p);w=Traced(p)
    assert w.cell_value_now('S',5,6)==57
    assert ('s',1,1,1048576,1)in w.deps['s',5,6]
    w.set_value('S',500,1,9);assert w.cell_value_now('S',5,6)==66


def test_casefold_cross_sheet_range_reuse(tmp_path):
    p=fixture(tmp_path);r=openpyxl.load_workbook(p);t=r.create_sheet('Other');t['A1']='=SUM(S!A1:A10)+S!D1+SUM(s!A1:A10)';r.save(p);w=Traced(p)
    assert w.cell_value_now('other',1,1)==112
    assert all(w.reads['s',r,1]==1 for r in range(1,11))


def test_array_snapshot_refusal_and_masked_notes_survive_reuse(tmp_path):
    p=fixture(tmp_path);r=openpyxl.load_workbook(p);r['S']['A1']=ArrayFormula(ref='A1:A3',text='=UNIQUE(C1:C3)');r['S']['F6']='=IFERROR(SUM(A2:A3)+D1,"blocked")';r.save(p);w=Traced(p)
    assert w.cell_value_now('S',6,6)=='blocked';assert any('array-output-uncomputed:'in n for n in w.notes);assert w._range_read_scope is None


def test_scope_is_per_workbook_not_global(tmp_path):
    p=fixture(tmp_path);a=Traced(p);b=Traced(p);b.set_value('S',1,1,100)
    assert a.cell_value_now('S',1,6)==112;assert b.cell_value_now('S',1,6)==310
    assert a._range_read_scope is b._range_read_scope is None


def test_formula_free_large_range_not_admitted():
    w=Traced();w.sheets['s']=SheetData('S');w.sheet_order=['s'];w.set_value('S',20001,1,1);w.set_formula('S',1,3,'=SUM(A1:A20001)')
    assert w.cell_value_now('S',1,3)==1;assert w.scope_peak==(0,0)


def test_admission_count_and_reserved_cells_bound():
    w=Traced();w.sheets['s']=SheetData('S');w.sheet_order=['s']
    for c in range(1,71):w.set_value('S',1,c,1)
    w.set_formula('S',1,80,'='+'+'.join(f'SUM({openpyxl.utils.get_column_letter(c)}1:{openpyxl.utils.get_column_letter(c)}2)'for c in range(1,71)))
    assert w.cell_value_now('S',1,80)==70
    assert w.scope_peak[0]==64;assert w.scope_peak[1]<=250000;assert w._range_read_scope is None


def test_nonformula_public_read_does_not_open_scope(tmp_path):
    w=Traced(fixture(tmp_path));assert w.cell_value_now('S',1,1)==1;assert w._range_read_scope is None


def test_mid_range_budget_failure_clears_prefix_before_edit_retry(tmp_path,monkeypatch):
    w=Traced(fixture(tmp_path));original=w.get_value
    def stop(sheet,row,col,ctx):
        if col==3 and row==5:raise CalculationBudgetExceeded('authored mid-prefix budget')
        return original(sheet,row,col,ctx)
    monkeypatch.setattr(w,'get_value',stop)
    with pytest.raises(CalculationBudgetExceeded):w.cell_value_now('S',2,6)
    assert w._range_read_scope is None
    monkeypatch.setattr(w,'get_value',original);w.set_value('S',1,1,100)
    assert w.cell_value_now('S',2,6)==308


def test_reserved_logical_cells_cap_not_only_entry_count():
    w=Traced();w.sheets['s']=SheetData('S');w.sheet_order=['s']
    for c in range(1,16):w.set_value('S',20000,c,1)
    w.set_formula('S',1,20,'='+'+'.join(f'SUM({openpyxl.utils.get_column_letter(c)}1:{openpyxl.utils.get_column_letter(c)}20000)'for c in range(1,16)))
    assert w.cell_value_now('S',1,20)==15
    assert w.scope_peak==(12,240000);assert w._range_read_scope is None
