"""Scoped SUM/COUNT direct argument vs cell reference rules from Microsoft docs."""
import openpyxl
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,DIV0


def test_sum_single_cell_references_do_not_coerce_text_or_logical(tmp_path):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';s['A1']='5';s['A2']=True;s['A3']='x';s['A4']=2;s['A5']='=1/0'
    formulas=[('=SUM(A1,A2,2)',2),('=SUM("5",TRUE,2)',8),('=SUM(A3,2)',2),('=SUM(A1:A4)',2),('=SUM(A5,2)',DIV0),('=SUM(A2+0,2)',3),('=SUM(A6,2)',2)]
    for row,(formula,_) in enumerate(formulas,1):s.cell(row,4,formula)
    p=tmp_path/'sum_refs.xlsx';raw.save(p);w=Workbook(str(p))
    for row,(_,expected) in enumerate(formulas,1):assert w.cell_value_now('S',row,4)==expected
    w.set_value('S',1,1,5);assert w.cell_value_now('S',1,4)==7
    w.set_value('S',3,1,4);assert w.cell_value_now('S',3,4)==6
    assert not w.notes


def test_count_direct_literals_differ_from_reference_values_and_ignore_errors(tmp_path):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';s['A1']='1';s['A2']=True;s['A3']='x';s['A4']=2;s['A5']='=1/0'
    formulas=[('=COUNT(TRUE,"1",2,"x",1/0)',3),('=COUNT(A1,A2,A3,A4,A5)',1),('=COUNT(A1:A5)',1),('=COUNT(FALSE,"",A6)',1),('=COUNT(A2+0)',1),('=COUNT("NaN","Infinity")',0)]
    for row,(formula,_) in enumerate(formulas,1):s.cell(row,4,formula)
    p=tmp_path/'count_refs.xlsx';raw.save(p);w=Workbook(str(p))
    for row,(_,expected) in enumerate(formulas,1):assert w.cell_value_now('S',row,4)==expected
    w.set_value('S',1,1,1);assert w.cell_value_now('S',2,4)==2
    assert not w.notes
