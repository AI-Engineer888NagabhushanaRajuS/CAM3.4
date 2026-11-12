"""Refuse conflicting explicit static identities; no Excel 3D semantics claim."""
import openpyxl,sys,pytest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,NAME_ERR
from excel_formula_engine.parser import parse_formula,ParseError,RangeRef


def test_conflicting_explicit_static_sheet_book_identities_refused():
    for f in ['=SUM(S!A1:Other!A2)',"=SUM('S'!A1:'Other'!A2)",'=SUM(S!A:A:Other!A:A)','=SUM([1]S!A1:[2]S!A2)','=SUM([1]S!A1:S!A2)','=SUM(S!A1:[1]S!A2)']:
        with pytest.raises(ParseError):parse_formula(f)
    for f in ['=SUM(S!A:Other!B)','=SUM([1]S!A:[2]S!B)']:
        with pytest.raises(ParseError,match='unsupported-reference:mixed-explicit'):parse_formula(f)


def test_same_explicit_and_inherited_static_identities_preserved():
    for f,sheet,book in [('=SUM(S!A1:s!A2)','S',None),("=SUM('S'!$A$1:'s'!$A$2)",'S',None),('=SUM([1]S!A1:[1]s!A2)','S','1'),('=SUM(S!A1:A2)','S',None),('=SUM(A1:S!A2)','S',None),('=SUM(S!A:s!B)','S',None)]:
        ref=parse_formula(f).args[0];assert isinstance(ref,RangeRef);assert (ref.sheet,ref.ext)==(sheet,book)


def test_masked_static_identity_refusal_notes_persist_across_parse_cache(tmp_path):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';other=raw.create_sheet('Other');s['A1']=1;s['A2']=2;other['A1']=100;other['A2']=200
    s['D1']='=SUM(S!A1:Other!A2)';s['D2']='=IFERROR(D1,7)';s['D3']='=IFERROR(SUM(S!A1:Other!A2),7)';s['D4']=s['D3'].value;s['D5']='=SUM(S!A1:s!A2)';s['D6']='=IFERROR(D3,7)'
    p=tmp_path/'identity.xlsx';raw.save(p);w=Workbook(str(p))
    assert w.cell_value_now('S',1,4)==NAME_ERR
    assert w.cell_value_now('S',2,4)==7
    assert w.cell_value_now('S',3,4)==NAME_ERR
    assert w.cell_value_now('S',4,4)==NAME_ERR
    assert w.cell_value_now('S',6,4)==7
    assert w.cell_value_now('S',5,4)==3
    assert sum('unsupported-reference:mixed-explicit-sheet-or-book-range' in n for n in w.notes)==3
    # Parse-cache hit after normal value invalidation still carries the blocker.
    w.set_formula('S',1,4,'=SUM(S!A1:Other!A2)')
    assert w.cell_value_now('S',1,4)==NAME_ERR
    assert any('unsupported-reference:mixed-explicit' in n for n in w.notes)
