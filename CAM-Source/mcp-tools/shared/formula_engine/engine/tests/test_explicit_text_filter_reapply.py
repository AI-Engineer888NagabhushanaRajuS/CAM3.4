from pathlib import Path
import sys,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest,openpyxl
from openpyxl.worksheet.filters import FilterColumn,Filters,CustomFilters,CustomFilter
from excel_formula_engine import Workbook
from excel_formula_engine.values import VALUE_ERR
from excel_formula_engine.text_filters import parse_region,ascii_literal
from xml.etree import ElementTree as ET

def make(tmp_path,values=None,filters=None):
 p=tmp_path/'text_filter.xlsx';w=openpyxl.Workbook();s=w.active;s.title='S'
 for row in [('Key','Amount'),('Alpha',2),('Beta',3),('Alpha',5),('',11)]:s.append(row)
 if values:
  for cell,value in values.items():s[cell]=value
 s.auto_filter.ref='A1:B5';s.auto_filter.add_filter_column(0,filters or ['Alpha']);s.row_dimensions[3].hidden=True;s.row_dimensions[4].hidden=True
 for r,code in enumerate([1,2,3,4,5,9,101,109],1):s.cell(r,4,f'=SUBTOTAL({code},B2:B5)')
 s['F1']='=D6*2';w.save(p);return p,w

def test_default_fail_closed_explicit_reapply_ignores_hidden_cause(tmp_path):
 p,_=make(tmp_path);w=Workbook(p);assert w.cell_value_now('S',6,4)==VALUE_ERR;w.reapply_text_filters('S')
 assert [w.cell_value_now('S',i,4)for i in range(1,7)]==[3.5,2.,2.,5.,2.,7.]
 assert w.cell_value_now('S',7,4)==VALUE_ERR and w.cell_value_now('S',8,4)==VALUE_ERR

def test_edit_requires_explicit_reapply_transitive_restore(tmp_path):
 p,_=make(tmp_path);original=p.read_bytes();w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==14
 w.set_value('S',3,1,'Alpha');assert w.cell_value_now('S',6,4)==VALUE_ERR
 w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==20
 w.set_value('S',3,1,'Beta');assert w.cell_value_now('S',1,6)==VALUE_ERR
 w.reapply_text_filters('S');assert w.cell_value_now('S',1,6)==14;assert p.read_bytes()==original

def test_cross_sheet_edit_and_formula_change_invalidate_view(tmp_path):
 p,raw=make(tmp_path);raw.create_sheet('Input')['A1']='Alpha';raw['S']['A2']="=Input!A1";raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==7
 w.set_value('Input',1,1,'Beta');assert w.cell_value_now('S',6,4)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==5
 w.set_formula('Input',1,1,'"Alpha"');assert w.cell_value_now('S',6,4)==VALUE_ERR;w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==7

@pytest.mark.parametrize('value',[3,False,'123','1.2','1e3','é','A*','A?','A~'])
def test_ambiguous_value_types_not_silently_excluded(tmp_path,value):
 p,_=make(tmp_path,{'A3':value});w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==VALUE_ERR;assert any('text-filter-value-unsupported'in n for n in w.notes)

@pytest.mark.parametrize('criterion',['123','1e3','A*','é'])
def test_ambiguous_criteria_rejected(tmp_path,criterion):
 p,_=make(tmp_path,filters=[criterion]);w=Workbook(p)
 with pytest.raises(ValueError):w.reapply_text_filters('S')

def test_multiple_values_and_columns_are_intersection(tmp_path):
 p,raw=make(tmp_path,filters=['Alpha','Beta']);s=raw['S'];s['C1']='Other';s['C2']='Yes';s['C3']='No';s['C4']='Yes';s['C5']='Yes';s.auto_filter.ref='A1:C5';s.auto_filter.add_filter_column(2,['Yes']);raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',6,4)==7

def test_header_and_outside_rows_not_filtered(tmp_path):
 p,raw=make(tmp_path);s=raw['S'];s['B6']=13;s['G1']='=SUBTOTAL(9,B1:B2)';s['G2']='=SUBTOTAL(9,B6:B6)';raw.save(p);w=Workbook(p);w.reapply_text_filters('S');assert w.cell_value_now('S',1,7)==2;assert w.cell_value_now('S',2,7)==13

def test_custom_filter_table_extension_fail_closed(tmp_path):
 p,raw=make(tmp_path);s=raw['S'];s.auto_filter.filterColumn=[FilterColumn(colId=0,customFilters=CustomFilters(customFilter=[CustomFilter(operator='greaterThan',val='Alpha')]))];raw.save(p);w=Workbook(p)
 with pytest.raises(ValueError):w.reapply_text_filters('S')

