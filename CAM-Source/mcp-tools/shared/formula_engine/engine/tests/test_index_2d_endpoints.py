"""Bounded rectangular INDEX point endpoints, not zero/area_num geometry."""
import openpyxl,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,REF_ERR,VALUE_ERR,NUM_ERR,DIV0


def model(tmp_path,formulas):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';other=raw.create_sheet('Other')
    for i,p in enumerate([.69,.34,.55,.25,.59],2):s.cell(i,2,p);s.cell(i,1,'fruit');s.cell(i,3,i*10)
    s['E1']=5;s['E2']=2
    for row,f in enumerate(formulas,1):s.cell(row,7,f)
    p=tmp_path/'2d-endpoints.xlsx';raw.save(p);return Workbook(str(p))


def test_microsoft_bounded_reference_endpoint_example_and_edits(tmp_path):
    w=model(tmp_path,['=SUM(B2:INDEX(A2:C6,5,2))','=SUM(B2:INDEX(A2:C6,E1,E2))','=SUM(INDEX(A2:C6,1,2):INDEX(A2:C6,5,2))','=COUNTIF(B2:INDEX(A2:C6,5,2),">0")','=SUMIFS(B2:INDEX(A2:C6,5,2),B2:B6,">0")'])
    for row in [1,2,3,5]:assert abs(w.cell_value_now('S',row,7)-2.42)<1e-12
    assert w.cell_value_now('S',4,7)==5
    w.set_value('S',1,5,3);assert abs(w.cell_value_now('S',2,7)-1.58)<1e-12
    w.set_value('S',3,2,1.34);assert abs(w.cell_value_now('S',2,7)-2.58)<1e-12


def test_bounded_2d_endpoint_selector_errors_limits_and_no_match(tmp_path):
    forms=['=SUM(B2:INDEX(A2:C6,6,2))','=SUM(B2:INDEX(A2:C6,5,4))','=SUM(B2:INDEX(A2:C6,-1,2))','=SUM(B2:INDEX(A2:C6,5,"x"))','=SUM(B2:INDEX(A2:C6,1E309,2))','=SUM(B2:INDEX(A2:C6,5,1/0))','=SUMIFS(B2:INDEX(A2:C6,6,2),B2:B6,99)','=SUM(B2:INDEX(A2:C6,"5",2.9))']
    w=model(tmp_path,forms)
    for row,v in enumerate([REF_ERR,REF_ERR,REF_ERR,VALUE_ERR,NUM_ERR,DIV0,REF_ERR],1):assert w.cell_value_now('S',row,7)==v,(row,w.cell_value_now('S',row,7))
    assert abs(w.cell_value_now('S',8,7)-2.42)<1e-12


def test_bounded_2d_endpoint_unsupported_geometry_and_lazy_selection(tmp_path):
    w=model(tmp_path,['=IFERROR(SUM(B2:INDEX(A2:C6,0,2)),7)','=IFERROR(SUM(B2:INDEX(A:C,5,2)),7)','=IFERROR(SUM(B2:INDEX(Other!A2:C6,5,2)),7)','=INDEX(G1:INDEX(G1:H6,6,1),2)','=SUM(G5:INDEX(G1:H6,5,1))'])
    for row in [1,2,3,4]:assert w.cell_value_now('S',row,7)==7
    assert not w.cycle_diagnostics
    for label in ['zero-index-endpoint-geometry','three-arg-unbounded-index-endpoint','mixed-sheet-or-book-endpoints']:assert any(label in n for n in w.notes),label
    w.cell_value_now('S',5,7);assert w.cycle_diagnostics
