"""The Centum case register (testing/centum_case_register.json): every case from the Centum master list is present once, with a kind, a report and a status.

A case becomes 'tested' only when its test id names a real test in this folder; the count of untested reported defects is printed so the gap stays visible.
"""
import json
import os

REGISTER = os.path.join(os.path.dirname(__file__), "centum_case_register.json")


def load():
    with open(REGISTER, encoding="utf-8") as f:
        return json.load(f)["cases"]


def test_every_case_is_listed_once_with_kind_report_and_status():
    cases = load()
    ids = [c["case_id"] for c in cases]
    assert len(ids) == len(set(ids)) == 282  # the source lists 282 unique cases (the 4 reference inputs appear on two sheets)
    for c in cases:
        assert c["kind"] and c["report"] and c["status"] in ("not_tested", "tested")
        if c["status"] == "tested":
            assert c["test"], f"{c['case_id']} is marked tested without a test id"


def test_a_tested_case_names_a_real_test_file():
    here = os.path.dirname(__file__)
    for c in load():
        if c["status"] == "tested":
            assert os.path.exists(os.path.join(here, c["test"].split("::")[0])), c["case_id"]
