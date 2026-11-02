"""
SPEC-017 bug (templates/excel_mappings.py to_cbom_tree_payload): the FG-level accumulation used
the RAW structural set, while the BOM matrix and the rest of the module use the effective set
(dual-role CPNs excluded from containers only). A dual-role CPN (structural by name, own price,
no costed children) was counted in the matrix but dropped from the tree totals, so the two
sheet totals disagreed. The tree must use the same effective set.
"""
import os
import sys

import pandas as pd

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def test_tree_totals_count_a_dual_role_cpn_like_the_matrix():
    sys.path.insert(0, SUP)
    try:
        from templates import excel_mappings as m
    finally:
        sys.path.remove(SUP)
    cbom = pd.DataFrame([
        {"cpn": "F", "fg": "F", "assembly": "F", "is_data": False, "is_assembly": True, "volume_no": "1",
         "display_order": 0, "part_qty": 1, "final_price_conv": None, "volume_qty": 100, "batch_qty": 0,
         "description": "root", "commodity": "x", "bom_item_id": 0},
        {"cpn": "S", "fg": "F", "assembly": "F", "is_data": True, "is_assembly": False, "volume_no": "1",
         "display_order": 1, "part_qty": 1, "final_price_conv": 10.0, "volume_qty": 100, "batch_qty": 0,
         "description": "sub", "commodity": "x", "bom_item_id": 1},
        {"cpn": "Y", "fg": "F", "assembly": "S", "is_data": True, "is_assembly": False, "volume_no": "1",
         "display_order": 2, "part_qty": 1, "final_price_conv": None, "volume_qty": 100, "batch_qty": 0,
         "description": "kid", "commodity": "x", "bom_item_id": 2},
    ])
    scrub = pd.DataFrame([
        {"fg": "F", "assembly": "F", "cpn": "S", "mpn": "MS", "quantity": 1, "level": "1",
         "hierarchy_multiplier": 1.0, "bom_item_id": 1, "description": "sub", "commodity": "x", "inventory_stock": 0},
        {"fg": "F", "assembly": "S", "cpn": "Y", "mpn": "MY", "quantity": 1, "level": "2",
         "hierarchy_multiplier": 1.0, "bom_item_id": 2, "description": "kid", "commodity": "x", "inventory_stock": 0},
    ])
    cbom, scrub = m._sanitize(cbom), m._sanitize(scrub)
    tree = m.to_cbom_tree_payload(cbom, scrub, "RFQ-T")
    summary_vol = tree["summary"][0]["volumes"][0]
    own_row = tree["F"]["F"][0]["volumes"][0]
    # The dual-role CPN S has its own costed row (1000 = qty 100 x price 10). Its FG total must
    # include it, not 0 (the bug left it out of the FG accumulators).
    assert own_row["ext_part_vol_price_conv"] == 1000.0, own_row
    assert summary_vol["ext_part_vol_price_conv"] == own_row["ext_part_vol_price_conv"], summary_vol
