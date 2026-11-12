"""Dynamic INDEX endpoint validation, not support for unverified geometry."""
import openpyxl,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,REF_ERR,VALUE_ERR,NAME_ERR,NUM_ERR,DIV0


def model(tmp_path, formulas):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';other=raw.create_sheet('Other')
    for i in range(1,6):s.cell(i,1,i);other.cell(i,1,i*100)
    s['B1']=1;s['B2']=2
    for row,formula in enumerate(formulas,1):s.cell(row,4,formula)
    p=tmp_path/'endpoints.xlsx';raw.save(p);return Workbook(str(p))


def test_dynamic_index_endpoint_bounds_types_and_all_consumers(tmp_path):
    bad='INDEX(A1:A2,3):INDEX(A1:A2,4)'
    formulas=[f'=SUM({bad})',f'=SUMIFS({bad},A1:A2,99)',f'=COUNTIF({bad},99)',f'=COUNTBLANK({bad})',f'=INDEX({bad},1)',f'=SUMPRODUCT({bad})','=SUM(INDEX(A:A,1048577):INDEX(A:A,1048578))','=SUM(INDEX(A1:XFD1,16385):INDEX(A1:XFD1,16386))','=SUM(INDEX(A:A,"x"):INDEX(A:A,4))','=SUM(INDEX(A:A,-1):INDEX(A:A,4))','=SUM(INDEX(A:A,1E309):INDEX(A:A,4))','=SUM(INDEX(A:A,1/0):INDEX(A:A,4))']
    w=model(tmp_path,formulas)
    for row in range(1,13):
        got=w.cell_value_now('S',row,4)
        expected=VALUE_ERR if row==9 else NUM_ERR if row==11 else DIV0 if row==12 else REF_ERR
        assert got==expected,(row,got)


def test_dynamic_unverified_geometry_refuses_and_masked_notes_remain(tmp_path):
    formulas=['=IFERROR(SUM(INDEX(A:A,0):INDEX(A:A,2)),7)','=IFERROR(SUM(INDEX(A:A,1):INDEX(Other!A:A,2)),7)','=IFERROR(SUM(INDEX(A:A,4):INDEX(A:A,2)),7)','=IFERROR(SUM(INDEX(A:B,1):INDEX(A:B,2)),7)']
    w=model(tmp_path,formulas)
    for row in range(1,5):assert w.cell_value_now('S',row,4)==7
    for label in ['zero-index-endpoint-geometry','mixed-sheet-or-book-endpoints','reversed-endpoint-geometry','non-vector-index-endpoint']:
        assert any(label in note for note in w.notes),label


def test_dynamic_valid_vectors_selected_reads_and_endpoint_edits(tmp_path):
    formulas=['=SUM(INDEX(A1:A5,B1):INDEX(A1:A5,B2))','=SUM(INDEX(A1:A5,"1"):INDEX(A1:A5,2.9))','=SUM(INDEX(S!A:A,1):INDEX(s!A:A,2))','=SUMIFS(INDEX(A:A,1):INDEX(A:A,2),INDEX(A:A,1):INDEX(A:A,2),">0")','=COUNTIF(INDEX(A:A,1):INDEX(A:A,2),">0")']
    w=model(tmp_path,formulas)
    for row,expected in enumerate([3,3,3,3,2],1):assert w.cell_value_now('S',row,4)==expected
    w.set_value('S',2,2,3);assert w.cell_value_now('S',1,4)==6
    w.set_value('S',3,1,10);assert w.cell_value_now('S',1,4)==13
    assert not w.notes and not w.cycle_diagnostics
