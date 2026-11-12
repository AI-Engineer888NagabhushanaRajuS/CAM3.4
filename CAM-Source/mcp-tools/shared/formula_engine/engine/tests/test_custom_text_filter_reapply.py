from pathlib import Path
from xml.etree import ElementTree as ET
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import openpyxl,pytest
from openpyxl.worksheet.filters import FilterColumn,Filters,CustomFilters,CustomFilter
from excel_formula_engine import Workbook
from excel_formula_engine.values import VALUE_ERR
from excel_formula_engine.text_filters import parse_region

def make(tmp_path,criteria=(('equal','ALPHA'),),and_=False,values=None):
 p=tmp_path/'custom.xlsx';w=openpyxl.Workbook();s=w.active;s.title='S'
 for row in [('Key','Amount'),('Alpha',2),('Beta',3),('alpha',5),('Gamma',11),('Delta',17)]:s.append(row)
 if values:
  for cell,value in values.items():s[cell]=value
 s.auto_filter.ref='A1:B6';s.auto_filter.filterColumn=[FilterColumn(colId=0,customFilters=CustomFilters(_and=and_,customFilter=[CustomFilter(operator=op,val=val)for op,val in criteria]))]
 for row,code in enumerate([1,2,3,4,5,9,109,12],1):s.cell(row,4,f'=SUBTOTAL({code},B2:B6)')
 s['F1']='=D6*2';s.row_dimensions[4].hidden=True;w.save(p);return p,w

@pytest.mark.parametrize('criteria,and_,expected',[
 ([('equal','ALPHA')],False,7),([('notEqual','Alpha')],False,31),
 ([('equal','Alpha'),('equal','Gamma')],False,18),
 ([('notEqual','Alpha'),('notEqual','Beta')],True,28),
 ([('equal','Alpha'),('notEqual','Alpha')],True,0),
 ([('equal','Alpha'),('notEqual','Alpha')],False,38)])
def test_custom_filters_match_independent_runtime_cases(tmp_path,criteria,and_,expected):
 p,_=make(tmp_path,criteria,and_);source=p.read_bytes();w=Workbook(p)
 assert w.cell_value_now('S',6,4)==VALUE_ERR
 w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==expected
 assert w.cell_value_now('S',7,4)==VALUE_ERR
 assert w.cell_value_now('S',8,4)==VALUE_ERR
 assert w.cell_value_now('S',1,6)==expected*2;assert p.read_bytes()==source

@pytest.mark.parametrize('value',[None,'',3,False,'123','1.2','1e3','é','A*','A?','A~','#VALUE!'])
def test_custom_data_unsupported_not_silently_excluded(tmp_path,value):
 p,_=make(tmp_path,values={'A3':value});w=Workbook(p);w.reapply_text_filters('S')
 assert w.cell_value_now('S',6,4)==VALUE_ERR
 assert any('filter' in n and 'unsupported' in n for n in w.notes)

def test_custom_edit_reapply_and_cross_sheet_formula_restore(tmp_path):
 p,raw=make(tmp_path);raw.create_sheet('Input')['A1']='Beta';raw['S']['A3']='=Input!A1';raw.save(p);source=p.read_bytes();w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==14
 w.set_value('Input',1,1,'ALPHA');assert w.cell_value_now('S',1,6)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==20
 w.set_formula('Input',1,1,'"Beta"');assert w.cell_value_now('S',1,6)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==14;assert source==p.read_bytes()

def test_multiple_columns_list_and_custom_intersect(tmp_path):
 p,raw=make(tmp_path,[('notEqual','Beta')]);s=raw['S'];s['C1']='Other'
 for row,val in enumerate(['Yes','Yes','No','Yes','No'],2):s.cell(row,3,val)
 s.auto_filter.ref='A1:C6';s.auto_filter.filterColumn.append(FilterColumn(colId=2,filters=Filters(filter=['Yes'])));raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==13

