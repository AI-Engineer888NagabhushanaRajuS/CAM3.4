"""SUMIF dynamic references use existing anchor alignment and lazy reads."""
import openpyxl,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook,REF_ERR,VALUE_ERR,NUM_ERR,DIV0


def model(tmp_path,forms):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';raw.create_sheet('Other')
    for row,(c,v) in enumerate([('x',10),('y',20),('x',30)],1):s.cell(row,1,c);s.cell(row,2,v)
    s['E1']=3
    for row,f in enumerate(forms,1):s.cell(row,7,f)
    p=tmp_path/'sumif-dyn.xlsx';raw.save(p);return Workbook(str(p))


def test_sumif_dynamic_criteria_sum_ranges_anchor_alignment_and_edits(tmp_path):
    w=model(tmp_path,['=SUMIF(A1:INDEX(A1:A3,3),"x",B1:B3)','=SUMIF(A1:A3,"x",B1:INDEX(B1:B3,1))','=SUMIF(A1:INDEX(A1:B3,E1,1),"x",B1:INDEX(A1:B3,1,2))','=SUMIF(B1:INDEX(B1:B3,3),">15")'])
    for row,v in enumerate([40,40,40,50],1):assert w.cell_value_now('S',row,7)==v
    w.set_value('S',1,5,2);assert w.cell_value_now('S',3,7)==10
    w.set_value('S',1,2,15);assert w.cell_value_now('S',3,7)==15
    assert w.cell_value_now('S',1,7)==45
    assert not w.notes


def test_sumif_dynamic_selector_errors_even_no_match_and_unsupported_notes(tmp_path):
    bad='B1:INDEX(B1:B3,4)';w=model(tmp_path,[f'=SUMIF(A1:A3,"absent",{bad})','=SUMIF(A1:INDEX(A1:A3,4),"absent",B1:B3)','=SUMIF(A1:A3,"x",B1:INDEX(B1:B3,"x"))','=SUMIF(A1:A3,"x",B1:INDEX(B1:B3,1E309))','=SUMIF(A1:A3,"x",B1:INDEX(B1:B3,1/0))','=IFERROR(SUMIF(A1:INDEX(A1:A3,0),"x",B1:B3),7)','=IFERROR(SUMIF(A1:INDEX(Other!A1:A3,3),"x",B1:B3),7)'])
    for row,v in enumerate([REF_ERR,REF_ERR,VALUE_ERR,NUM_ERR,DIV0,7,7],1):assert w.cell_value_now('S',row,7)==v,(row,w.cell_value_now('S',row,7))
    for label in ['zero-index-endpoint-geometry','mixed-sheet-or-book-endpoints']:assert any(label in n for n in w.notes)


def test_sumif_dynamic_selected_self_exclusion_and_true_cycle(tmp_path):
    w=model(tmp_path,[]);w.set_formula('S',2,2,'=SUMIF(A1:A3,"x",B1:INDEX(B1:B3,3))')
    assert w.cell_value_now('S',2,2)==40
    assert not w.cycle_diagnostics
    w.set_value('S',2,1,'x');w.cell_value_now('S',2,2);assert w.cycle_diagnostics
