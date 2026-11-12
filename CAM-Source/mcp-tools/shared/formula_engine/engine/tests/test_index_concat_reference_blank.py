import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/"engine"),str(Path(__file__).parent)]
from excel_formula_engine import Workbook
from excel_formula_engine.workbook import SheetData
from excel_formula_engine.values import BLANK,NA
import pytest

def make(f):
 w=Workbook();s=SheetData('S');s.cached={(2,1):'',(3,1):0,(4,1):'00123',(5,1):False,(6,1):NA};s.formulas={(1,3):f};s.max_row=6;s.max_col=3;w.sheets={'s':s};w.sheet_order=['s'];return w
@pytest.mark.parametrize('formula,expected',[
 ('INDEX(A1:A6,1)&""',''),('"x"&INDEX(A1:A6,1)','x'),('INDEX(A1:A6,2)&""',''),('INDEX(A1:A6,3)&""','0'),('INDEX(A1:A6,4)&""','00123'),('INDEX(A1:A6,5)&""','FALSE'),('INDEX(A1:A6,6)&""',NA),('INDEX(A1:A6,1)',0),('INDEX(A1:A6,1)+1',1),('INDEX(INDEX(A:A,1):INDEX(A:A,6),1)&""',''),('INDEX(A1:A6,MATCH(0,A3:A3,0))&""',''),('"x"&INDEX(A1:A6,1)&INDEX(A1:A6,3)','x0')])
def test_semantics(formula,expected):assert make(formula).cell_value_now('S',1,3)==expected

def test_invalidation():
 w=make('INDEX(A1:A6,1)&""');assert w.cell_value_now('S',1,3)=='';w.set_value('S',1,1,0);assert w.cell_value_now('S',1,3)=='0';w.set_value('S',1,1,None);assert w.cell_value_now('S',1,3)==''

def test_sibling_scope_does_not_leak():assert make('(INDEX(A1:A6,1)&"")&INDEX(A1:A6,3)').cell_value_now('S',1,3)=='0'
