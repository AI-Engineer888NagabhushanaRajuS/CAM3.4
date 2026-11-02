"""
SPEC-017 bug (reports/ex_inv_vl.py _find_volume): volume matched with == and no type coercion,
so a numeric volume stored as 1 was not found when asked for "1" and the sheet came out empty
with no error. Compare the labels as strings.
"""
import os
import sys

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_find_volume_matches_int_and_string_labels():
    sys.path.insert(0, SUP)
    try:
        import reports.ex_inv_vl as ex
    finally:
        sys.path.remove(SUP)
    volumes = [{"volume": 1, "qty": 10}]
    assert ex._find_volume(volumes, "1") is not None
    assert ex._find_volume(volumes, 1) is not None
