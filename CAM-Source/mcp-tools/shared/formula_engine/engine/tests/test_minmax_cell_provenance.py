"""Microsoft MIN/MAX direct CellRef rules, not general function provenance."""
import openpyxl,pytest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,DIV0,VALUE_ERR


def model(tmp_path,fn,args):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';other=raw.create_sheet('Other')
    for row,value in enumerate(['5',True,'x',2,'=1/0',None,0],1):s.cell(row,1,value)
    other['A1']='100';other['A2']=False;other['A3']=8
    for row,arg in enumerate(args,1):s.cell(row,4,f'={fn}({arg})')
    p=tmp_path/(fn+'.xlsx');raw.save(p);return Workbook(str(p))


@pytest.mark.parametrize('fn',['MIN','MAX'])
def test_minmax_direct_cell_refs_ignore_text_logicals_blanks_and_keep_zero(tmp_path,fn):
    args=['A1,2','A2,2','A3,2','A1,A2,A3','A6,2','A7,2','A1:A4','A5,2']
    expected=[2,2,2,0,2,0 if fn=='MIN' else 2,2,DIV0]
    w=model(tmp_path,fn,args)
    for row,v in enumerate(expected,1):assert w.cell_value_now('S',row,4)==v,(fn,row,w.cell_value_now('S',row,4))
    assert not w.notes


@pytest.mark.parametrize('fn',['MIN','MAX'])
def test_minmax_direct_literals_and_arithmetic_remain_value_arguments(tmp_path,fn):
    args=['"5",TRUE,2','"x",2','A1+0,2','A2+0,2','A3&"",2']
    expected=[1 if fn=='MIN' else 5,VALUE_ERR,2 if fn=='MIN' else 5,1 if fn=='MIN' else 2,VALUE_ERR]
    w=model(tmp_path,fn,args)
    for row,v in enumerate(expected,1):assert w.cell_value_now('S',row,4)==v
    assert not w.notes


@pytest.mark.parametrize('fn',['MIN','MAX'])
def test_minmax_crosssheet_and_edits_retain_dependencies(tmp_path,fn):
    w=model(tmp_path,fn,['Other!A1,Other!A2,Other!A3','A1,2','A3,2'])
    assert w.cell_value_now('S',1,4)==8
    assert w.cell_value_now('S',2,4)==2
    assert w.cell_value_now('S',3,4)==2
    w.set_value('Other',1,1,10);assert w.cell_value_now('S',1,4)==(8 if fn=='MIN' else 10)
    w.set_value('S',1,1,-3);assert w.cell_value_now('S',2,4)==(-3 if fn=='MIN' else 2)
    w.set_formula('S',3,1,'=1/0');assert w.cell_value_now('S',3,4)==DIV0
    assert not w.notes and not w.cycle_diagnostics
