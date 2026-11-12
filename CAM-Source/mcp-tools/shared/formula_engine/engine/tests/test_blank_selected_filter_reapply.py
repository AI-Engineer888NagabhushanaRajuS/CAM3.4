from pathlib import Path
import sys,math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import openpyxl,pytest
from openpyxl.worksheet.filters import FilterColumn,Filters
from excel_formula_engine import Workbook
from excel_formula_engine.values import VALUE_ERR
from excel_formula_engine.text_filters import parse_region
from xml.etree import ElementTree as ET

def make(tmp_path,with_text=False):
 p=tmp_path/'blank.xlsx';raw=openpyxl.Workbook();s=raw.active;s.title='S';s.append(['Key','Amount'])
 values=[None,'=""',' ','Alpha','Beta','Other','Other','=IF(1=1,"","Beta")','alpha']
 for row,value in enumerate(values,2):
  if value is not None:s.cell(row,1,value)
  s.cell(row,2,2**(row-2))
 s.auto_filter.ref='A1:B10';s.auto_filter.filterColumn=[FilterColumn(colId=0,filters=Filters(blank=True,filter=['Alpha']if with_text else []))]
 for row,code in enumerate(range(1,12),1):s.cell(row,4,f'=SUBTOTAL({code},B2:B10)')
 s['F1']='=D9*2';s.row_dimensions[3].hidden=True;raw.save(p);return p,raw

@pytest.mark.parametrize('text,expected',[(False,[43.666666666666664,3.,3.,128.,1.,256.,73.03652054508987,59.63406930792349,131.,5334.333333333334,3556.2222222222226]),(True,[79.,5.,5.,256.,1.,524288.,112.6765281680262,100.78095058095056,395.,12696.,10156.8])])
def test_blank_only_or_literal_text_independent_actual_filter(tmp_path,text,expected):
 p,_=make(tmp_path,text);source=p.read_bytes();w=Workbook(p);assert w.cell_value_now('S',9,4)==VALUE_ERR;w.reapply_text_filters('S')
 for row,x in enumerate(expected,1):assert math.isclose(w.cell_value_now('S',row,4),x,rel_tol=1e-12,abs_tol=0)
 assert w.cell_value_now('S',1,6)==expected[8]*2;assert p.read_bytes()==source

@pytest.mark.parametrize('value',[0,False,3,'123','é','A*','A_x000D_'])
def test_blank_selected_does_not_silently_filter_unsupported_data(tmp_path,value):
 p,raw=make(tmp_path);raw['S']['A6']=value;raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',9,4)==VALUE_ERR

def test_edit_restore_blank_to_text_requires_reapply(tmp_path):
 p,_=make(tmp_path);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==262
 w.set_value('S',2,1,'Other');assert w.cell_value_now('S',1,6)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==260
 w.set_value('S',2,1,None);assert w.cell_value_now('S',1,6)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==262

@pytest.mark.parametrize('flag',['1','true'])
def test_blank_only_zero_children_valid_boolean(flag):
 node=ET.fromstring('<autoFilter xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ref="A1:B5"><filterColumn colId="0"><filters blank="'+flag+'"/></filterColumn></autoFilter>');assert parse_region(node)is not None

@pytest.mark.parametrize('flag',['0','false','TRUE','yes','2'])
def test_empty_allowlist_without_valid_blank_still_rejects(flag):
 node=ET.fromstring('<autoFilter xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ref="A1:B5"><filterColumn colId="0"><filters blank="'+flag+'"/></filterColumn></autoFilter>');assert parse_region(node)is None

def test_cross_sheet_formula_empty_edit_restore_reapply(tmp_path):
 p,raw=make(tmp_path);raw.create_sheet('Input')['A1']='';raw['S']['A2']='=Input!A1&""';raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',9,4)==131
 w.set_value('Input',1,1,'Other');assert w.cell_value_now('S',9,4)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',9,4)==130
 w.set_formula('Input',1,1,'""');assert w.cell_value_now('S',9,4)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',9,4)==131

def test_blank_and_other_column_intersection_with_high_guard(tmp_path):
 p,raw=make(tmp_path);s=raw['S'];s['C1']='Other'
 for row in range(2,11):s.cell(row,3,'Yes'if row in(2,3)else'No')
 s.auto_filter.ref='A1:C10';s.auto_filter.filterColumn.append(FilterColumn(colId=2,filters=Filters(filter=['Yes'])));s['H1']='=SUBTOTAL(109,B2:B10)';raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',9,4)==3;assert w.cell_value_now('S',1,8)==VALUE_ERR

def test_blank_filter_keeps_header_and_outside_rows(tmp_path):
 p,raw=make(tmp_path);s=raw['S'];s['B1']=19;s['B11']=23;s['H1']='=SUBTOTAL(9,B1:B11)';raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',1,8)==173

@pytest.mark.parametrize('fragment',[
 '<filters blank="1"><filter val=""/></filters>',
 '<filters blank="1"><dateGroupItem year="2026"/></filters>',
 '<filters blank="1" other="x"/>',
 '<filters blank="1"><filter xmlns="urn:foreign" val="Alpha"/></filters>',
 '<filters blank="1"><filter val="Alpha"/><filter val="Alpha"/></filters>'])
def test_blank_metadata_does_not_bypass_other_shape_guards(fragment):
 node=ET.fromstring('<autoFilter xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ref="A1:B5"><filterColumn colId="0">'+fragment+'</filterColumn></autoFilter>');assert parse_region(node)is None