@pytest.mark.parametrize('fragment',[
 '<filterColumn colId="2"><filters><filter val="Alpha"/></filters></filterColumn>',
 '<filterColumn colId="0"><filters blank="bad"><filter val="Alpha"/></filters></filterColumn>',
 '<filterColumn colId="0"><filters><filter val="Alpha"/><filter val="Alpha"/></filters></filterColumn>',
 '<filterColumn colId="0"><filters><dateGroupItem year="2026"/></filters></filterColumn>',
 '<filterColumn colId="0"><filters><filter val="Alpha"/></filters></filterColumn><filterColumn colId="0"><filters><filter val="Beta"/></filters></filterColumn>'])
def test_raw_metadata_rejects_ambiguous_subset(fragment):
 root=ET.fromstring('<autoFilter xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ref="A1:B5">'+fragment+'</autoFilter>');assert parse_region(root)is None

@pytest.mark.parametrize('mutation',['relationships_namespace','relationship_child_namespace','worksheet_type','target_mode','duplicate_relation','target_external','target_nonworksheet','target_query','target_duplicate_part','workbook_namespace','duplicate_sheets','foreign_sheet','duplicate_sheet_name','duplicate_sheetid','worksheet_namespace','duplicate_sheetData','duplicate_zip_member'])
def test_whole_workbook_adversarial_identity_rejects(tmp_path,mutation):
 from excel_formula_engine.text_filters import source_text_filters
 p,raw=make(tmp_path);raw.create_sheet('Second');raw.save(p)
 with zipfile.ZipFile(p)as z:base={n:z.read(n)for n in z.namelist()}
 P='http://schemas.openxmlformats.org/package/2006/relationships';M='http://schemas.openxmlformats.org/spreadsheetml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
 rels=ET.fromstring(base['xl/_rels/workbook.xml.rels']);wb=ET.fromstring(base['xl/workbook.xml']);sheets=wb.find('{'+M+'}sheets');sheet=ET.fromstring(base['xl/worksheets/sheet1.xml']);worksheetrels=[el for el in rels if el.get('Type')==R+'/worksheet'];import copy
 if mutation=='relationships_namespace':rels.tag='{http://example.invalid}Relationships'
 elif mutation=='relationship_child_namespace':worksheetrels[0].tag='{http://example.invalid}Relationship'
 elif mutation=='worksheet_type':worksheetrels[0].set('Type','http://example.invalid/worksheet')
 elif mutation=='target_mode':worksheetrels[0].set('TargetMode','Wrong')
 elif mutation=='duplicate_relation':rels.append(copy.deepcopy(worksheetrels[0]))
 elif mutation=='target_external':worksheetrels[0].set('TargetMode','External')
 elif mutation=='target_nonworksheet':worksheetrels[0].set('Target','styles.xml')
 elif mutation=='target_query':worksheetrels[0].set('Target','/xl/worksheets/sheet1.xml?x=1')
 elif mutation=='target_duplicate_part':worksheetrels[1].set('Target',worksheetrels[0].get('Target'))
 elif mutation=='workbook_namespace':wb.tag='{http://example.invalid}workbook'
 elif mutation=='duplicate_sheets':wb.append(copy.deepcopy(sheets))
 elif mutation=='foreign_sheet':sheets[0].tag='{http://example.invalid}sheet'
 elif mutation=='duplicate_sheet_name':sheets[1].set('name',sheets[0].get('name'))
 elif mutation=='duplicate_sheetid':sheets[1].set('sheetId',sheets[0].get('sheetId'))
 elif mutation=='worksheet_namespace':sheet.tag='{http://example.invalid}worksheet'
 elif mutation=='duplicate_sheetData':sheet.append(copy.deepcopy(sheet.find('{'+M+'}sheetData')))
 base['xl/_rels/workbook.xml.rels']=ET.tostring(rels);base['xl/workbook.xml']=ET.tostring(wb);base['xl/worksheets/sheet1.xml']=ET.tostring(sheet)
 q=tmp_path/(mutation+'.xlsx')
 with zipfile.ZipFile(q,'w')as z:
  for n,b in base.items():z.writestr(n,b)
  if mutation=='duplicate_zip_member':z.writestr('xl/worksheets/sheet1.xml',base['xl/worksheets/sheet1.xml'])
 with pytest.raises((ValueError,KeyError)):source_text_filters(q)
 try:w=Workbook(q)
 except Exception:return # owning loader rejected the malformed workbook first
 with pytest.raises((ValueError,KeyError)):w.reapply_text_filters('S')
