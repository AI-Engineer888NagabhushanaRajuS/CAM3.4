import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/"engine"),str(Path(__file__).parent)]
import zipfile,pytest
from cache_source_mapping import read_sources,bound_empty_snapshot,NS,R,P

def package(tmp_path,*,target='worksheets/sheet9.xml',relattrs='',reltype=R+'/worksheet',sheets=None,rows=None,extra_rel='',ns=NS):
 path=tmp_path/'test.xlsx'
 if sheets is None:sheets='<sheet name="Not Sheet1" sheetId="8" r:id="rId7"/>'
 if rows is None:rows='<row r="2"><c r="B2" t="str"><f>INDEX(A1:A3,1)&amp;""</f><v/></c></row>'
 with zipfile.ZipFile(path,'w') as z:
  z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="{R}"><sheets>{sheets}</sheets></workbook>')
  z.writestr('xl/_rels/workbook.xml.rels',f'<Relationships xmlns="{P}"><Relationship Id="rId7" Type="{reltype}" Target="{target}" {relattrs}/>{extra_rel}</Relationships>')
  z.writestr('xl/worksheets/sheet9.xml',f'<worksheet xmlns="{NS}"><sheetData>{rows}</sheetData></worksheet>')
 return path

def test_bound_nonordinal(tmp_path):
 d=read_sources(package(tmp_path));assert bound_empty_snapshot(d,'NOT SHEET1','B2','INDEX(A1:A3,1)&""');assert d[('not sheet1','B2')].part=='xl/worksheets/sheet9.xml'
def test_wrong_formula(tmp_path):assert not bound_empty_snapshot(read_sources(package(tmp_path)),'Not Sheet1','B2','INDEX(A1:A3,2)&""')
def test_wrong_sheet(tmp_path):assert not bound_empty_snapshot(read_sources(package(tmp_path)),'Sheet1','B2','INDEX(A1:A3,1)&""')
def test_wrong_cell(tmp_path):assert not bound_empty_snapshot(read_sources(package(tmp_path)),'Not Sheet1','A2','INDEX(A1:A3,1)&""')
def test_absolute_target(tmp_path):assert len(read_sources(package(tmp_path,target='/xl/worksheets/sheet9.xml')))==1
@pytest.mark.parametrize('target',['https://example.invalid/sheet.xml','../../outside.xml','../outside.xml','worksheets/a.xml?x','worksheets/%61.xml'])
def test_bad_target(tmp_path,target):
 with pytest.raises(ValueError):read_sources(package(tmp_path,target=target))
def test_external(tmp_path):
 with pytest.raises(ValueError):read_sources(package(tmp_path,relattrs='TargetMode="External"'))
def test_wrong_type(tmp_path):
 with pytest.raises(ValueError):read_sources(package(tmp_path,reltype=R+'/chartsheet'))
def test_missing_relation(tmp_path):
 with pytest.raises(ValueError):read_sources(package(tmp_path,sheets='<sheet name="S" sheetId="1" r:id="missing"/>'))
def test_duplicate_relationship(tmp_path):
 with pytest.raises(ValueError):read_sources(package(tmp_path,extra_rel='<Relationship Id="rId7"/>'))
def test_duplicate_sheet_name(tmp_path):
 with pytest.raises(ValueError):read_sources(package(tmp_path,sheets='<sheet name="S" sheetId="1" r:id="rId7"/><sheet name="s" sheetId="2" r:id="rId7"/>'))
def test_duplicate_cell(tmp_path):
 with pytest.raises(ValueError):read_sources(package(tmp_path,rows='<row r="1"><c r="A1"/><c r="A1"/></row>'))
def test_row_mismatch(tmp_path):
 d=read_sources(package(tmp_path,rows='<row r="1"><c r="A2" t="str"><f>1</f><v/></c></row>'));assert not bound_empty_snapshot(d,'Not Sheet1','A2','1')
def test_shared_follower_unbound(tmp_path):
 d=read_sources(package(tmp_path,rows='<row r="1"><c r="A1" t="str"><f t="shared" si="0"/><v/></c></row>'));assert not bound_empty_snapshot(d,'Not Sheet1','A1','')
def test_namespace(tmp_path):
 with pytest.raises(ValueError):read_sources(package(tmp_path,ns='urn:other'))
def test_no_write(tmp_path):
 p=package(tmp_path);before=p.read_bytes();read_sources(p);assert p.read_bytes()==before

def shared_rows(master='si="2" ref="A1:A3"',follower='si="2"',cell='A2',extra=''):
 return f'<row r="1"><c r="A1" t="str"><f t="shared" {master}>B1&amp;""</f><v/></c></row><row r="2"><c r="{cell}" t="str"><f t="shared" {follower}/><v/></c>{extra}</row>'
def test_shared_valid(tmp_path):
 d=read_sources(package(tmp_path,rows=shared_rows()));assert bound_empty_snapshot(d,'Not Sheet1','A2','B2&""');assert bound_empty_snapshot(d,'Not Sheet1','A1','B1&""')
@pytest.mark.parametrize('master,follower',[('si="2" ref="A1:A3"','si="3"'),('si="2"','si="2"'),('si="2" ref="A1:A1"','si="2"'),('si="2" ref="A1:XFE3"','si="2"'),('si="-2" ref="A1:A3"','si="-2"'),('si="2" ref="A1:A3"','si="2" ref="A1:A3"'),('si="2" ref="A3:A1"','si="2"')])
def test_shared_unbindable(tmp_path,master,follower):
 d=read_sources(package(tmp_path,rows=shared_rows(master,follower)));assert not bound_empty_snapshot(d,'Not Sheet1','A2','B2&""')
def test_duplicate_shared_master(tmp_path):
 d=read_sources(package(tmp_path,rows=shared_rows(extra='<c r="B2" t="str"><f t="shared" si="2" ref="B2:B3">C2&amp;""</f><v/></c>')));assert not bound_empty_snapshot(d,'Not Sheet1','A2','B2&""')
def test_shared_wrong_model_translation(tmp_path):
 d=read_sources(package(tmp_path,rows=shared_rows()));assert not bound_empty_snapshot(d,'Not Sheet1','A2','B1&""')


def test_invalid_master_row_cannot_authorize_follower(tmp_path):
 rows='<row r="9"><c r="A1" t="str"><f t="shared" si="2" ref="A1:A3">B1&amp;""</f><v/></c></row><row r="2"><c r="A2" t="str"><f t="shared" si="2"/><v/></c></row>'
 d=read_sources(package(tmp_path,rows=rows));assert not bound_empty_snapshot(d,'Not Sheet1','A2','B2&""')

def test_illegal_master_coordinate_cannot_authorize_follower(tmp_path):
 rows='<row r="1"><c r="XFE1" t="str"><f t="shared" si="2" ref="A1:XFE3">B1&amp;""</f><v/></c></row><row r="2"><c r="A2" t="str"><f t="shared" si="2"/><v/></c></row>'
 d=read_sources(package(tmp_path,rows=rows));assert not bound_empty_snapshot(d,'Not Sheet1','A2','B2&""')
