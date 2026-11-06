"""SPEC-021: failure explanations and the run list. Real failure texts below are copied from this stack's router log."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router")))
import run_history as rh  # noqa: E402

SHEET = ("centum_intake__standardize_scrub_bom failed: Could not find a sheet named 'SCRUB BOM' in "
         "/app/fastapi-router/staged/inbox/449701_BOM_Centum_BOM.xlsx. Available sheets: ['BOM']")


def test_wrong_sheet_is_invalid_input_with_what_the_file_has_and_no_rerun():
    c = rh.classify_failure(SHEET)
    assert c["kind"] == "invalid_input" and c["can_rerun"] is False
    assert "SCRUB BOM" in c["title"] and "449701_BOM_Centum_BOM.xlsx" in c["cause"] and "has: BOM" in c["cause"]
    assert "/app/" not in c["cause"]                       # the server path is not shown, only the file name
    assert c["step"] == "Standardize scrub bom" and "new upload" in c["next_step"]


@pytest.mark.parametrize("text,title", [
    ("centum_intake__standardize_quote_win failed: No QuoteWin file uploaded for rfq_id=RFQ-000005", "no QuoteWin file"),
    ("centum_intake__standardize_quote_win failed: Could not locate the QuoteWin data header row (expected columns: ['Part Number'])", "header row"),
])
def test_quotewin_problems_are_invalid_input(text, title):
    c = rh.classify_failure(text)
    assert c["kind"] == "invalid_input" and title in c["title"] and not c["can_rerun"]


def test_missing_rate_is_configuration_and_points_to_settings():
    c = rh.classify_failure("centum_reporting__export_reports failed: no active conversion rate for 'INR' -> 'USD'; refusing to report an unconverted amount")
    assert c["kind"] == "configuration" and c["can_rerun"] and "INR" in c["title"] and "Settings" in c["next_step"]


def test_anything_else_is_a_tool_error_with_trimmed_raw_text_and_rerun():
    c = rh.classify_failure("some_tool failed: " + "x" * 2000)
    assert c["kind"] == "tool_error" and c["can_rerun"] and len(c["raw"]) == rh.RAW_LIMIT and len(c["cause"]) <= rh.RAW_LIMIT
    assert rh.classify_failure("")["kind"] == "tool_error"  # no text at all must not crash


T0 = datetime(2026, 11, 6, 8, 0, 0, tzinfo=timezone.utc)


class FakeExec:
    def __init__(self, run_id, status, start, secs, memo=None):
        self.id, self.run_id, self.status = "rfq-RFQ-1", run_id, SimpleNamespace(name=status)
        self.start_time = start
        self.close_time = start + timedelta(seconds=secs) if status != "RUNNING" else None
        self._memo = memo or {}

    async def memo(self):
        return self._memo


class FakeClient:
    def __init__(self, execs, results):
        self.execs, self.results, self.queries = execs, results, []

    def list_workflows(self, query, limit):
        self.queries.append(query)

        async def gen():
            for e in self.execs:
                yield e
        return gen()

    def get_workflow_handle(self, wid, run_id):
        res = self.results[run_id]

        async def result(follow_runs=False):
            if isinstance(res, Exception):
                raise res
            return res
        return SimpleNamespace(result=result)


def failure_error(text):
    from temporalio.client import WorkflowFailureError
    from temporalio.exceptions import ApplicationError
    err = WorkflowFailureError(cause=ApplicationError(text, non_retryable=True))
    return err


def test_runs_listed_newest_first_with_status_duration_and_who():
    execs = [
        FakeExec("old", "FAILED", T0, 12, {"started_by": "Dana"}),
        FakeExec("new", "COMPLETED", T0 + timedelta(hours=1), 95, {"started_by": "CAM assistant"}),
        FakeExec("live", "RUNNING", T0 + timedelta(hours=2), 0),
        FakeExec("rej", "COMPLETED", T0 + timedelta(minutes=30), 40),
        FakeExec("sup", "TERMINATED", T0 + timedelta(minutes=10), 5),
    ]
    results = {"old": failure_error(SHEET), "new": {"status": "completed"}, "rej": {"status": "rejected"}, "sup": None}
    fc = FakeClient(execs, results)
    runs = asyncio.run(rh.list_runs("RFQ-1", fc))
    assert fc.queries == ['WorkflowId = "rfq-RFQ-1"']
    assert [r["run_id"] for r in runs] == ["live", "new", "rej", "sup", "old"]
    by = {r["run_id"]: r for r in runs}
    assert by["live"]["status"] == "running" and by["live"]["duration_ms"] is None
    assert by["new"]["status"] == "passed" and by["new"]["duration_ms"] == 95000 and by["new"]["started_by"] == "CAM assistant"
    assert by["rej"]["status"] == "stopped" and by["sup"]["status"] == "replaced"
    assert by["old"]["status"] == "failed" and by["old"]["started_by"] == "Dana" and by["old"]["can_rerun"] is False
    assert by["old"]["failure"]["kind"] == "invalid_input" and by["old"]["failed_step"] == "Standardize scrub bom"
    assert by["live"]["started_by"] == "unknown"


def test_rfq_id_cannot_inject_into_the_visibility_query():
    for bad in ['x" OR 1=1', "a b", "", "x" * 65, "a'b"]:
        with pytest.raises(ValueError):
            asyncio.run(rh.list_runs(bad, FakeClient([], {})))
