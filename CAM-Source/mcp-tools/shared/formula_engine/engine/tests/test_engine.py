import tempfile as _tempfile
TMP = _tempfile.gettempdir()
"""Test suite for the CAM Formula Engine.

Every test is grounded in either (a) an authored SRIM/CAM template from the
corpus, (b) an observed corpus formula pattern, or (c) a client edge case from
the Master edge cases sheet. Test names carry the source.
Run: python3 -m pytest tests/ -q   (from engine/)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import pytest

from excel_formula_engine import Workbook, parse_formula
from excel_formula_engine.evaluator import EvalContext, evaluate
from excel_formula_engine.values import (BLANK, NA, VALUE_ERR, REF_ERR, DIV0,
                                         NAME_ERR, is_error, ErrorValue)


def make_wb(cells, today=datetime.date(2026, 10, 9)):
    """cells: {sheet: {(row,col): value}} ; strings starting '=' become formulas."""
    path = os.path.join(TMP, '_t.xlsx')
    wb = openpyxl.Workbook()
    first = True
    for sheet, data in cells.items():
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = sheet
        for (r, c), v in data.items():
            ws.cell(row=r, column=c, value=v)
    wb.save(path)
    return Workbook(path, today=today)


def V(wb, sheet, r, c):
    return wb.cell_value_now(sheet, r, c)


# ---------- parser ----------

def test_parse_corpus_shapes():
    # Real authored templates (SRIM logic docs), A1 forms
    samples = [
        "=IFERROR(INDEX('7.0 CBOM VL-1'!$F$1:$F$500, MATCH($A9, '7.0 CBOM VL-1'!$C$1:$C$500, 0)),0)",
        "=SUMIFS(INDEX('7.0 CBOM VL-1'!$AW:$AW,$AL$1):INDEX('7.0 CBOM VL-1'!$AW:$AW,$AK$1), INDEX('7.0 CBOM VL-1'!$C:$C,$AL$1):INDEX('7.0 CBOM VL-1'!$C:$C,$AK$1), $A9, INDEX('7.0 CBOM VL-1'!$AH:$AH,$AL$1):INDEX('7.0 CBOM VL-1'!$AH:$AH,$AK$1), \"<>TRUE\")",
        "=IF(INT(F5)=F5, ROUNDUP(J5*(1+IF(K5=\"\",0,K5)),0), J5*(1+IF(K5=\"\",0,K5)))",
        "=IF(V5=0,0,IFERROR(ROUNDUP(MAX(V5,T5)/S5,0)*S5,0))",
        "=MATCH(1, INDEX(('7.0 CBOM VL-1'!$A$1:$A$500=$B$2)*('7.0 CBOM VL-1'!$C$1:$C$500=$A9)*(UPPER(TRIM('7.0 CBOM VL-1'!$AF$1:$AF$500))=\"TRUE\"),0),0)",
        "=SUMPRODUCT(--($AP$10:$AP$100=1)*($C$10:$C$100<>\"\"))",
        "=$B3*IFERROR(NUMBERVALUE(LEFT($A3,FIND(\" \",$A3))),0)",
        "=\" $ \"&TEXT(SUM($I$3:$I$50),\"0.00\")",
        "=IF($AF26, IF($K26<>\"\", INDEX('Scrap Factor'!$C$2:$C$10, MATCH($K26, 'Scrap Factor'!$A$2:$A$10, 1)), \"\"), \"\")",
        "=IF($AF26, IFERROR(LEFT($AE26, FIND(\"@\", SUBSTITUTE($AE26, \".\", \"@\", LEN($AE26)-LEN(SUBSTITUTE($AE26, \".\", \"\"))))-1), $AE26), \"\")",
        "=DATEDIF($A$1,TODAY(),\"d\")",
        "=IFERROR(ABS(INDEX('[1]Ex Inv VL--1'!O$5:O$1029, MATCH('Ex Inv VL-proto'!A5, '[1]Ex Inv VL--1'!$A$5:$A$1029, 0)) - 'Ex Inv VL-proto'!O5),0)",
        "=IF($C26<>\"\", COUNTIF($C$1:$C26, $C26), \"\")",
        "=SUBTOTAL(109,Summary!$E$3:$E$20)",
        "=K10-K12",
        '=IF($AF26,IF($K26="",TRUE,ROUND(SUMIFS($K$10:$K$100,$C$10:$C$100,$C26)/COUNTIFS($C$10:$C$100,$C26),3)=ROUND($K26,3)),"")',
    ]
    for s in samples:
        ast = parse_formula(s)
        assert ast is not None, s


# ---------- core semantics ----------

def test_if_and_blank_guard_scrap_rule():
    # CAM-008/101/189 + the Sep/Oct generator divergence: IF(K="",0,K)
    wb = make_wb({"S": {(1, 1): None, (1, 2): 0.05,
                        (2, 1): '=IF(A1="",0,A1)', (2, 2): '=IF(B1="",0,B1)',
                        (3, 1): 10.0, (3, 2): '=ROUNDUP(C1*(1+A2),0)',
                        (3, 3): '=ROUNDUP(C1*(1+B2),0)'},
                  })
    # renaming: build properly below
    wb = make_wb({"S": {(1, 1): None, (1, 2): 0.05,
                        (2, 1): '=IF(A1="",0,A1)', (2, 2): '=IF(B1="",0,B1)',
                        (4, 1): 10.0,
                        (3, 2): '=ROUNDUP(A4*(1+A2),0)',
                        (3, 3): '=ROUNDUP(A4*(1+B2),0)'}})
    assert V(wb, "S", 2, 1) == 0.0        # blank scrap -> 0
    assert V(wb, "S", 2, 2) == 0.05
    assert V(wb, "S", 3, 2) == 10.0       # 10 * 1.0
    assert V(wb, "S", 3, 3) == 11.0       # roundup(10*1.05)=11


def test_iferror_lookup_fallbacks():
    wb = make_wb({"D": {(1, 1): "P1", (1, 2): 5.0, (2, 1): "P2", (2, 2): 7.5},
                  "S": {(1, 1): '=IFERROR(INDEX(D!$B$1:$B$2, MATCH("P2", D!$A$1:$A$2, 0)),0)',
                        (2, 1): '=IFERROR(INDEX(D!$B$1:$B$2, MATCH("P9", D!$A$1:$A$2, 0)),0)',
                        (3, 1): '=IFERROR(INDEX(D!$B$1:$B$2, MATCH("P9", D!$A$1:$A$2, 0)),"") & ""'}})
    assert V(wb, "S", 1, 1) == 7.5
    assert V(wb, "S", 2, 1) == 0.0
    assert V(wb, "S", 3, 1) == ""


def test_sumifs_with_nottrue_criteria():
    # _sumifs_lookup: SUMIFS(values, C, pn, AH, "<>TRUE") - excludes AH=TRUE rows
    wb = make_wb({"CBOM": {(1, 3): "P1", (1, 8): True, (1, 23): 10.0,
                           (2, 3): "P1", (2, 8): False, (2, 23): 20.0,
                           (3, 3): "P1", (3, 8): "x", (3, 23): 30.0},
                  "S": {(1, 1): "P1",
                        (1, 2): "=SUMIFS(CBOM!$W$1:$W$3, CBOM!$C$1:$C$3, $A1, CBOM!$H$1:$H$3, \"<>TRUE\")"}})
    assert V(wb, "S", 1, 2) == 50.0


def test_two_key_match_with_upper_trim():
    # _fg_price_lookup shape: MATCH(1, INDEX((A=fg)*(C=cpn)*(UPPER(TRIM(AF))="TRUE"),0),0)
    wb = make_wb({"CBOM": {(1, 1): "FG-A", (1, 3): "P1", (1, 6): 100.0, (1, 32): " true "},
                  "S": {(1, 1): "=INDEX(CBOM!$F$1:$F$1, MATCH(1, INDEX((CBOM!$A$1:$A$1=\"FG-A\")*(CBOM!$C$1:$C$1=\"P1\")*(UPPER(TRIM(CBOM!$AF$1:$AF$1))=\"TRUE\"),0),0))"}})
    assert V(wb, "S", 1, 1) == 100.0


def test_sumproduct_double_unary():
    wb = make_wb({"S": {(10, 1): 1, (11, 1): 1, (12, 1): 2,
                        (10, 3): "a", (11, 3): "", (12, 3): "b",
                        (1, 1): "=SUMPRODUCT(--($A$10:$A$12=1))",
                        (2, 1): "=SUMPRODUCT(($A$10:$A$12=1)*($C$10:$C$12<>\"\"))"}})
    assert V(wb, "S", 1, 1) == 2.0
    assert V(wb, "S", 2, 1) == 1.0


def test_roundup_ordering_qty_business_rule():
    # Ordering qty (ex_inv_vl L167): IF(V=0,0,IFERROR(ROUNDUP(MAX(V,T)/S,0)*S,0))
    wb = make_wb({"S": {(1, 22): 250.0, (1, 20): 100.0, (1, 19): 50.0,  # V,T,S
                        (2, 1): '=IF(V1=0,0,IFERROR(ROUNDUP(MAX(V1,T1)/S1,0)*S1,0))',
                        (1, 24): '=IF(AND(T1<>"",T1>0), MAX(N1-H1,0), 0)'}})
    assert V(wb, "S", 2, 1) == 250.0  # roundup(250/50)*50
    wb2 = make_wb({"S": {(1, 22): 0.0, (1, 20): 100.0, (1, 19): 50.0,
                         (2, 1): '=IF(V1=0,0,IFERROR(ROUNDUP(MAX(V1,T1)/S1,0)*S1,0))'}})
    assert V(wb2, "S", 2, 1) == 0.0


def test_currency_conversion_chain():
    # cbom_vl L714: L / INDEX(K,MATCH(M,J,0)) * INDEX(K,MATCH($N$1,J,0))
    wb = make_wb({"CBOM": {(1, 10): "USD", (1, 11): 1.0,
                           (2, 10): "EUR", (2, 11): 1.1,
                           (3, 10): "INR", (3, 11): 83.0,
                           (1, 14): "INR",  # N1 target currency
                           (26, 32): True, (26, 12): 100.0, (26, 13): "EUR",
                           (26, 11): '=IF($AF26, IFERROR(IF(OR($M26="", $L26=""), "", $L26/INDEX($K$1:$K$4,MATCH($M26,$J$1:$J$4,0))*INDEX($K$1:$K$4,MATCH($N$1,$J$1:$J$4,0))), ""), "")'}})
    # 100 EUR -> base(1.1) -> INR(83): 100/1.1*83
    assert abs(V(wb, "CBOM", 26, 11) - (100.0 / 1.1 * 83.0)) < 1e-9


def test_excel_round_half_away_from_zero():
    wb = make_wb({"S": {(1, 1): "=ROUND(29608.49, 1)", (1, 2): "=ROUND(2.5,0)",
                        (1, 3): "=ROUND(-2.5,0)", (1, 4): "=ROUNDUP(10.01,0)",
                        (1, 5): "=INT(5.9)", (1, 6): "=INT(-5.9)"}})
    assert V(wb, "S", 1, 1) == 29608.5
    assert V(wb, "S", 1, 2) == 3.0
    assert V(wb, "S", 1, 3) == -3.0
    assert V(wb, "S", 1, 4) == 11.0
    assert V(wb, "S", 1, 5) == 5.0
    assert V(wb, "S", 1, 6) == -6.0


def test_summary_arithmetic_precision():
    # Duplicates tab: 4.9347 x 6000 = 29608.2 exactly (not 29608.490 typo)
    wb = make_wb({"S": {(1, 1): 4.9347, (1, 2): 6000, (1, 3): "=A1*B1"}})
    assert abs(V(wb, "S", 1, 3) - 29608.2) < 1e-6


def test_text_numbervalue_left_find():
    # batchwise_cashflow: =$B3*IFERROR(NUMBERVALUE(LEFT($A3,FIND(" ",$A3))),0)
    wb = make_wb({"S": {(3, 1): "5 Years", (3, 2): 12.0,
                        (4, 1): "=$B3*IFERROR(NUMBERVALUE(LEFT($A3,FIND(\" \",$A3))),0)"}})
    assert V(wb, "S", 4, 1) == 60.0


def test_substitute_domain_strip():
    # cbom_vl L851: strip email domain via SUBSTITUTE/FIND/LEN
    wb = make_wb({"S": {(1, 5): "menakam@centum.com",
                        (2, 1): '=IFERROR(LEFT($E1, FIND("@", SUBSTITUTE($E1, ".", "@", LEN($E1)-LEN(SUBSTITUTE($E1, ".", ""))))-1), $E1)'}})
    assert V(wb, "S", 2, 1) == "menakam"


def test_is_price_same_round3():
    # cbom_vl L879: ROUND(SUMIFS/COUNTIFS,3)=ROUND(K,3)
    wb = make_wb({"S": {(10, 3): "P1", (10, 11): 0.12345,
                        (11, 3): "P1", (11, 11): 0.12344,
                        (26, 32): True, (26, 11): 0.12345, (26, 3): "P1",
                        (26, 40): '=IF($AF26,IF($K26="",TRUE,ROUND(SUMIFS($K$10:$K$11,$C$10:$C$11,$C26)/COUNTIFS($C$10:$C$11,$C26),3)=ROUND($K26,3)),"")'}})
    assert V(wb, "S", 26, 40) is True


def test_text_function_formats():
    wb = make_wb({"S": {(1, 1): 1234.5678,
                        (2, 1): '=TEXT(A1,"0.00")',
                        (3, 1): '=" $ "&TEXT(A1,"0.00")',
                        (4, 1): '=TEXT(A1,"$#,##0.0000")'}})
    assert V(wb, "S", 2, 1) == "1234.57"
    assert V(wb, "S", 3, 1) == " $ 1234.57"
    assert V(wb, "S", 4, 1) == "$1,234.5678"


def test_error_values_propagate_and_caught():
    wb = make_wb({"S": {(1, 1): "=NA()", (1, 2): "=A1+1", (1, 3): "=IFERROR(A1+1,-1)",
                        (1, 4): "=ISERROR(B1)", (1, 5): "=ISNA(A1)", (1, 6): "=1/0"}})
    assert V(wb, "S", 1, 1) == NA
    assert V(wb, "S", 1, 2) == NA
    assert V(wb, "S", 1, 3) == -1.0
    assert V(wb, "S", 1, 4) is True
    assert V(wb, "S", 1, 5) is True
    assert V(wb, "S", 1, 6) == DIV0


def test_datedif_and_today():
    wb = make_wb({"S": {(1, 1): "=DATE(2026,10,9)",
                        (1, 2): '=DATEDIF(DATE(2026,9,9),TODAY(),"d")',
                        (1, 3): '=DATEDIF(DATE(2026,9,9),TODAY(),"m")'}},
                 today=datetime.date(2026, 10, 9))
    assert V(wb, "S", 1, 2) == 30.0   # validity minimum-30-days rule (CAM-037)
    assert V(wb, "S", 1, 3) == 1.0


def test_vlookup_approximate_scrap_factor():
    # Scrap Factor lookup: MATCH(K, A2:A10, 1) tiered
    wb = make_wb({"Scrap Factor": {(2, 1): 0.0, (2, 3): 0.05,
                                   (3, 1): 100.0, (3, 3): 0.03,
                                   (4, 1): 1000.0, (4, 3): 0.01},
                  "S": {(26, 32): True, (26, 11): 150.0,
                        (26, 1): '=IF($AF26, IF($K26<>"", INDEX(\'Scrap Factor\'!$C$2:$C$4, MATCH($K26, \'Scrap Factor\'!$A$2:$A$4, 1)), ""), "")'}})
    assert V(wb, "S", 26, 1) == 0.03


# ---------- recalculation / propagation (the #1 client pain) ----------

def test_edit_propagates_to_dependents():
    # CAM-185/186/208: packing qty edit must update every dependent cell
    wb = make_wb({"S": {(1, 1): 10.0,
                        (2, 1): "=A1*2",
                        (3, 1): "=A2+5",
                        (1, 2): "='T'!A1*2"},
                  "T": {(1, 1): "=S!A3"}})
    assert V(wb, "S", 3, 1) == 25.0
    assert V(wb, "T", 1, 1) == 25.0
    assert V(wb, "S", 1, 2) == 50.0
    wb.set_value("S", 1, 1, 20.0)
    assert V(wb, "S", 2, 1) == 40.0
    assert V(wb, "S", 3, 1) == 45.0
    assert V(wb, "T", 1, 1) == 45.0
    assert V(wb, "S", 1, 2) == 90.0


def test_edit_through_lookup_chain():
    wb = make_wb({"D": {(1, 1): "P1", (1, 2): 5.0},
                  "S": {(1, 1): '=IFERROR(INDEX(D!$B$1:$B$1, MATCH("P1", D!$A$1:$A$1, 0)),0)',
                        (1, 2): "=A1*3"}})
    assert V(wb, "S", 1, 2) == 15.0
    wb.set_value("D", 1, 2, 9.0)
    assert V(wb, "S", 1, 1) == 9.0
    assert V(wb, "S", 1, 2) == 27.0


def test_circular_ref_flagged_not_hung():
    wb = make_wb({"S": {(1, 1): "=A2", (2, 1): "=A1"}})
    v = V(wb, "S", 1, 1)
    assert is_error(v) and v.code == "#CIRC!"


def test_unknown_function_is_name_error_counted():
    wb = make_wb({"S": {(1, 1): "=NOTAREALFUNC(1)"}})
    assert V(wb, "S", 1, 1) == NAME_ERR
    assert wb.stats["name_errors"] >= 1


# ---- structured table references (corpus: CBOM_VN_SUM[Assembly],
# Ex_Inv_VN[[#This Row],[Part Number]], Currency_VN[Value]) ----

def make_table_wb():
    path = os.path.join(TMP, '_t_tbl.xlsx')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A1"], ws["B1"], ws["C1"] = "Part Number", "Cost #N", "MOQ"
    for i in range(2, 6):
        ws.cell(row=i, column=1, value=f"P{i}")
        ws.cell(row=i, column=2, value=i * 10.0)
        ws.cell(row=i, column=3, value=i)
    from openpyxl.worksheet.table import Table, TableStyleInfo
    t = Table(displayName="Ex_Inv_VN", ref="A1:C5")
    wb["Data"].add_table(t)
    ws2 = wb.create_sheet("Calc")
    ws2["A1"] = "=SUM(Ex_Inv_VN[Cost #N])"
    ws2["A2"] = "=SUMPRODUCT(--(Ex_Inv_VN[Part Number]=\"P3\"),Ex_Inv_VN[MOQ])"
    ws2["A3"] = "=COUNTA(Ex_Inv_VN[Part Number])"
    ws2["A4"] = "=SUM(Ex_Inv_VN[[#This Row],[MOQ]])"  # row 4 in table rows -> 4.0
    ws2["A9"] = "=SUM(Ex_Inv_VN[[#This Row],[MOQ]])"  # row 9 off table -> #VALUE!
    ws2["A5"] = "=SUM(NoSuchTable[X])"
    ws2["A6"] = "=SUM(Ex_Inv_VN[No Such Col])"
    wb.save(path)
    return Workbook(path, today=datetime.date(2026, 10, 9))


def test_structured_ref_column_sum():
    wb = make_table_wb()
    assert V(wb, "Calc", 1, 1) == 20 + 30 + 40 + 50  # rows 2..5 -> 140


def test_structured_ref_in_sumproduct_lookup_pattern():
    wb = make_table_wb()
    assert V(wb, "Calc", 2, 1) == 3.0


def test_structured_ref_counta_excludes_header():
    wb = make_table_wb()
    assert V(wb, "Calc", 3, 1) == 4.0


def test_structured_ref_this_row_uses_formula_row_number():
    wb = make_table_wb()
    assert V(wb, "Calc", 4, 1) == 4.0
    assert V(wb, "Calc", 9, 1) == VALUE_ERR


def test_structured_ref_unknown_table_name_err():
    wb = make_table_wb()
    assert V(wb, "Calc", 5, 1) == NAME_ERR


def test_structured_ref_unknown_col_ref_err():
    wb = make_table_wb()
    assert V(wb, "Calc", 6, 1) == REF_ERR


def test_parse_escaped_quote_col():
    ast = parse_formula("=SUM(CBOM_VN_SUM[Ext Vol Qty '#N])")
    assert ast is not None


def test_explicit_empty_arg_is_distinct_from_absent():
    # corpus: VLOOKUP(Ex_Inv_V1[[#This Row],[Mfg Part Number]],'Scrub BOM'!$E$1:$I$556,5,)
    wb = make_wb({"S": {(1, 1): 1.0, (1, 2): "a", (2, 1): 3.0, (2, 2): "b",
                        (3, 1): "=VLOOKUP(2,A1:B2,2,)", (4, 1): "=VLOOKUP(2,A1:B2,2)",
                        (5, 1): "=IF(1=1,5,)"}})
    # LibreOffice differential fixture: explicit empty is FALSE; absent is TRUE.
    assert V(wb, "S", 3, 1) == NA
    assert V(wb, "S", 4, 1) == "a"
    assert V(wb, "S", 5, 1) == 5.0


def test_empty_false_if_and_index_empty_cell_oracle():
    wb = make_wb({'S': {(1,1): 1, (2,1): '=IF(FALSE,5,)', (3,1): '=IF(FALSE,5)',
                       (4,1): '=SUM(1,,2)', (5,1): '=INDEX(B1:B2,2,1)'}})
    assert V(wb,'S',2,1) == 0.0
    assert V(wb,'S',3,1) is False
    assert V(wb,'S',4,1) == 3.0
    assert V(wb,'S',5,1) == 0.0


def test_text_range_preserves_array_values():
    wb = make_wb({'S': {(1,1): 'P1', (2,1): 'P2', (1,2): '=SUMPRODUCT(--(TEXT(A1:A2,0)="P2"))'}})
    assert V(wb,'S',1,2) == 1.0


def test_quoted_external_ref_is_not_local_sheet():
    from excel_formula_engine.parser import CellRef
    n = parse_formula("='[1]Book Sheet'!A1")
    assert isinstance(n, CellRef)
    assert n.ext == '1' and n.sheet == 'Book Sheet'


def test_whole_column_edit_beyond_used_rows_invalidates():
    wb = make_wb({'S': {(1,1): 4, (1,2): '=SUM(A:A)'}})
    assert V(wb,'S',1,2) == 4
    wb.set_value('S',100,1,9)
    assert V(wb,'S',1,2) == 13


def test_branch_edit_dependency_and_transitive_propagation():
    wb = make_wb({'S': {(1,1): True, (1,2): 2, (1,3): 3, (1,4): '=IF(A1,B1,C1)', (1,5): '=D1*2'}})
    assert V(wb,'S',1,5) == 4
    wb.set_value('S',1,1,False)
    assert V(wb,'S',1,5) == 6
    wb.set_value('S',1,3,10)
    assert V(wb,'S',1,5) == 20


def test_xlfn_prefix_for_registered_function_only():
    wb=make_wb({'S': {(1,1): '=_xlfn.SUMIFS(B1:B2,B1:B2,">0")', (1,2): 2, (2,2): 3}})
    assert V(wb,'S',1,1) == 5


def test_deep_acyclic_chain_uses_iterative_scheduler():
    cells={(1,1): 1}
    for r in range(2,1601):cells[(r,1)]=f'=A{r-1}+1'
    wb=make_wb({'S':cells})
    assert V(wb,'S',1600,1) == 1600
    assert wb.stats['max_dependency_depth'] == 1599
    assert wb.cycle_diagnostics == []
    wb.set_value('S',1,1,2)
    assert V(wb,'S',1600,1) == 1601


def test_runtime_cycle_reports_actual_path_and_can_be_broken():
    wb=make_wb({'S': {(1,1): '=B1+1', (1,2): '=A1+1'}})
    assert str(V(wb,'S',1,1)) == '#CIRC!'
    assert wb.cycle_diagnostics[-1] == [('s',1,1),('s',1,2),('s',1,1)]
    wb.set_value('S',1,2,3)
    assert V(wb,'S',1,1) == 4


def test_untaken_branch_cycle_does_not_create_false_cycle():
    wb=make_wb({'S': {(1,1): '=IF(TRUE,7,A1)'}})
    assert V(wb,'S',1,1) == 7
    assert wb.cycle_diagnostics == []


def test_sumifs_does_not_evaluate_excluded_self_reference():
    # LibreOffice differential fixture oracles/cycle_filters_results.json.
    wb=make_wb({'S': {(1,1): '=SUMIFS(A1:A2,B1:B2,"keep")', (1,2): 'skip', (2,1): 5, (2,2): 'keep'}})
    assert V(wb,'S',1,1) == 5
    assert wb.cycle_diagnostics == []
    wb.set_value('S',2,1,8)
    assert V(wb,'S',1,1) == 8
    wb.set_value('S',1,2,'keep')
    assert str(V(wb,'S',1,1)) == '#CIRC!'
    assert wb.cycle_diagnostics[-1] == [('s',1,1),('s',1,1)]


def test_index_reads_only_selected_reference_not_excluded_self():
    wb=make_wb({'S': {(1,1): '=INDEX(A1:A2,2)', (2,1): 7}})
    assert V(wb,'S',1,1) == 7
    assert wb.cycle_diagnostics == []
    wb.set_value('S',2,1,9)
    assert V(wb,'S',1,1) == 9


def test_subtotal_saved_hidden_rows_and_nested_subtotal():
    p=os.path.join(TMP, '_subtotal_fixture.xlsx')
    raw=openpyxl.Workbook();s=raw.active;s.title='S'
    for cell,v in {'A1':2,'A2':3,'A3':'=SUBTOTAL(9,A1:A2)','C1':'=SUBTOTAL(9,A1:A3)','C2':'=SUBTOTAL(109,A1:A3)'}.items():s[cell]=v
    s.row_dimensions[2].hidden=True;raw.save(p)
    wb=Workbook(p)
    assert V(wb,'S',1,3) == 5
    assert V(wb,'S',2,3) == 2
    wb.set_value('S',1,1,4)
    assert V(wb,'S',2,3) == 4


def test_match_skips_physically_empty_lookup_cells():
    wb=make_wb({'S': {(1,1): 'part', (3,1): 0,
                     (1,3): '=MATCH(B1,A1:A2,0)', (2,3): '=MATCH(0,A1:A2,0)',
                     (3,3): '=MATCH(0,A1:A3,0)'}})
    assert V(wb,'S',1,3) == NA
    assert V(wb,'S',2,3) == NA
    assert V(wb,'S',3,3) == 3


def test_n_scalar_array_and_error_oracle():
    wb=make_wb({'S': {(1,1): 4,(2,1):True,(3,1):'text',
      (1,3):'=SUMPRODUCT(N(A1:A3))',(2,3):'=N("4")',(3,3):'=N(A4)',(4,3):'=N(NA())'}})
    assert V(wb,'S',1,3) == 5
    assert V(wb,'S',2,3) == 0
    assert V(wb,'S',3,3) == 0
    assert V(wb,'S',4,3) == NA


def test_multicell_lower_trim_array_not_implicit_intersection():
    wb=make_wb({'S': {(1,1):' TRUE ',(2,1):'false',(3,1):'x',
      (1,3):'=SUMPRODUCT(--((LOWER(TRIM(A1:A3))="true")+(LOWER(TRIM(A1:A3))="false")))'}})
    assert V(wb,'S',1,3) == 2


def test_literal_generator_snapshot_is_not_assumed_live_formula():
    from excel_formula_engine.provenance import describe_cell,arithmetic_product_diagnostic
    wb=make_wb({'S': {(1,1):4.9347,(1,2):6000,(1,3):198810.5,(1,4):'=C1'}})
    before=V(wb,'S',1,4)
    origin=describe_cell(wb,'S',1,3,'generator-derived-snapshot','synthetic payload.extended')
    assert origin.storage == 'literal' and origin.formula is None
    assert origin.origin_role == 'generator-derived-snapshot'
    diagnostic=arithmetic_product_diagnostic(4.9347,6000,before)
    assert diagnostic['status'] == 'inconsistent' and diagnostic['mutation']=='none'
    wb.set_value('S',1,2,1)
    assert V(wb,'S',1,4) == before  # static dependency gap is not evaluator propagation


def test_two_path_origin_dirty_contract_and_no_policy_inference():
    from excel_formula_engine.provenance import OriginGraph,OriginNode
    g=OriginGraph()
    for key,kind in [('qty','input'),('N','formula'),('J','generator-snapshot'),('O','formula'),('G','generator-snapshot'),('Summary','formula')]:
        g.add_node(OriginNode(key,kind,'synthetic lineage fixture'))
    for a,b in [('qty','N'),('qty','J'),('J','O'),('O','G'),('G','Summary')]:g.add_dependency(a,b)
    report=g.impact(['qty'])
    assert report['model_rebuild_required']==['G','J']
    assert report['blocked_model_nodes']==['G','J']
    assert report['formula_recalc_candidates']==['N','O','Summary']
    assert report['declared_model_path_ready'] is False and report['mutation']=='none'
    with pytest.raises(ValueError,match='cycle'):g.add_dependency('Summary','qty')
    with pytest.raises(KeyError):g.impact(['unknown'])
    with pytest.raises(ValueError,match='Evidence'):g.add_node(OriginNode('bad','input',''))


def test_approved_recipe_identifier_still_requires_actual_rebuild():
    from excel_formula_engine.provenance import OriginGraph,OriginNode
    g=OriginGraph();g.add_node(OriginNode('in','input','synthetic'))
    g.add_node(OriginNode('out','generator-snapshot','synthetic','known-recipe',True))
    g.add_dependency('in','out');r=g.impact(['in'])
    assert not r['blocked_model_nodes'] and r['model_rebuild_required']==['out']
    assert r['declared_model_path_ready'] is False  # recipe existence is not successful execution


def test_getpivotdata_metadata_snapshot_independent_oracle_fixture():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    for stem in ['pivot_grandtotal','pivot_filtered_grandtotal']:
        wb=Workbook(str(root/'oracles/in'/f'{stem}.xlsx'))
        expected=json.load(open(root/'oracles'/f'{stem}_results.json'))['results']
        for r in range(1,5):
            assert str(V(wb,'Queries',r,2))==str(float(expected[r-1]['value']) if isinstance(expected[r-1]['value'],(int,float)) else expected[r-1]['value'])
        assert V(wb,'Queries',5,2)==NAME_ERR  # item pairs remain explicitly unsupported
        before=V(wb,'Queries',1,2)
        wb.set_value('Source',2,2,100)
        assert wb.pivot_snapshots[0]['source_dirty'] is True
        assert V(wb,'Queries',1,2)==before  # GETPIVOTDATA does not refresh a saved pivot
        target=wb.pivot_snapshots[0]['fields']['sales']
        wb.set_value('Pivot',*target,125)
        assert V(wb,'Queries',1,2)==125  # actual pivot display cell is a tracked dependency


def test_source_identity_collisions_detected_without_dedup_or_repair():
    from excel_formula_engine.model_validation import identity_collisions
    rows=[{'fg':'FG','assembly':'A','cpn':'P','mpn':'M','id':1,'q':2},
          {'fg':'FG','assembly':'A','cpn':'P','mpn':'M','id':2,'q':3}]
    original=[dict(x) for x in rows]
    r=identity_collisions(rows,['fg','assembly','cpn','mpn'],['id'],'q')
    assert r['collisions'][0]['risk']=='distinct-occurrences-share-dedup-key'
    assert r['collisions'][0]['distinct_quantity_count']==2
    assert r['mutation']=='none' and rows==original
    rows[1]['id']=1
    assert identity_collisions(rows,['cpn'],['id'],'q')['collisions'][0]['risk']=='same-identity-conflicting-quantity'
    rows[1].pop('id')
    assert identity_collisions(rows,['cpn'],['id'],'q')['missing_identity']==[{'row_index':1,'missing_fields':['id']}]
    with pytest.raises(ValueError):identity_collisions(rows,['cpn'],[],'q')


def test_bounded_range_growth_invalidates_original_rectangle_not_used_extent():
    wb=make_wb({'S':{(1,1):2,(1,2):'=SUM(A1:A100)',(2,2):'=SUM(C1:Z1)'}})
    assert V(wb,'S',1,2)==2
    assert V(wb,'S',2,2)==0
    wb.set_value('S',50,1,3)
    assert V(wb,'S',1,2)==5
    wb.set_value('S',1,20,7)
    assert V(wb,'S',2,2)==7
    assert ('s',1,1,100,1) in wb.deps['s',1,2]


def test_countblank_reference_extent_and_growth_not_just_occupied_cells():
    wb=make_wb({'S':{(1,1):2,(2,1):'=""',(1,2):'=COUNTBLANK(A1:A100)',(2,2):'=COUNTBLANK(A:A)'}})
    assert V(wb,'S',1,2)==99
    assert V(wb,'S',2,2)==1048575
    wb.set_value('S',50,1,3)
    assert V(wb,'S',1,2)==98
    assert V(wb,'S',2,2)==1048574


def test_countif_and_countifs_unused_blank_tail_and_range_shape():
    wb=make_wb({'S':{(1,1):2,(1,2):'=COUNTIF(A1:A100,"")',
        (2,2):'=COUNTIF(A:A,0)',(3,2):'=COUNTIFS(A1:A100,"",C1:C100,"")',
        (4,2):'=COUNTIFS(A1:A100,"",C1:C99,"")'}})
    assert V(wb,'S',1,2)==99
    assert V(wb,'S',2,2)==NAME_ERR  # numeric-zero/blank-tail coercion remains unverified
    assert V(wb,'S',3,2)==99
    assert V(wb,'S',4,2)==VALUE_ERR
    wb.set_value('S',50,1,3)
    assert V(wb,'S',1,2)==98
    assert V(wb,'S',3,2)==98


def test_crosssheet_blank_criteria_uses_occupied_union_and_sum_growth():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/crosssheet_blank_criteria.xlsx'))
    assert V(wb,'Queries',1,1)==8
    assert V(wb,'Queries',2,1)==8
    assert V(wb,'Queries',3,1)==VALUE_ERR
    wb.set_value('Values',90,1,12)
    assert V(wb,'Queries',1,1)==20
    assert V(wb,'Queries',2,1)==10
    wb.set_value('Criteria',50,1,'exclude')
    assert V(wb,'Queries',1,1)==12
    assert V(wb,'Queries',2,1)==12


def test_workday_modern_numeric_serial_scope_secondary_oracle():
    from pathlib import Path
    import json
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/workday_modern_serial.xlsx'))
    oracle=json.load(open(root/'oracles/workday_modern_serial_results.json'))['results']
    for r in [1,2,3,4,5,6,7,9]:
        got=V(wb,'Dates',r,3);expected=oracle[f'C{r}']
        assert (str(got) if isinstance(expected,str) else got)==expected
    assert V(wb,'Dates',8,3)==NAME_ERR  # early1900notcertified, noapproximation
    wb.date_system_1904=True;wb.cache.clear()
    assert V(wb,'Dates',1,3)==NAME_ERR


def test_sumif_selected_reads_and_top_left_shape_alignment():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/sumif_selected_reference.xlsx'))
    assert V(wb,'Sheet',1,1)==7
    assert V(wb,'Sheet',1,4)==7  # single-cell sum_range expands to criteria shape
    assert not wb.cycle_diagnostics
    wb.set_value('Sheet',2,1,9)
    assert V(wb,'Sheet',1,1)==9
    assert V(wb,'Sheet',1,4)==9


def test_escaped_wildcards_countif_match_and_search_secondary_oracle():
    from pathlib import Path
    import json
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/escaped_wildcards.xlsx'))
    oracle=json.load(open(root/'oracles/escaped_wildcards_results.json'))['results']
    for r in range(1,10):assert V(wb,'Sheet',r,3)==oracle[f'C{r}']
    wb=make_wb({'S':{(1,1):'=SEARCH("n","printer")',
                    (2,1):'=SEARCH("Y","AYF0093.YoungMensApparel",8)',
                    (3,1):'=SEARCH("x","abc",0)'}})
    assert V(wb,'S',1,1)==4
    assert V(wb,'S',2,1)==9
    assert V(wb,'S',3,1)==VALUE_ERR


def test_source_typed_nonstandard_error_is_not_plain_text_or_cache_fallback():
    from excel_formula_engine.workbook import _py_to_excel
    assert _py_to_excel('#ERROR!','e')==ErrorValue('#ERROR!')
    assert _py_to_excel('#SPILL!','e')==ErrorValue('#SPILL!')
    assert _py_to_excel('#ERROR!','s')=='#ERROR!'  # literal text stays text
    # Source errors are propagated as inputs, never substituted for formula execution.
    wb=make_wb({'S':{(1,1):1,(1,2):'=A1+1'}})
    wb.set_value('S',1,1,ErrorValue('#ERROR!'))
    assert V(wb,'S',1,2)==ErrorValue('#ERROR!')


def test_countif_unknown_reference_geometry_is_not_occupied_only_blank_count():
    wb=make_wb({'S':{(1,1):'x',(1,2):'=COUNTIF(IF(TRUE,A1:A100,A1:A100),"")',
                    (2,2):'=COUNTIFS(IF(TRUE,A1:A100,A1:A100),"")'}})
    assert V(wb,'S',1,2)==NAME_ERR
    assert V(wb,'S',2,2)==NAME_ERR
    assert any('countifs:unknown-reference-geometry' in note for note in wb.notes)


def test_xlookup_exact_literal_and_selected_return_no_false_cycle():
    # Microsoft XLOOKUP syntax: default match_mode=0 is literal exact;
    # wildcards require match_mode=2. Selected return excludes C2 self-reference.
    wb=make_wb({'S':{(1,1):'a*',(2,1):'alpha',(3,1):'a*',
        (1,3):7,(2,3):'=XLOOKUP("a*",A1:A3,C1:C3)',(3,3):9,
        (1,5):'=XLOOKUP("missing",A1:A3,C1:C3,"absent")',
        (2,5):'=XLOOKUP("missing",A1:A3,C1:C3)',
        (3,5):'=XLOOKUP("a*",A1:A3,C1:C3,,0,1)',
        (1,6):'a',(1,7):'b',(2,6):4,(2,7):8,
        (4,5):'=XLOOKUP("b",F1:G1,F2:G2)'}})
    assert V(wb,'S',2,3)==7
    assert V(wb,'S',1,5)=='absent'
    assert V(wb,'S',2,5)==NA
    assert V(wb,'S',3,5)==7
    assert V(wb,'S',4,5)==8
    assert not wb.cycle_diagnostics
    wb.set_value('S',1,3,11)
    assert V(wb,'S',2,3)==11


def test_xlookup_unverified_modes_geometry_blanks_fail_explicitly():
    wb=make_wb({'S':{(1,1):'a',(2,1):'b',(1,3):2,(2,3):3,
       (1,5):'=XLOOKUP("a",A1:A2,C1:C2,,2)',
       (2,5):'=XLOOKUP("a",A1:A2,C1:C2,,, -1)',
       (3,5):'=XLOOKUP("a",A1:A2,C1:C1)',
       (4,5):'=XLOOKUP("a",A1:A100,C1:C100)',
       (5,5):'=XLOOKUP("a",IF(TRUE,A1:A2,A1:A2),C1:C2)',
       (6,5):'=XLOOKUP("a",A1:A2,C1:C2,,1)',
       (7,5):'=XLOOKUP("a",A1:A2,C1:C2,,,2)'}})
    assert V(wb,'S',3,5)==VALUE_ERR
    for r in (1,2,4,5,6,7):assert V(wb,'S',r,5)==NAME_ERR
    assert any('xlookup:match-mode' in n for n in wb.notes)
    assert any('xlookup:search-mode' in n for n in wb.notes)


def test_modern_numeric_date_semantics_secondary_oracle_and_official_exceptions():
    from pathlib import Path
    import json
    from excel_formula_engine.values import NUM_ERR
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/date_modern_numeric.xlsx'))
    expected=json.load(open(root/'oracles/date_modern_numeric_results.json'))['results']
    for r in [1,2,3,4,5,6,8,10,11,12,13,14,18,19,20,21]:
        got=V(wb,'Dates',r,1);oracle=expected[f'A{r}']
        assert (str(got) if isinstance(oracle,str) else got)==oracle
    # Microsoft documentation takes precedence over divergent LO behavior.
    assert V(wb,'Dates',9,1)==NUM_ERR  # start>end
    assert V(wb,'Dates',15,1)==39449  # DATE(108,1,2) -> Jan2,2008
    assert V(wb,'Dates',16,1)==NUM_ERR
    assert V(wb,'Dates',17,1)==NUM_ERR
    assert V(wb,'Dates',22,1)==NUM_ERR
    assert V(wb,'Dates',23,1)==NUM_ERR
    for r in [7,24,25,26,27,28]:assert V(wb,'Dates',r,1)==NAME_ERR
    wb.date_system_1904=True;wb.cache.clear()
    for r in [1,11,19,20,21]:assert V(wb,'Dates',r,1)==NAME_ERR


def test_date_extremes_text_inputs_1904_today_and_now_do_not_silently_guess():
    from excel_formula_engine.values import NUM_ERR
    wb=make_wb({'S':{(1,1):'=DATE(-999999999,1,1)',
        (2,1):'=DATE(2008,1,999999999999)',(3,1):'=YEAR(999999999999)',
        (4,1):'=DATEDIF("2026/1/1",45000,"D")',(5,1):'=NOW()',
        (6,1):'=TODAY()'}})
    for r in [1,2,3]:assert V(wb,'S',r,1)==NUM_ERR
    for r in [4,5]:assert V(wb,'S',r,1)==NAME_ERR
    wb.date_system_1904=True;wb.cache.clear()
    assert V(wb,'S',6,1)==NAME_ERR


def test_clear_cell_with_none_normalizes_to_blank_and_invalidates():
    wb=make_wb({'S':{(1,1):'INR',(1,2):'=IF(A1="","missing",A1)'}})
    assert V(wb,'S',1,2)=='INR'
    wb.set_value('S',1,1,None)
    assert V(wb,'S',1,1)==BLANK
    assert V(wb,'S',1,2)=='missing'
    wb.set_value('S',1,1,'USD')
    assert V(wb,'S',1,2)=='USD'


def test_standard_error_like_source_text_preserves_explicit_string_type():
    from excel_formula_engine.workbook import _py_to_excel
    for code in ['#N/A','#VALUE!','#REF!','#DIV/0!','#NAME?','#NUM!','#NULL!']:
        assert _py_to_excel(code,'s')==code
        assert _py_to_excel(code,'str')==code
        assert _py_to_excel(code,'e')==ErrorValue(code)


def test_sumproduct_declared_dimensions_and_array_text_not_silent_broadcast():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/sumproduct_dimensions.xlsx'))
    # Official nonnumeric entries rule includes numeric-looking text/logicals.
    # LibreOffice differs on logical arrays, recorded in oracle evidence.
    for r,value in [(1,46),(2,6),(3,VALUE_ERR),(4,VALUE_ERR),(5,VALUE_ERR),
                    (6,46),(7,VALUE_ERR),(8,1),(9,VALUE_ERR),(10,0)]:
        assert V(wb,'Queries',r,1)==value
    wb.set_value('A',90,1,2);wb.set_value('B',90,1,3)
    assert V(wb,'Queries',6,1)==52


def test_sumproduct_transformed_unmaterialized_blank_tail_is_not_undercounted():
    wb=make_wb({'S':{(1,1):2,(1,2):'=SUMPRODUCT(--(A1:A100=""))',
        (2,2):'=SUMPRODUCT(--(A:A=""))',
        (3,2):'=SUMPRODUCT(A1:A100)',
        (4,2):'=SUMPRODUCT(IF(TRUE,A1:A100,A1:A100))'}})
    for r in [1,2,4]:assert V(wb,'S',r,2)==NAME_ERR
    assert V(wb,'S',3,2)==2
    assert any('sumproduct:computed-blank-tail' in n for n in wb.notes)


def test_numbervalue_official_explicit_separator_space_and_percent_rules():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/numbervalue_explicit_separators.xlsx'))
    values={1:2500.27,2:0.035,3:0.0009,4:0,5:3000,6:VALUE_ERR,
            7:VALUE_ERR,8:12.3,9:1234.56,10:1000,11:VALUE_ERR,
            12:VALUE_ERR,13:VALUE_ERR,14:VALUE_ERR,15:-2.5,16:NAME_ERR,17:2.5}
    for r,value in values.items():
        got=V(wb,'Values',r,1)
        assert got==value or (isinstance(value,float) and abs(got-value)<1e-12)


def test_numbervalue_omitted_separators_use_explicit_caller_configuration():
    import pytest
    wb=make_wb({'S':{(1,1):'=NUMBERVALUE("2.500,27")'}})
    assert V(wb,'S',1,1)==VALUE_ERR  # default dot decimal, comma group; not source locale inference
    wb=Workbook(os.path.join(TMP, '_t.xlsx'),decimal_separator=',',group_separator='.')
    assert V(wb,'S',1,1)==2500.27
    with pytest.raises(ValueError):Workbook(decimal_separator='xx')
    with pytest.raises(ValueError):Workbook(decimal_separator='.',group_separator='.')


def test_prefixed_wildcard_criteria_equality_inequality_and_empty_tail():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/prefixed_wildcard_criteria.xlsx'))
    for r,count,total in [(1,4,10),(2,1,3),(3,5,35),(4,6,24),
                          (5,3,21),(6,5,35),(7,NAME_ERR,NAME_ERR),(8,0,0),(10,96,35)]:
        assert V(wb,'Values',r,4)==count
        assert V(wb,'Values',r,5)==total
    wb.set_value('Values',50,1,'another')
    assert V(wb,'Values',10,4)==95
    wb.set_value('Values',1,7,'a'*256)
    wb.set_formula('Values',1,6,'=COUNTIF(A1:A9,G1)')
    assert V(wb,'Values',1,6)==NAME_ERR
    assert any('criteria:long-text' in n for n in wb.notes)
    assert any('criteria:relational-wildcard' in n for n in wb.notes)

    wb.set_value('Values',1,1,VALUE_ERR)
    assert V(wb,'Values',1,4)==NAME_ERR
    assert any('criteria:wildcard-error-input' in n for n in wb.notes)


def test_pinned_aclass_export_quantity_rollup_first_cost_and_precision():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/aclass_pinned_source_probe.xlsx'))
    for address,value in [("F3",5),("G3",50),("H3",2),("I3",10),("K3",100)]:
        col=ord(address[0])-64;row=int(address[1:])
        assert V(wb,'A CLASS PARTS',row,col)==value
    # First selected unit cost, not a silently invented weighted average.
    wb.set_value('7.0 CBOM VL-1',4,11,9)
    assert V(wb,'A CLASS PARTS',3,8)==2
    assert V(wb,'A CLASS PARTS',3,9)==10
    wb.set_value('7.0 CBOM VL-1',3,34,True)
    assert V(wb,'A CLASS PARTS',3,6)==3
    assert V(wb,'A CLASS PARTS',3,8)==9
    assert V(wb,'A CLASS PARTS',3,9)==27
    wb.set_value('7.0 CBOM VL-1',4,11,4.934748383725271)
    assert abs(V(wb,'A CLASS PARTS',3,9)-3*4.934748383725271)<1e-12


def test_text_numeric_half_away_percent_zero_padding_and_source_precision():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/text_numeric_format.xlsx'))
    expected=['3','-3','1.13','-1.13','2.68','$1,234.57','28.5%','12.35%',
              '0001234','-0013','0.00','1234.50','1,234.50','0.00','alpha']
    for row,value in enumerate(expected,1):assert V(wb,'Values',row,3)==value
    assert V(wb,'Values',5,1)==2.675  # formatting does not round source
    wb.set_formula('Values',1,5,'=TEXT(A1,"0.00E+00")')
    assert V(wb,'Values',1,5)==NAME_ERR
    assert any('text:format-code' in n for n in wb.notes)
    wb.set_formula('Values',1,5,'=TEXT(-2.5,"$#,##0")')
    assert V(wb,'Values',1,5)=='-$3'
    wb.set_formula('Values',1,5,'=TEXT(1E99,"0.00")')
    assert V(wb,'Values',1,5)==NAME_ERR


def test_exact_table_lookup_selected_reads_no_false_cycle_and_declared_bounds():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    wb=Workbook(str(root/'oracles/in/exact_table_lookup_selected.xlsx'))
    for address,value in [('C1',10),('C2',20),('D1',40),('D2',NA),('D3',REF_ERR),
                          ('D4',VALUE_ERR),('D5',10),('E1',0)]:
        assert V(wb,'Vertical',int(address[1:]),ord(address[0])-64)==value
    for address,value in [('A3',20),('B3',40),('E1',0),('E2',VALUE_ERR)]:
        assert V(wb,'Horizontal',int(address[1:]),ord(address[0])-64)==value
    assert not wb.cycle_diagnostics
    wb.set_value('Vertical',1,2,17)
    assert V(wb,'Vertical',1,3)==17
    assert V(wb,'Vertical',5,4)==17
    wb.set_value('Vertical',1,1,'other')
    assert V(wb,'Vertical',1,3)==30  # next duplicate becomes selected
    wb.set_value('Vertical',1,26,99)
    assert V(wb,'Vertical',1,5)==0  # selected row3, not unrelated row1
    wb.set_value('Vertical',3,26,55)
    assert V(wb,'Vertical',1,5)==55
    wb.set_value('Horizontal',1,1,'other')
    assert V(wb,'Horizontal',3,2)==40


def test_exact_lookup_selected_self_cycle_is_not_suppressed():
    wb=make_wb({'S':{(1,1):'key',(1,2):'=VLOOKUP("key",A1:B2,2,FALSE)',(2,1):'other',(2,2):7}})
    assert is_error(V(wb,'S',1,2))
    assert wb.cycle_diagnostics


def test_exact_lookup_table_reference_and_whole_column_growth():
    from openpyxl.worksheet.table import Table,TableStyleInfo
    import openpyxl
    w=openpyxl.Workbook();s=w.active;s.title='S'
    for r in [('key','value'),('a',10),('b',20)]:s.append(r)
    s.add_table(Table(displayName='Lookups',ref='A1:B3'))
    s['D1']='=VLOOKUP("b",Lookups[#All],2,FALSE)'
    s['D2']='=VLOOKUP("later",A:B,2,FALSE)'
    w.save(os.path.join(TMP, 'lookup_table_test.xlsx'));wb=Workbook(os.path.join(TMP, 'lookup_table_test.xlsx'))
    assert V(wb,'S',1,4)==20
    assert V(wb,'S',2,4)==NA
    wb.set_value('S',90,1,'later');wb.set_value('S',90,2,66)
    assert V(wb,'S',2,4)==66


def test_unique_rejects_missing_spill_contract_instead_of_first_value():
    wb=make_wb({'S':{(1,1):'a',(2,1):'b',(3,1):'a',
        (1,4):'=UNIQUE(A1:A3)',(2,4):'=UNIQUE(A1:A3,FALSE,TRUE)',
        (3,4):'=UNIQUE(A1:B3,TRUE)',(4,4):'=SUM(UNIQUE(A1:A3))'}})
    for row in [1,2,3,4]:assert V(wb,'S',row,4)==NAME_ERR
    assert any('unique:dynamic-array-spill-contract' in n for n in wb.notes)


def test_match_array_lookup_preserves_shape_for_first_occurrence_mask():
    wb=make_wb({'S':{(1,1):'a',(2,1):'b',(3,1):'a',(4,1):'c',
      (1,2):1,(2,2):1,(3,2):1,(4,2):1,
      (1,4):'=SUMPRODUCT(--(MATCH(A1:A4,A1:A4,0)=ROW(A1:A4)))',
      (2,4):'=INDEX(MATCH(A1:A4,A1:A4,0),3)',
      (3,4):'=SUM(MATCH(A1:A4,A1:A4,0))',
      (4,4):'=SUM(MATCH(A1:A4,A1:A4,1))'}})
    assert V(wb,'S',1,4)==3
    assert V(wb,'S',2,4)==1
    assert V(wb,'S',3,4)==8
    assert V(wb,'S',4,4)==NAME_ERR
    wb.set_value('S',3,1,'d')
    assert V(wb,'S',1,4)==4
    assert V(wb,'S',3,4)==10


def test_row_column_array_context_and_scalar_context_separate():
    wb=make_wb({'S':{(1,4):'=SUM(ROW(A3:A5))',(2,4):'=ROW(A3:A5)',
       (3,4):'=SUM(COLUMN(B1:D1))',(4,4):'=COLUMN(B1:D1)',
       (5,4):'=SUM(ROW(A:A))'}})
    assert V(wb,'S',1,4)==12
    assert V(wb,'S',2,4)==3
    assert V(wb,'S',3,4)==9
    assert V(wb,'S',4,4)==2
    assert V(wb,'S',5,4)==NAME_ERR


def test_subtotal_active_filter_rejects_without_guessing_hidden_cause(tmp_path):
    from openpyxl.worksheet.filters import AutoFilter
    from openpyxl.worksheet.table import Table
    p=tmp_path/'filtered.xlsx'
    raw=openpyxl.Workbook();s=raw.active;s.title='S'
    for row in [('Key','Amount'),('A',2),('B',3),('A',5)]:s.append(row)
    s.auto_filter.ref='A1:B4';s.auto_filter.add_filter_column(0,['A*'])
    s.row_dimensions[3].hidden=True
    # The independently hidden matching row must not be silently inferred as filtered.
    s.row_dimensions[4].hidden=True
    for code in [1,2,3,4,5,9,101,102,103,104,105,109]:
        s.cell(code,4,f'=SUBTOTAL({code},B2:B4)')
    s['F1']='=SUBTOTAL(9,B6:B7)';s['B6']=7;s['B7']=8
    tab=Table(displayName='T',ref='A1:B4');s.add_table(tab)
    raw.save(p)
    wb=Workbook(p)
    for code in [1,2,3,4,5,9,101,102,103,104,105,109]:
        assert V(wb,'S',code,4)==VALUE_ERR
    assert any('subtotal-active-filter-unsupported' in str(n) for n in wb.notes)
    assert V(wb,'S',1,6)==15
    wb.set_value('S',3,1,'A')
    assert V(wb,'S',9,4)==VALUE_ERR
    # Table-only active criteria are captured independently from worksheet criteria.
    s.auto_filter=AutoFilter();tab.autoFilter=AutoFilter(ref='A1:B4')
    tab.autoFilter.add_filter_column(0,['A']);raw.save(p)
    wb=Workbook(p);assert V(wb,'S',9,4)==VALUE_ERR
    # Filter top is the header row, not filterable data. First and last data rows
    # must reject; just after the filter is safe. Column-blind rejection is conservative.
    s['B5']=7
    for a,f in {'H1':'=SUBTOTAL(3,B1:B1)','H2':'=SUBTOTAL(9,B2:B2)',
                'H3':'=SUBTOTAL(9,B4:B4)','H4':'=SUBTOTAL(9,B5:B5)',
                'H5':'=SUBTOTAL(9,B1:B2)'}.items():s[a]=f
    raw.save(p);edge=Workbook(p)
    assert V(edge,'S',1,8)==1
    assert V(edge,'S',2,8)==VALUE_ERR
    assert V(edge,'S',3,8)==VALUE_ERR
    assert V(edge,'S',4,8)==7
    assert V(edge,'S',5,8)==VALUE_ERR
    # Dropdowns without active criteria are not filters, retain manual-hidden semantics.
    tab.autoFilter=AutoFilter(ref='A1:B4');s.auto_filter=AutoFilter(ref='A1:B4');raw.save(p)
    wb=Workbook(p);assert V(wb,'S',9,4)==10;assert V(wb,'S',109,4)==2
    # Older retained models lack metadata. Do not reinterpret missing as inactive.
    del wb.sheets['s'].active_filter_ranges;wb.cache.clear()
    assert V(wb,'S',9,4)==VALUE_ERR


def test_subtotal_unresolved_reference_never_returns_plausible_count():
    wb=make_wb({'S':{(1,1):2,(2,1):3,(1,2):'=SUBTOTAL(9,A1+A2)',
                    (2,2):'=SUBTOTAL(2,A1+A2)',(3,2):'=SUBTOTAL(3,A1+A2)'}})
    for r in range(1,4):assert V(wb,'S',r,2)==VALUE_ERR
    assert any('subtotal-reference-provenance' in str(n) for n in wb.notes)


def test_standalone_smoke_and_masked_diagnostic_release_gate():
    from smoke_check import run
    assert run()['production_ready'] is False


def test_offline_fixture_hash_typed_edits_and_no_false_authority(tmp_path):
    import importlib.util,hashlib,copy
    from pathlib import Path
    path=Path(__file__).resolve().parents[2]/'offline_fixture.py'
    spec=importlib.util.spec_from_file_location('offline_fixture_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original=tmp_path/'fixture.xlsx';raw=openpyxl.Workbook();s=raw.active;s.title='S'
    s['A1']=2;s['B1']='=A1*3';s['C1']='=IFERROR(_XLUDF.NUMBERVALUE("1"),0)';raw.save(original)
    locator=lambda c:{'sheet':'S','row':1,'col':c}
    val=lambda x:{'type':'number','value':x}
    fixture={'schema_version':1,'workbook_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
             'as_of':'2026-11-11','evidence':{'kind':'synthetic','reference':'authored test fixture','limits':'Not a client expected value or approval.'},
             'observations':[{'cell':locator(2),'expected_before':val(6),'expected_after':val(12)},
                             {'cell':locator(3),'expected_before':val(0),'expected_after':val(0)}],
             'edits':[{'cell':locator(1),'before':val(2),'after':val(4)}]}
    result=module.run(original,fixture)
    assert result['all_expected_values_match'] and not result['release_ready']
    assert any('function:_XLUDF.NUMBERVALUE' in n for n in result['diagnostics'])
    assert hashlib.sha256(original.read_bytes()).hexdigest()==fixture['workbook_sha256']
    for alteration in ['hash','bool-number','formula-target','formula-text','duplicate-edit','baseline','approval-label','unknown-field','case-alias-duplicate','locator-extra','bool-version']:
        bad=copy.deepcopy(fixture)
        if alteration=='hash':bad['workbook_sha256']='0'*64
        if alteration=='bool-number':bad['edits'][0]['after']['value']=True
        if alteration=='formula-target':bad['edits'][0]['cell']=locator(2)
        if alteration=='formula-text':bad['edits'][0]['after']={'type':'text','value':'=1+1'}
        if alteration=='duplicate-edit':bad['edits']*=2
        if alteration=='baseline':bad['edits'][0]['before']=val(9)
        if alteration=='approval-label':bad['evidence']['kind']='client-approved'
        if alteration=='unknown-field':bad['send_to']='unapproved'
        if alteration=='case-alias-duplicate':
            bad['edits'].append(copy.deepcopy(bad['edits'][0]));bad['edits'][1]['cell']['sheet']='s'
        if alteration=='locator-extra':bad['edits'][0]['cell']['new_goal']='unapproved'
        if alteration=='bool-version':bad['schema_version']=True
        with pytest.raises(ValueError):module.run(original,bad)
        assert hashlib.sha256(original.read_bytes()).hexdigest()==fixture['workbook_sha256']
