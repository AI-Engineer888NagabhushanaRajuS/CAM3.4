import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'engine'),str(Path(__file__).parent)]
from excel_formula_engine import Workbook,parse_formula
from excel_formula_engine.workbook import SheetData
from excel_formula_engine.values import NAME_ERR
from excel_formula_engine.parser import ParseError
import pytest

def make(f):
 w=Workbook();s=SheetData('Data');s.cached={(1,1):2,(2,1):3,(1,2):4,(2,2):5};s.max_row=s.max_col=2;q=SheetData('Q');q.formulas={(1,1):f};q.max_row=q.max_col=1;w.sheets={'data':s,'q':q};w.sheet_order=['data','q'];return w

def val(w):return w.cell_value_now('Q',1,1)
def test_vertical_reverse():assert val(make('SUM(Data!A2:A1)'))==5
def test_bothaxes_reverse():assert val(make('SUM(Data!B2:A1)'))==14
def test_crosscorners_reverse():assert val(make('SUM(Data!B1:A2)'))==14
def test_wholecolumns_reverse():assert val(make('SUM(Data!B:A)'))==14
def test_qualified_wholerows_reverse():assert val(make('SUM(Data!$2:$1)'))==14
def test_editinvalidationcanonicalrectangle():
 w=make('SUM(Data!B2:A1)');assert val(w)==14;w.set_value('Data',1,1,12);assert val(w)==24;w.set_value('Data',2,2,15);assert val(w)==34

def test_futureoccupiedrow_wholecolinvalidation():
 w=make('SUM(Data!B:A)');assert val(w)==14;w.set_value('Data',100,1,6);assert val(w)==20

def test_cycle_not_silently_zero():
 w=make('1');w.sheets['q'].formulas={(3,2):'SUM(B3:B2)'};w.sheets['q'].max_row=3;w.sheets['q'].max_col=2;assert str(w.cell_value_now('Q',3,2))=='#CIRC!';assert any('runtime-cycle' in n for n in w.notes)

def test_mixedstaticidentitystillrejected():
 with pytest.raises(ParseError):parse_formula('SUM(Data!B2:Other!A1)')

def test_dynamicreversalstillrefused():
 w=make('SUM(INDEX(Data!A:A,2):INDEX(Data!A:A,1))');assert val(w)==NAME_ERR;assert any('reversed-endpoint' in n for n in w.notes)

def test_qualified_absidentity():
 a=parse_formula("SUM('Data'!$B$2:'data'!$A$1)").args[0];assert (a.sheet,a.ext,a.r1,a.c1,a.r2,a.c2)==('Data',None,1,1,2,2)

def test_unqualifiednumeric_wholerow_syntax_not_widened():
 with pytest.raises(ParseError):parse_formula('SUM(2:1)')
