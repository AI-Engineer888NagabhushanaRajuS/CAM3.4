"""AVERAGE CellRef rules only; no direct literal/INDEX/AVERAGEIF claim."""
import openpyxl,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,DIV0,VALUE_ERR


def model(tmp_path,args):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';other=raw.create_sheet('Other')
    for row,value in enumerate(['5',True,'x',2,'=1/0',None,0],1):s.cell(row,1,value)
    other['A1']='100';other['A2']=False;other['A3']=8
    for row,arg in enumerate(args,1):s.cell(row,4,f'=AVERAGE({arg})')
    p=tmp_path/'average-cell.xlsx';raw.save(p);return Workbook(str(p))


def test_average_cell_refs_ignore_text_logicals_and_blank_but_count_zero(tmp_path):
    args=['A1,2','A2,2','A3,2','A1,A2,A3','A6,2','A7,2','A1:A4','A5,2','A1:A3','A6']
    expected=[2,2,2,DIV0,2,1,2,DIV0,DIV0,DIV0]
    w=model(tmp_path,args)
    for row,v in enumerate(expected,1):assert w.cell_value_now('S',row,4)==v,(row,w.cell_value_now('S',row,4))
    assert not w.notes


def test_average_arithmetic_cell_values_remain_computed_arguments(tmp_path):
    w=model(tmp_path,['A1+0,2','A2+0,2','A3+0,2','A7+0,2'])
    for row,v in enumerate([3.5,1.5,VALUE_ERR,1],1):assert w.cell_value_now('S',row,4)==v
    assert not w.notes


def test_average_crosssheet_and_type_changes_retain_dependencies(tmp_path):
    w=model(tmp_path,['Other!A1,Other!A2,Other!A3','A1,2','A3,2'])
    assert w.cell_value_now('S',1,4)==8
    assert w.cell_value_now('S',2,4)==2
    assert w.cell_value_now('S',3,4)==2
    w.set_value('Other',1,1,10);assert w.cell_value_now('S',1,4)==9
    w.set_value('S',1,1,0);assert w.cell_value_now('S',2,4)==1
    w.set_formula('S',3,1,'=1/0');assert w.cell_value_now('S',3,4)==DIV0
    assert not w.notes and not w.cycle_diagnostics
