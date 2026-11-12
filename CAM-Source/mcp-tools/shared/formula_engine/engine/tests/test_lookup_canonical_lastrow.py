"""Authored canonical lastrow-shape witnesses, not an Excel oracle."""
import sys,datetime
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'engine'),str(Path(__file__).parent)]
from excel_formula_engine.workbook import Workbook,SheetData
from excel_formula_engine.values import NA,DIV0,BLANK

def make(data):
 w=Workbook(today=datetime.date(2026,11,11));s=SheetData('Data');s.cached={k:BLANK if v is None else v for k,v in data.items()};s.max_row=max([r for r,c in data] or [1]);s.max_col=1;q=SheetData('Q');q.max_row=q.max_col=1;q.formulas={(1,1):'LOOKUP(2,1/(Data!A:A<>""),ROW(Data!A:A))'};w.sheets={'data':s,'q':q};w.sheet_order=['data','q'];return w

def val(w):return w.cell_value_now('Q',1,1)
def test_last_number_text_zero_false_not_omitted():
 for value in [0,False,'x',23]:assert val(make({(1,1):'header',(9,1):value}))==9

def test_empty_string_and_physical_blanks_not_selected():assert val(make({(1,1):'header',(9,1):'',(10,1):None}))==1
def test_error_does_not_become_numeric_lookup_match():assert val(make({(1,1):'header',(9,1):DIV0}))==1
def test_all_blank_no_match():assert val(make({(1,1):''}))==NA
def test_future_value_and_restore_invalidation():
 w=make({(1,1):'header'});assert val(w)==1;w.set_value('Data',100,1,'new');assert val(w)==100;w.set_value('Data',100,1,'');assert val(w)==1

def test_formula_empty_string_vs_value_invalidation():
 w=make({(1,1):'header'});w.set_formula('Data',15,1,'""');assert val(w)==1;w.set_formula('Data',15,1,'2+3');assert val(w)==15

def test_same_sheet_case_variant():
 w=make({(4,1):'x'});w.sheets['q'].formulas[(1,1)]='LOOKUP(2,1/(DATA!A:A<>""),ROW(data!A:A))';assert val(w)==4

def test_other_shapes_not_admitted():
 from excel_formula_engine import parse_formula
 from excel_formula_engine.evaluator import EvalContext
 from excel_formula_engine.functions import _lookup_canonical_lastrow as lastrow_lookup
 w=make({(4,1):'x'});ctx=EvalContext(w,'Q',1,1,0)
 for f in ['LOOKUP(3,1/(Data!A:A<>""),ROW(Data!A:A))','LOOKUP(2,2/(Data!A:A<>""),ROW(Data!A:A))','LOOKUP(2,1/(Data!A:A=""),ROW(Data!A:A))','LOOKUP(2,1/(Data!A:A<>""),ROW(Data!B:B))','LOOKUP(2,1/(Data!A1:A10<>""),ROW(Data!A1:A10))','LOOKUP(2,1/(Data!A:A<>""),ROW(Q!A:A))']:
  assert lastrow_lookup(parse_formula(f).args,ctx) is None
