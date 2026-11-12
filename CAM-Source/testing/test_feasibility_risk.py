"""Feasibility & Risk verdicts (mcp-tools/reporting/superset/reports/feasibility_risk.py): pure functions over the SCRUB BOM and QuoteWin frames."""
import datetime
import os
import sys

import openpyxl
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset", "reports")))
import feasibility_risk as fr  # noqa: E402

TODAY = datetime.date(2026, 11, 11)


def scrub(*rows):
    base = {"fg": "FG1", "assembly": "FG1", "cpn": "", "mpn": "", "description": "d", "commodity": "RES", "quantity": 2.0, "part_status": "Active", "ltb_date": None}
    return pd.DataFrame([{**base, **r} for r in rows])


def quotes(*rows):
    base = {"part_number": "", "mfg_part_number": "", "cost_1_conv": 0.01, "cost_2_conv": None, "lead_time": 8.0, "part_status": None, "ncnr": None, "exp_date": None}
    return pd.DataFrame([{**base, **r} for r in rows])


def one(scrub_rows, quote_rows, **kw):
    return fr.feasibility_rows(scrub(*scrub_rows), quotes(*quote_rows), as_of=TODAY, **kw)[0]


def test_a_priced_part_with_a_short_lead_time_can_be_built_at_low_risk():
    r = one([{"cpn": "R1"}], [{"part_number": "R1"}])
    assert (r["verdict"], r["risk"], r["reasons"], r["lead_time"]) == ("Can build", "Low", "", 8.0)


def test_an_eol_or_discontinued_part_cannot_be_built_and_a_part_without_any_price_is_uncosted():
    eol = one([{"cpn": "R1", "part_status": "EOL"}], [{"part_number": "R1"}])
    assert eol["verdict"] == "Cannot build" and eol["risk"] == "High" and "EOL" in eol["reasons"]
    quote_says = one([{"cpn": "R1"}], [{"part_number": "R1", "part_status": "Discontinued"}])
    assert quote_says["verdict"] == "Cannot build" and "DISCONTINUED" in quote_says["reasons"]
    uncosted = one([{"cpn": "R1"}], [{"part_number": "R1", "cost_1_conv": 0}])
    assert uncosted["verdict"] == "Cannot build" and "uncosted" in uncosted["reasons"]
    none_at_all = one([{"cpn": "R1"}], [{"part_number": "OTHER"}])
    assert none_at_all["verdict"] == "Cannot build"


def test_medium_risks_are_flagged_with_their_reason_and_can_still_be_built():
    long_lead = one([{"cpn": "R1"}], [{"part_number": "R1", "lead_time": 26.0}])
    assert (long_lead["verdict"], long_lead["risk"]) == ("Can build", "Medium") and "lead time 26 weeks is over 20" in long_lead["reasons"]
    assert one([{"cpn": "R1", "part_status": "NRFND"}], [{"part_number": "R1"}])["risk"] == "Medium"
    assert one([{"cpn": "R1"}], [{"part_number": "R1", "ncnr": "Y"}])["risk"] == "Medium"
    expired = one([{"cpn": "R1"}], [{"part_number": "R1", "exp_date": datetime.datetime(2025, 6, 30)}])
    assert expired["risk"] == "Medium" and "validity has passed" in expired["reasons"]


def test_the_best_lead_time_of_all_priced_quotes_counts_and_the_limit_is_a_setting():
    both = one([{"cpn": "R1"}], [{"part_number": "R1", "lead_time": 30.0}, {"part_number": "R1", "lead_time": 12.0}])
    assert both["lead_time"] == 12.0 and both["risk"] == "Low"
    strict = one([{"cpn": "R1"}], [{"part_number": "R1", "lead_time": 12.0}], settings={"lead_time_limit_weeks": 10})
    assert strict["risk"] == "Medium" and "over 10" in strict["reasons"]


def test_high_risks_that_are_not_blockers_are_no_lead_time_and_a_last_time_buy_date():
    r = one([{"cpn": "R1", "ltb_date": datetime.date(2027, 3, 1)}], [{"part_number": "R1", "lead_time": None}])
    assert r["verdict"] == "Can build" and r["risk"] == "High" and "no lead time quoted" in r["reasons"] and "last-time-buy date 2027-03-01" in r["reasons"]


def test_a_part_is_found_by_its_mpn_and_a_sub_assembly_gets_no_line_of_its_own():
    r = fr.feasibility_rows(scrub({"cpn": "SUB", "assembly": "FG1"}, {"cpn": "R1", "mpn": "MPN-1", "assembly": "SUB"}), quotes({"part_number": "X", "mfg_part_number": "mpn-1"}), as_of=TODAY)
    assert [x["cpn"] for x in r] == ["R1"] and r[0]["verdict"] == "Can build"


def test_the_summary_adds_up_and_counts_the_machine_rules():
    rows = fr.feasibility_rows(scrub({"cpn": "A"}, {"cpn": "B"}, {"cpn": "C"}), quotes({"part_number": "A"}, {"part_number": "B", "lead_time": 30.0}), as_of=TODAY)
    s = fr.summary(rows)
    assert (s["lines"], s["can_build"], s["cannot_build"]) == (3, 2, 1) and s["high"] + s["medium"] + s["low"] == 3
    assert s["machine_rules"] == 0 and s["lead_time_limit_weeks"] == 20


