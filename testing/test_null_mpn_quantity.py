"""scrub_bom_to_database.mpn is nullable, but the per-assembly and per-FG quantity sums grouped
on mpn with pandas' default dropna=True, so a part with no MPN silently lost its quantity
(part qty 0 on the BOM matrix). Such a row must still count.
"""
import os
import sys

import pandas as pd

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def _em():
    sys.path.insert(0, SUP)
    try:
        from templates import excel_mappings as em
    finally:
        sys.path.remove(SUP)
    return em



def test_assembly_quantity_keeps_rows_with_null_mpn():
    em = _em()
    scrub = pd.DataFrame([
        {"fg": "F", "assembly": "A", "cpn": "C-1", "mpn": None, "quantity": 4},
        {"fg": "F", "assembly": "A", "cpn": "C-2", "mpn": "M-2", "quantity": 1},
    ])
    sums = em.fg_assembly_part_qty_sums(scrub)
    assert sum(sums.values()) == 5, sums
    assert any(k[2] == "C-1" and k[3] == "" and v == 4 for k, v in sums.items()), sums


def test_fg_quantity_keeps_rows_with_null_mpn():
    em = _em()
    scrub = pd.DataFrame([
        {"fg": "F", "assembly": "A", "cpn": "C-1", "mpn": None, "quantity": 4},
        {"fg": "F", "assembly": "A", "cpn": "C-2", "mpn": "M-2", "quantity": 1},
    ])
    sums = em.fg_part_qty_sums(scrub)
    assert sum(sums.values()) == 5, sums
