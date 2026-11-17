"""Regression tests for two fixes found by checking RFQ-000069's shipped CBOM export against the engine.

1. SUMPRODUCT(--ISERROR(range)) over a range that runs past the sheet's used rows is a valid count (Excel: blank cells are not
   errors). The engine used to return #NAME? here. ISBLANK over the same tail must still fail closed: it is TRUE on blanks.
2. A formula that refers to an empty cell is empty inside the engine (so comparisons such as X<>"" behave as in Excel) and is
   shown as 0, the value Excel stores.
"""
import os
import sys
import tempfile

import openpyxl

ENGINE = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ENGINE)
import excel_formula_engine as fe  # noqa: E402


def _book(tmp_path):
    raw = openpyxl.Workbook()
    s = raw.active
    s.title = 'Data'
    s.append(['label', 'value'])
    s.append(['a', 1])
    s.append(['b', 2])
    s['D1'] = '=SUMPRODUCT(--ISERROR(Data!A1:A9))'
    s['D2'] = '=SUMPRODUCT(--ISBLANK(Data!A1:A9))'
    s['D3'] = '=C9'
    s['D4'] = '=IF(C9<>"",1,0)'
    p = os.path.join(str(tmp_path), 'blank_tail.xlsx')
    raw.save(p)
    return p


def test_iserror_count_over_blank_tail_is_a_number_not_name_error(tmp_path):
    w = fe.Workbook(_book(tmp_path))
    assert w.cell_value_now('Data', 1, 4) == 0


def test_isblank_over_blank_tail_still_fails_closed(tmp_path):
    w = fe.Workbook(_book(tmp_path))
    assert fe.is_error(w.cell_value_now('Data', 2, 4))


def test_reference_to_empty_cell_is_empty_for_comparisons(tmp_path):
    w = fe.Workbook(_book(tmp_path))
    assert fe.is_blank(w.cell_value_now('Data', 3, 4)) or w.cell_value_now('Data', 3, 4) == 0
    assert w.cell_value_now('Data', 4, 4) == 0


def test_verify_treats_an_empty_result_as_the_stored_zero():
    import importlib.util
    from excel_formula_engine.values import BLANK
    spec = importlib.util.spec_from_file_location('formula_verify', os.path.join(ENGINE, '..', '..', 'formula_verify.py'))
    v = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v)
    assert v.same(fe, BLANK, 0.0) is True
    assert v.same(fe, BLANK, 0) is True
    assert v.same(fe, BLANK, 5.0) is False


def test_countifs_not_equal_keeps_trailing_space_in_the_criterion(tmp_path):
    # RFQ-000024's 7.0 CBOM VL-1 AN67: COUNTIFS(G,"<>"&G67, C,C67) with G67 = 'BAT54SW-QF ' (trailing space) must count 0.
    raw = openpyxl.Workbook()
    s = raw.active
    s.title = 'S'
    s.append(['C', 'G'])
    s.append(['P1', 'X1 '])
    s.append(['P1', 'X1 '])
    s['D2'] = '=COUNTIFS($B$2:$B$3,"<>"&B2,$A$2:$A$3,A2)'
    p = os.path.join(str(tmp_path), 'countifs_trailing.xlsx')
    raw.save(p)
    w = fe.Workbook(p)
    assert w.cell_value_now('S', 2, 4) == 0
