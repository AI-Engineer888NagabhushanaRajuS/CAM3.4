from pathlib import Path
import sys,math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import openpyxl,pytest
from excel_formula_engine import Workbook
from excel_formula_engine.values import VALUE_ERR,DIV0,NUM_ERR
CODES=[6,7,8,10,11]

def make(tmp_path,values,hidden=(),filter_=False,formula_suffix=''):
 p=tmp_path/'stats.xlsx';raw=openpyxl.Workbook();s=raw.active;s.title='S'
 for row,v in enumerate(values,1):
  if v is not None:s.cell(row,1,v)
 for row,code in enumerate(CODES,1):
  s.cell(row,3,f'=SUBTOTAL({code},A1:A{len(values)}{formula_suffix})');s.cell(row,4,f'=SUBTOTAL({100+code},A1:A{len(values)}{formula_suffix})')
 for row in hidden:s.row_dimensions[row].hidden=True
 if filter_:
  s['F1']='Key'
  for row in range(2,len(values)+1):s.cell(row,6,'Alpha')
  s.auto_filter.ref=f'A1:F{len(values)}';s.auto_filter.add_filter_column(5,['Alpha'])
 raw.save(p);return p,raw

@pytest.mark.parametrize('values,expected',[
 ([2,3,5,11,17],[5610.,6.308724118235002,5.642694391866354,39.8,31.84]),
 ([None,'text',None,'=""'],[0.,DIV0,DIV0,DIV0,DIV0]),
 ([5,None,None,'4'],[5.,DIV0,0.,DIV0,0.]),
 ([2,3,'=1/0',5],[DIV0]*5),
 ([2,3,'=SUBTOTAL(9,A1:A2)',5],[30.,1.5275252316519465,1.247219128924647,2.333333333333333,1.5555555555555554]),
 ([-2,0,5,8],[0.,4.573474244670748,3.960744879438715,20.916666666666668,15.6875]),
 ([1e12+1,1e12+2,1e12+3],[1.000000000006e36,1.,0.816496580927726,1.,2/3])])
def test_numeric_reference_cases_match_independent_secondary(tmp_path,values,expected):
 p,_=make(tmp_path,values);source=p.read_bytes();w=Workbook(p)
 for row,expected in enumerate(expected,1):
  for col in(3,4):
   got=w.cell_value_now('S',row,col)
   if hasattr(expected,'code'):assert got==expected
   else:assert math.isclose(got,expected,rel_tol=1e-12,abs_tol=1e-12)
 assert p.read_bytes()==source

@pytest.mark.parametrize('logical',[True,False,'=1=1','=1=2'])
def test_logical_reference_disagreement_fails_closed(tmp_path,logical):
 p,_=make(tmp_path,[2,logical,5]);w=Workbook(p)
 for row in range(1,6):
  assert w.cell_value_now('S',row,3)==VALUE_ERR
 assert any('reference-logical-unverified'in n for n in w.notes)

@pytest.mark.parametrize('nonfinite',[float('inf'),float('-inf'),float('nan')])
def test_nonfinite_model_edit_not_numeric_success(tmp_path,nonfinite):
 p,_=make(tmp_path,[2,3,5]);w=Workbook(p);w.set_value('S',2,1,nonfinite)
 for row in range(1,6):assert w.cell_value_now('S',row,3)==VALUE_ERR
 assert any('nonfinite-input'in n for n in w.notes)

def test_product_overflow_and_zero_no_wrong_infinity(tmp_path):
 p,_=make(tmp_path,[1e200,1e200]);w=Workbook(p);assert w.cell_value_now('S',1,3)==NUM_ERR
 w.set_value('S',2,1,0);assert w.cell_value_now('S',1,3)==0

def test_model_edit_restore_transitive_dependents(tmp_path):
 p,raw=make(tmp_path,[2,3,5]);raw['S']['F1']='=C1*2';raw.save(p);source=p.read_bytes();w=Workbook(p);assert w.cell_value_now('S',1,6)==60
 w.set_value('S',2,1,4);assert w.cell_value_now('S',1,6)==80
 w.set_value('S',2,1,3);assert w.cell_value_now('S',1,6)==60;assert source==p.read_bytes()

def test_default_active_filter_all_new_codes_guarded(tmp_path):
 p,_=make(tmp_path,[2,3,5],filter_=True);w=Workbook(p)
 for row in range(1,6):
  assert w.cell_value_now('S',row,3)==VALUE_ERR;assert w.cell_value_now('S',row,4)==VALUE_ERR
 assert any('active-filter-unsupported'in n for n in w.notes)

@pytest.mark.parametrize('value',[1e151,-1e151,1e-151,-1e-151])
def test_statistical_extreme_domain_explicitly_unverified(tmp_path,value):
 p,_=make(tmp_path,[2,value,5]);w=Workbook(p)
 for row in range(2,6):assert w.cell_value_now('S',row,3)==VALUE_ERR
 assert any('extreme-magnitude-unverified'in n for n in w.notes)

def test_manual_hidden_hundred_series_secondary_oracle(tmp_path):
 p,_=make(tmp_path,[2,3,5,11,17],hidden=[2]);w=Workbook(p)
 low=[5610.,6.308724118235002,5.642694391866354,39.8,31.84];high=[1870.,6.652067347825035,5.7608593109014565,44.25,33.1875]
 for row,(a,b)in enumerate(zip(low,high),1):
  assert math.isclose(w.cell_value_now('S',row,3),a,rel_tol=1e-12)
  assert math.isclose(w.cell_value_now('S',row,4),b,rel_tol=1e-12)

def test_overlapping_multiple_refs_preserved_secondary_oracle(tmp_path):
 p,_=make(tmp_path,[2,3,5],formula_suffix=',A1:A2');w=Workbook(p);expected=[180.,1.224744871391589,1.0954451150103321,1.5,1.2]
 for row,value in enumerate(expected,1):assert math.isclose(w.cell_value_now('S',row,3),value,rel_tol=1e-12)

def test_explicit_text_filter_new_codes_and_high_guard(tmp_path):
 p,raw=make(tmp_path,['Amount',2,3,5,11,17]);s=raw['S'];s['F1']='Key'
 for row,label in enumerate(['Alpha','Beta','alpha','Gamma','Delta'],2):s.cell(row,6,label)
 s.auto_filter.ref='A1:F6';s.auto_filter.add_filter_column(5,['Alpha']);raw.save(p);w=Workbook(p);w.reapply_text_filters('S')
 # Actual independent filter oracle selected rows2/4: numeric2 and5.
 expected=[10.,2.1213203435596424,1.5,4.5,2.25]
 for row,value in enumerate(expected,1):
  assert math.isclose(w.cell_value_now('S',row,3),value,rel_tol=1e-12)
  assert w.cell_value_now('S',row,4)==VALUE_ERR

def test_reference_logical_hidden_exclusion_before_domain_gate(tmp_path):
 p,_=make(tmp_path,[2,True,5],hidden=[2]);w=Workbook(p)
 for row in range(1,6):assert w.cell_value_now('S',row,3)==VALUE_ERR
 assert w.cell_value_now('S',1,4)==10
