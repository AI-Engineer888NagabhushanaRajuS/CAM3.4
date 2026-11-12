"""Integrated guarded whole-column scope/error/invalidation, not Excel oracle."""
import sys,datetime
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'engine'))
from excel_formula_engine.workbook import Workbook,SheetData
from excel_formula_engine.values import NAME_ERR,VALUE_ERR,DIV0

def make(formula,cells=None):
 w=Workbook(today=datetime.date(2026,11,11));s=SheetData('S');s.cached=dict(cells or {(1,1):2,(2,1):3,(1,2):'yes',(2,2):'no'});s.formulas={(1,5):formula.lstrip('=')};s.max_row=max(r for r,c in list(s.cached)+list(s.formulas));s.max_col=5;w.sheets={'s':s};w.sheet_order=['s'];return w

def val(w):return w.cell_value_now('S',1,5)
def test_guard_comparison():assert val(make('SUMPRODUCT(A:A,--(B:B="yes"))'))==2
def test_blank_equality_tail_not_counted_with_numeric_guard():assert val(make('SUMPRODUCT(A:A,--(B:B=""))'))==0
def test_range_equality_and_scalar_selection():assert val(make('SUMPRODUCT(A:A,--(B:B=B1))'))==2
def test_guard_does_not_suppress_occupied_error():assert val(make('SUMPRODUCT(A:A,--(B:B=1))',{(1,1):0,(1,2):DIV0}))==DIV0
def test_new_future_guard_value_invalidates():
 w=make('SUMPRODUCT(A:A,--(B:B="yes"))');assert val(w)==2;w.set_value('S',100,2,'yes');assert val(w)==2;w.set_value('S',100,1,7);assert val(w)==9

def test_new_future_comparison_error_invalidates():
 w=make('SUMPRODUCT(A:A,--(B:B="yes"))');assert val(w)==2;w.set_value('S',100,2,DIV0);assert val(w)==DIV0

def test_no_guard_remains_unsupported():assert val(make('SUMPRODUCT(--(B:B=""))'))==NAME_ERR
def test_arithmetic_tail_remains_unsupported():assert val(make('SUMPRODUCT(A:A,1/(B:B="yes"))'))==NAME_ERR
def test_if_computed_tail_remains_unsupported():assert val(make('SUMPRODUCT(A:A,IF(B:B="yes",1,0))'))==NAME_ERR
def test_bounded_mixed_shape_not_admitted():assert val(make('SUMPRODUCT(A:A,--(B1:B2="yes"))'))==VALUE_ERR
def test_multicolumn_not_admitted():assert val(make('SUMPRODUCT(A:B,--(A:B=""))'))==NAME_ERR
def test_text_numeric_logical_guard_keeps_direct_reference_rule():assert val(make('SUMPRODUCT(A:A,--(B:B="yes"))',{(1,1):'4',(1,2):'yes',(2,1):True,(2,2):'yes'}))==0
