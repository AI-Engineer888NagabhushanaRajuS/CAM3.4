"""Revision History on a multi-level BOM (batch-05, 2026-11-18): its Assembly column held the FG, while '7.0 CBOM VL-n' column B
holds each part's PARENT assembly, so every lookup keyed on (assembly, CPN) for a part under a sub-assembly matched nothing and
Description / Commodity / Manufacturer / MPN / New Unit Price were empty in 340 of 365 rows. A CPN no quote covers showed FALSE."""
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SUP = os.path.join(ROOT, "mcp-tools", "reporting", "superset")


def _load():
    for p in (SUP, os.path.join(SUP, "templates")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import excel_mappings
    from reports.revision_history import revision_history_rows
    return excel_mappings, revision_history_rows


def test_assembly_is_the_parent_assembly_not_the_fg():
    em, _ = _load()
    scrub = pd.DataFrame([
        {"cpn": "FG-1", "fg": "FG-1", "assembly": "FG-1", "description": "Top", "mpn": None},
        {"cpn": "SUB-A", "fg": "FG-1", "assembly": "FG-1", "description": "Sub", "mpn": None},
        {"cpn": "R-100", "fg": "FG-1", "assembly": "SUB-A", "description": "Resistor", "mpn": "RC0603"},
        {"cpn": "C-200", "fg": "FG-1", "assembly": None, "description": "Cap", "mpn": "GRM"},
    ])
    payload = em.to_revision_history_payload("RFQ-X", scrub, pd.DataFrame(columns=["part_number"]))
    asm = {r["CPN"]: r["Assembly"] for r in payload["bom_data"]}
    assert asm["R-100"] == "SUB-A"      # the key column B of '7.0 CBOM VL-1' holds
    assert asm["C-200"] == "FG-1"       # no parent recorded: the FG, as before
    assert asm["SUB-A"] == "FG-1"


def test_a_cpn_without_a_quote_shows_a_dash_not_false():
    _, rows_of = _load()
    rows = rows_of({"centum_id": "-", "bom_data": [{"CPN": "CPN-9999", "Assembly": "-", "Description": "-", "MPN": "-"}], "rfqs": []})
    assert rows[2][1] == "-"
