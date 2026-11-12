"""Cell:INDEX parsing reaches existing bounded endpoint binding, not new geometry."""
import openpyxl,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,REF_ERR,VALUE_ERR
from excel_formula_engine.parser import parse_formula,DynRange,FuncCall,CellRef,ParseError


def model(tmp_path,formulas):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';other=raw.create_sheet('Other')
    for i in range(1,6):s.cell(i,1,i);other.cell(i,1,i*100)
    s['B1']=4
    for row,formula in enumerate(formulas,1):s.cell(row,4,formula)
    p=tmp_path/'cell-index.xlsx';raw.save(p);return Workbook(str(p))


def test_cell_index_syntax_and_static_ranges_unchanged():
    for f in ['=SUM(A2:INDEX(A1:A5,4))','=SUM($A$2:INDEX($A$1:$A$5,4))',"=SUM('S'!A2:INDEX('S'!A1:A5,4))",'=SUM(A2:_xlfn.INDEX(A1:A5,4))']:
        node=parse_formula(f);assert isinstance(node,FuncCall);assert isinstance(node.args[0],DynRange);assert isinstance(node.args[0].l,CellRef)
    from excel_formula_engine.parser import RangeRef
    for f in ['=SUM(A2:A4)','=SUM(A:A)',"=SUM('S'!A2:A4)"]:
        assert isinstance(parse_formula(f).args[0],RangeRef)
    for f in ['=SUM(A2:3)','=SUM(A2:SUM(A1:A5))','=SUM(1:1)']:
        try:parse_formula(f)
        except ParseError:pass
        else:raise AssertionError(f)


def test_cell_index_evaluation_bounds_edits_and_selected_cycles(tmp_path):
    formulas=['=SUM(A2:INDEX(A1:A5,B1))','=SUMIFS(A2:INDEX(A1:A5,4),A2:A4,">0")','=COUNTIF(A2:INDEX(A1:A5,4),">0")','=SUM(A2:INDEX(A1:A5,6))','=SUM(A2:INDEX(A1:A5,"x"))','=INDEX(D1:INDEX(D1:D9,9),2)','=SUM(D7:INDEX(D1:D9,7))','=SUM(INDEX(A1:A5,2):A4)']
    w=model(tmp_path,formulas)
    for row,expected in enumerate([9,9,3,REF_ERR,VALUE_ERR,9],1):assert w.cell_value_now('S',row,4)==expected,(row,w.cell_value_now('S',row,4))
    assert not w.cycle_diagnostics
    w.cell_value_now('S',7,4);assert w.cycle_diagnostics
    w.set_value('S',1,2,3);assert w.cell_value_now('S',1,4)==5
    w.set_value('S',3,1,10);assert w.cell_value_now('S',1,4)==12
    assert w.cell_value_now('S',8,4)==16


def test_cell_index_unsupported_geometry_remains_diagnostic(tmp_path):
    formulas=['=IFERROR(SUM(A2:INDEX(A1:A5,0)),7)','=IFERROR(SUM(A2:INDEX(Other!A1:A5,4)),7)','=IFERROR(SUM(A4:INDEX(A1:A5,2)),7)','=IFERROR(SUM(A2:INDEX(A1:B5,4,1,1)),7)']
    w=model(tmp_path,formulas)
    for row in range(1,5):assert w.cell_value_now('S',row,4)==7
    for label in ['zero-index-endpoint-geometry','mixed-sheet-or-book-endpoints','reversed-endpoint-geometry','dynrange-shape']:
        assert any(label in note for note in w.notes),label
