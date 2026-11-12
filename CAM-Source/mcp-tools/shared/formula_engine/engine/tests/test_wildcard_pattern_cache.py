"""Local pure-helper cache regression; does not certify new Excel semantics."""
import datetime
import openpyxl
from excel_formula_engine import Workbook
from excel_formula_engine import functions as f


def test_pattern_cache_purity_bound_eviction_overlength_clear():
    f._clear_wildcard_pattern_cache()
    assert f._WILDCARD_PATTERN_CACHE_MAXSIZE == 1024
    assert f._WILDCARD_PATTERN_CACHE_MAX_CHARS == 255
    patterns = ['', '*', '?', '~', '~~', '~*', '~?', '~~*', 'a.b', '[x]', 'a\\b', 'é 中😀', '*\n?']
    for text in patterns:
        assert f._wildcard_regex(text) == f._wildcard_regex_uncached(text)
    before = f._wildcard_regex_cached.cache_info()
    assert f._wildcard_regex('é 中😀') == f._wildcard_regex_uncached('é 中😀')
    assert f._wildcard_regex_cached.cache_info().hits == before.hits + 1
    before = f._wildcard_regex_cached.cache_info()
    for text in ['x' * 256, '*' + 'é' * 4096]:
        assert f._wildcard_regex(text) == f._wildcard_regex_uncached(text)
    assert f._wildcard_regex_cached.cache_info() == before
    f._clear_wildcard_pattern_cache()
    for i in range(1025):
        text = 'unique_' + str(i)
        assert f._wildcard_regex(text) == f._wildcard_regex_uncached(text)
    info = f._wildcard_regex_cached.cache_info()
    assert info.currsize == info.maxsize == 1024 and info.misses == 1025
    assert f._wildcard_regex('unique_0') == f._wildcard_regex_uncached('unique_0')
    assert f._wildcard_regex_cached.cache_info().misses == 1026
    f._clear_wildcard_pattern_cache()
    assert f._wildcard_regex_cached.cache_info().currsize == 0


def test_pattern_cache_search_match_criteria_outputs_and_edit(tmp_path):
    raw = openpyxl.Workbook(); sheet = raw.active; sheet.title = 'S'
    for row, text in enumerate(['a*b', 'a?b', 'tilde~x', 'AB', 'é 中'], 1):
        sheet.cell(row, 1, text); sheet.cell(row, 2, row)
    formulas = [
        ('=SUMIF(A1:A5,"a~*b",B1:B5)', 1),
        ('=COUNTIF(A1:A5,"a?b")', 2),
        ('=MATCH("a~?b",A1:A5,0)', 2),
        ('=SEARCH("~*","a*b")', 2),
        ('=SEARCH("É","é 中")', 1),
        ('=SUMIFS(B1:B5,A1:A5,"*")', 15),
        ('=MATCH("tilde~~x",A1:A5,0)', 3),
        ('=COUNTIF(A1:A5,"É*")', 1),
    ]
    for row, (formula, _) in enumerate(formulas, 1):sheet.cell(row, 4, formula)
    path = tmp_path / 'pattern_cache.xlsx'; raw.save(path)
    w = Workbook(str(path), today=datetime.date(2026, 11, 11))
    for row, (_, expected) in enumerate(formulas, 1):
        assert w.cell_value_now('S', row, 4) == expected
    w.set_value('S', 1, 2, 7)
    assert w.cell_value_now('S', 1, 4) == 7
    assert w.cell_value_now('S', 6, 4) == 21
    assert not w.notes and not w.cycle_diagnostics
    f._clear_wildcard_pattern_cache()