def test_the_tab_has_plain_values_the_rule_set_and_the_machine_note():
    rows = fr.feasibility_rows(scrub({"cpn": "A"}, {"cpn": "B"}), quotes({"part_number": "A"}), as_of=TODAY)
    wb = openpyxl.Workbook()
    ws = fr.build_feasibility_sheet(wb, rows)
    assert ws.title == "Feasibility & Risk"
    text = " ".join(str(c.value) for row in ws.iter_rows(max_row=3) for c in row if c.value)
    assert "Rule set" in text and "none are saved in Settings" in text and "2 lines" in text
    values = [[c.value for c in row] for row in ws.iter_rows(min_row=6)]
    assert [v[2] for v in values] == ["A", "B"] and [v[9] for v in values] == ["Can build", "Cannot build"]
    assert not any(isinstance(c.value, str) and c.value.startswith("=") for row in ws.iter_rows() for c in row)


# ---- the rules are settings (Settings > Feasibility), not code ----

def test_every_default_rule_can_be_switched_off_or_changed_by_a_setting():
    base = [{"cpn": "R1", "part_status": "NRFND", "ltb_date": datetime.date(2027, 3, 1)}]
    q = [{"part_number": "R1", "lead_time": None, "ncnr": "Y"}]
    default = one(base, q)
    assert default["risk"] == "High" and "NRFND" in default["reasons"] and "NCNR" in default["reasons"] and "no lead time" in default["reasons"]
    quiet = one(base, q, settings={"medium_statuses": [], "no_lead_time_high": False, "ltb_high": False, "ncnr_medium": False})
    assert (quiet["verdict"], quiet["risk"], quiet["reasons"]) == ("Can build", "Low", "")
    obsolete = one([{"cpn": "R1", "part_status": "Obsolete"}], [{"part_number": "R1"}], settings={"cannot_build_statuses": ["obsolete"]})
    assert obsolete["verdict"] == "Cannot build" and "OBSOLETE" in obsolete["reasons"]
    priced_only = one([{"cpn": "R1"}], [], settings={"no_price_cannot_build": False})
    assert priced_only["verdict"] == "Can build"


def test_a_machine_rule_saved_in_settings_decides_the_verdict_and_names_itself_in_the_reason():
    rules = {"constraints": [
        {"name": "No 0201 placement", "column": "description", "operator": "contains", "value": "0201", "effect": "cannot_build"},
        {"name": "Fine pitch needs review", "column": "description", "operator": "contains", "value": "QFN", "effect": "medium"},
        {"name": "Heavy part", "column": "quantity", "operator": "gt", "value": "10", "effect": "high"},
    ]}
    tiny = one([{"cpn": "R1", "description": "RES 0201 10K"}], [{"part_number": "R1"}], settings=rules)
    assert tiny["verdict"] == "Cannot build" and tiny["risk"] == "High" and "machine rule: No 0201 placement (description contains 0201)" in tiny["reasons"]
    qfn = one([{"cpn": "U1", "description": "IC QFN-32"}], [{"part_number": "U1"}], settings=rules)
    assert (qfn["verdict"], qfn["risk"]) == ("Can build", "Medium")
    many = one([{"cpn": "C1", "quantity": 40.0}], [{"part_number": "C1"}], settings=rules)
    assert (many["verdict"], many["risk"]) == ("Can build", "High") and "quantity gt 10" in many["reasons"]
    untouched = one([{"cpn": "C2", "description": "CAP 0603"}], [{"part_number": "C2"}], settings=rules)
    assert (untouched["verdict"], untouched["risk"], untouched["reasons"]) == ("Can build", "Low", "")


def test_the_tab_lists_the_rules_it_used_and_a_bad_rule_stops_the_step_instead_of_being_ignored():
    rules = {"lead_time_limit_weeks": 12, "constraints": [{"name": "No BGA", "column": "description", "operator": "contains", "value": "BGA", "effect": "cannot_build"}]}
    rows = fr.feasibility_rows(scrub({"cpn": "A"}), quotes({"part_number": "A"}), as_of=TODAY, settings=rules)
    ws = fr.build_feasibility_sheet(openpyxl.Workbook(), rows, settings=rules)
    text = " ".join(str(c.value) for row in ws.iter_rows(max_row=3) for c in row if c.value)
    assert "over 12 weeks" in text and "No BGA (description contains BGA) -> cannot build" in text
    for bad in ({"column": "nope"}, {"operator": "like"}, {"effect": "maybe"}, {"name": ""}, {"value": ""}):
        rule = {"name": "x", "column": "description", "operator": "contains", "value": "v", "effect": "high", **bad}
        try:
            fr.normalize({"constraints": [rule]})
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")
    try:
        fr.normalize({"lead_time_limit_weeks": 0})
    except ValueError:
        return
    raise AssertionError("a 0-week limit was accepted")