@pytest.mark.parametrize('fragment',[
 '<customFilters/>','<customFilters and="bad"><customFilter val="Alpha"/></customFilters>',
 '<customFilters other="1"><customFilter val="Alpha"/></customFilters>',
 '<customFilters><customFilter val="Alpha"/><customFilter val="Beta"/><customFilter val="Gamma"/></customFilters>',
 '<customFilters><customFilter/></customFilters>',
 '<customFilters><customFilter val=""/></customFilters>',
 '<customFilters><customFilter operator="greaterThan" val="Alpha"/></customFilters>',
 '<customFilters><customFilter operator="notEqual" val="123"/></customFilters>',
 '<customFilters><customFilter val="é"/></customFilters>',
 '<customFilters><customFilter val="A*"/></customFilters>',
 '<customFilters><customFilter val="Alpha" bad="1"/></customFilters>',
 '<customFilters><customFilter val="Alpha"><unknown/></customFilter></customFilters>',
 '<customFilters><filter val="Alpha"/></customFilters>',
 '<customFilters><customFilter xmlns="urn:foreign" val="Alpha"/></customFilters>'])
def test_custom_metadata_fail_closed(fragment):
 node=ET.fromstring('<autoFilter xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ref="A1:B6"><filterColumn colId="0">'+fragment+'</filterColumn></autoFilter>');assert parse_region(node)is None

@pytest.mark.parametrize('and_', ['',' and="0"',' and="false"',' and="1"',' and="true"'])
def test_valid_boolean_lexical_and_omitted_equal(and_):
 node=ET.fromstring('<autoFilter xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ref="A1:B6"><filterColumn colId="0"><customFilters'+and_+'><customFilter val="Alpha"/></customFilters></filterColumn></autoFilter>');region=parse_region(node);assert region is not None;assert region['columns'][0][1]['criteria']==(('equal','alpha'),)

@pytest.mark.parametrize('value',['Alpha_x000D_','Alpha_x005F_x000D_','Alpha_x0041_','Alpha_X000d_','Alpha\r','Alpha\n','Alpha\t','Alpha\x7f',' 123 ',' +1 ',' -1.2 ',' 1e3 '])
@pytest.mark.parametrize('mode',['list','custom'])
def test_whole_workbook_escaped_or_control_criteria_reject(tmp_path,value,mode):
 p,raw=make(tmp_path);s=raw['S']
 if mode=='list':s.auto_filter.filterColumn=[FilterColumn(colId=0,filters=Filters(filter=[value]))]
 else:s.auto_filter.filterColumn=[FilterColumn(colId=0,customFilters=CustomFilters(customFilter=[CustomFilter(operator='equal',val=value)]))]
 raw.save(p);w=Workbook(p)
 with pytest.raises(ValueError):w.reapply_text_filters('S')

@pytest.mark.parametrize('value',['Alpha_x000D_','Alpha_x005F_x000D_','Alpha_x0041_','Alpha_X000d_','Alpha\r','Alpha\n','Alpha\t','Alpha\x7f',' 123 ',' +1 ',' -1.2 ',' 1e3 '])
@pytest.mark.parametrize('mode',['list','custom'])
def test_whole_workbook_escaped_or_control_data_fail_closed(tmp_path,value,mode):
 p,raw=make(tmp_path,values={'A3':value})
 if mode=='list':raw['S'].auto_filter.filterColumn=[FilterColumn(colId=0,filters=Filters(filter=['Alpha']))];raw.save(p)
 w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==VALUE_ERR

@pytest.mark.parametrize('criteria,labels,expected',[
 ([('equal',' Alpha ')],[' Alpha ','Alpha',' alpha ','Alpha ',' Alpha'],7),
 ([('notEqual','A.B')],['A.B','AxB','a.b','A[B]','A+B'],31)])
def test_literal_whitespace_and_regex_punctuation_independent_runtime(tmp_path,criteria,labels,expected):
 p,_=make(tmp_path,criteria,values={f'A{r}':val for r,val in enumerate(labels,2)});w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==expected
