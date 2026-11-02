"""
SPEC-017 bug (templates/excel_mappings.py to_bom_matrix_payload): when every FG has only its
root row, the is_data filter leaves nothing, and apply(axis=1) on the empty frame returns a
column-less frame, so the later groupby("cpn") raised KeyError. Must return a payload instead.
"""
import os
import sys

import pandas as pd

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_bom_matrix_with_only_root_rows_does_not_raise():
    sys.path.insert(0, SUP)
    try:
        from templates import excel_mappings as em
    finally:
        sys.path.remove(SUP)
    cbom = pd.DataFrame([
        {"cpn": "F", "fg": "F", "assembly": "F", "is_data": False, "is_assembly": True, "volume_no": "1",
         "display_order": 0, "part_qty": 1, "final_price_conv": None, "volume_qty": 100, "batch_qty": 0,
         "description": "root", "commodity": "x", "bom_item_id": 0, "level": "0"},
    ])
    scrub = pd.DataFrame([
        {"cpn": "F", "fg": "F", "assembly": "F", "mpn": "M", "quantity": 1, "level": "0",
         "bom_item_id": 0, "commodity": "x", "description": "root", "display_order": 0},
    ])
    payload = em.to_bom_matrix_payload(cbom, scrub)
    assert payload is not None
