"""FullXLSXexternalcachetypedcells; unknown snapshot positions never guessed."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'engine'),str(Path(__file__).parent)]
from excel_formula_engine.workbook import Workbook,_decode_external_cache_cell as decode_external_cell
from excel_formula_engine.values import BLANK,REF_ERR,NA
import openpyxl
from openpyxl.workbook.external_link.external import ExternalLink,ExternalBook,ExternalSheetNames,ExternalSheetDataSet,ExternalSheetData,ExternalRow,ExternalCell
from openpyxl.packaging.relationship import Relationship

def fixture(tmp_path,cells,parent_row=1):
 p=tmp_path/'external.xlsx';w=openpyxl.Workbook();w.active.title='Q';book=ExternalBook(sheetNames=ExternalSheetNames(sheetName=['S']),sheetDataSet=ExternalSheetDataSet(sheetData=[ExternalSheetData(sheetId=0,row=[ExternalRow(r=parent_row,cell=cells)])]));link=ExternalLink(externalBook=book);link.file_link=Relationship(Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath',Target='file:///authored-external.xlsx',TargetMode='External');w._external_links=[link];w.active['A1']='=[1]S!A1';w.save(p);return Workbook(str(p))

def test_text_identity_not_coerced(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='str',v='00123')]);assert w.get_external_cell('1','S',1,1)=='00123'

def test_default_number_not_text(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',v='1.5')]);assert w.get_external_cell('1','S',1,1)==1.5

def test_boolean_not_numeric(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='b',v='0'),ExternalCell(r='B1',t='b',v='1')]);assert w.get_external_cell('1','S',1,1) is False;assert w.get_external_cell('1','S',1,2) is True

def test_typed_error_preserved(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='e',v='#N/A')]);assert w.get_external_cell('1','S',1,1)==NA

def test_present_empty_vs_absent_position(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1')]);assert w.get_external_cell('1','S',1,1) is BLANK;assert w.get_external_cell('1','S',1,2)==REF_ERR

def test_hash_text_not_error(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='str',v='#N/A')]);assert w.get_external_cell('1','S',1,1)=='#N/A'

def test_malformed_and_unsupported_refuse():
 for value,kind in [('nan','n'),('inf',None),('bad','n'),('yes','b'),('3','s'),('2026-11-11','d')]:
  v,note=decode_external_cell(value,kind);assert v==REF_ERR and note

def test_missing_book_still_unresolved(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='str',v='x')]);assert w.get_external_cell('2','S',1,1)==REF_ERR

def test_exact_numeric_lookup_does_not_match_text_id(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='str',v='123'),ExternalCell(r='B1',v='4.5')]);w.set_formula('Q',1,1,'VLOOKUP(123,[1]S!A1:B1,2,0)');assert w.cell_value_now('Q',1,1)==NA

def test_exact_text_lookup_matches_present_blank_zero_display(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='str',v='123'),ExternalCell(r='B1')]);w.set_formula('Q',1,1,'VLOOKUP("123",[1]S!A1:B1,2,0)');assert w.cell_value_now('Q',1,1)==0


def test_error_kind_arbitrary_and_unknown_values_refuse(tmp_path):
 for raw in ['not-an-error','#BOGUS!','#SPILL!']:
  w=fixture(tmp_path,[ExternalCell(r='A1',t='e',v=raw)]);assert w.get_external_cell('1','S',1,1)==REF_ERR;assert any('malformed-or-unsupported-error' in n for n in w.notes)

def test_row_reference_must_match_parent_row(tmp_path):
 w=fixture(tmp_path,[ExternalCell(r='A1',t='str',v='hidden')],parent_row=2);assert w.get_external_cell('1','S',1,1)==REF_ERR;assert w.get_external_cell('1','S',2,1)==REF_ERR;assert any('parent-row-mismatch' in n for n in w.notes)
