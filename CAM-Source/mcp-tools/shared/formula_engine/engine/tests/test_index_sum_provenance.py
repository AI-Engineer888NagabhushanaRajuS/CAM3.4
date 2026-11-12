"""SUM INDEX reference provenance only, no general reference-returning contract."""
import openpyxl,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,DIV0,REF_ERR,is_error
from openpyxl.worksheet.table import Table


def test_sum_index_reference_text_logical_and_selected_value_edits(tmp_path):
    raw=openpyxl.Workbook();s=raw.active;s.title='S'
    for row,value in enumerate(['5',True,2,'x'],1):s.cell(row,1,value)
    s['A5']='=1/0';s['B1']=1
    formulas=[('=SUM(INDEX(A1:A5,1),2)',2),('=SUM(INDEX(A1:A5,2),2)',2),('=SUM(INDEX(A1:A5,3),2)',4),('=SUM(INDEX(A1:A5,4),2)',2),('=SUM(INDEX(A1:A5,5),2)',DIV0),('=SUM(INDEX(A1:A5,6),2)',REF_ERR),('=SUM(INDEX(A1:A4,0),2)',4),('=SUM(INDEX(A1:A5,B1),2)',2),('=SUM(INDEX(A1:A5,1)+0,2)',7),('=SUM(INDEX("5",1),2)',7),('=SUM(INDEX(A1,1),2)',2),('=SUM(INDEX(A2,1),2)',2)]
    for row,(formula,_) in enumerate(formulas,1):s.cell(row,4,formula)
    p=tmp_path/'index_sum.xlsx';raw.save(p);w=Workbook(str(p))
    for row,(_,expected) in enumerate(formulas,1):assert w.cell_value_now('S',row,4)==expected
    w.set_value('S',1,1,7);assert w.cell_value_now('S',1,4)==9
    w.set_value('S',1,2,3);assert w.cell_value_now('S',8,4)==4
    assert not w.notes and not w.cycle_diagnostics


def test_sum_index_reference_lazy_crosssheet_table_dynamic_and_cycles(tmp_path):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';other=raw.create_sheet('Other')
    other['A1']='text';other['A2']=3;other['A3']='=S!D1';s['B1']=1
    s['A1']='Values';s['A2']='5';s['A3']=4;s.add_table(Table(displayName='T',ref='A1:A3'))
    formulas=[('=SUM(INDEX(Other!A1:A3,B1),2)',2),('=SUM(INDEX(T[Values],1),2)',2),('=SUM(INDEX(INDEX(A:A,2):INDEX(A:A,3),1),2)',2),('=SUM(INDEX(Other!A1:A3,2),2)',5)]
    for row,(formula,_) in enumerate(formulas,1):s.cell(row,4,formula)
    p=tmp_path/'index_refs.xlsx';raw.save(p);w=Workbook(str(p))
    for row,(_,expected) in enumerate(formulas,1):assert w.cell_value_now('S',row,4)==expected
    assert not w.notes and not w.cycle_diagnostics
    # Excluded self-reference stays unvisited, but selecting it is an actual cycle.
    w.set_value('S',1,2,3);assert is_error(w.cell_value_now('S',1,4))
    assert w.cycle_diagnostics
