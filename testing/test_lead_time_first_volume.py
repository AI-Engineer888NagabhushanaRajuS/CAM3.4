"""
SPEC-017 bug (templates/excel_mappings.py): the lead-time payloads kept only volumes "proto"
and "1", so an RFQ with no volume 1 (volumes ["2"]) produced an empty lead-time section. The
rule is: prefer proto, else the lowest numbered volume that exists.
"""
import os
import sys

import pandas as pd

SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))


def _mappings():
    sys.path.insert(0, SUP)
    try:
        from templates import excel_mappings as em
    finally:
        sys.path.remove(SUP)
    return em


def test_volume_two_only_rfq_still_has_lead_time_rows():
    em = _mappings()
    cbom = pd.DataFrame([
        {"cpn": "C1", "fg": "F1", "is_data": True, "final_lead_time": 6, "volume_no": "2"},
        {"cpn": "C2", "fg": "F1", "is_data": True, "final_lead_time": 9, "volume_no": "2"},
    ])
    payload = em.to_lead_time_fg_payload(cbom)
    assert len(payload["rfqs"]) == 2, payload
