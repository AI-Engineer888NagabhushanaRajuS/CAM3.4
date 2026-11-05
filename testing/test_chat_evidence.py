"""The RFQ assistant answers from the RFQ's own results, never from a model's memory.

chat_evidence turns the exported workbook (the values it stores) and the RFQ's live state into citable chunks.
Found when the assistant was run for real: it could not reach any data, and when it had none it let a model guess.
"""
import os
import sys

import openpyxl
import pytest

FR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))
SUP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-tools", "reporting", "superset"))
sys.path.insert(0, FR_DIR)
try:
    import chat_evidence as ce
finally:
    sys.path.remove(FR_DIR)


def make_export(path, rows=300):
    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Metric", "Value"])
    summary.append(["Total CBOM rows", rows])
    summary.append(["Go / no-go", "GO"])
    cbom = wb.create_sheet("CBOM")
    cbom.append(["cpn", "mpn", "description", "final_price_conv", "qty"])
    for i in range(1, rows + 1):
        cbom.append([f"UBR{i:04d}", f"MPN-{i}", f"capacitor {i}", round(i * 0.0137, 4), i])
    notes = wb.create_sheet("Notes")  # a title row above the real header
    notes.append(["Payment term details for VL-1"])
    notes.append(["Supplier Type", "Final buy value"])
    notes.append(["30 Days", 1234.5])
    wb.save(path)
    return str(path)


@pytest.fixture
def index(tmp_path):
    return ce.workbook_index(make_export(tmp_path / "CBOM_Report_T.xlsx"))


def by_label(index, label):
    return next(c for c in index["chunks"] if c["citation"]["label"] == label)


def test_every_row_is_a_chunk_that_cites_its_own_cells(index):
    chunk = by_label(index, "CBOM!A124:E124")  # row 124 = part 123 (row 1 is the header)
    assert "cpn=UBR0123" in chunk["text"] and "mpn=MPN-123" in chunk["text"] and "qty=123" in chunk["text"]
    assert chunk["citation"] == {"sourceType": "excel_export", "label": "CBOM!A124:E124",
                                 "identifier": {"workbook": "CBOM_Report_T.xlsx", "sheet": "CBOM", "row": 124}}


def test_a_title_row_above_the_header_is_not_mistaken_for_the_header(index):
    chunk = by_label(index, "Notes!A3:B3")
    assert "Supplier Type=30 Days" in chunk["text"] and "Final buy value=1234.5" in chunk["text"]


def test_naming_a_part_number_puts_that_row_first(index):
    found = ce.retrieve(index, "What is the price of UBR0123?")
    specific = [c for c in found["chunks"] if c["citation"]["label"] == "CBOM!A124:E124"]
    assert specific and found["missing_identifiers"] == []
    best = max(found["chunks"], key=lambda c: c["score"])
    assert best["citation"]["label"] == "CBOM!A124:E124"


def test_a_part_number_that_is_not_in_the_results_is_reported_missing_not_guessed(index):
    found = ce.retrieve(index, "What is the price of ZZZ-99999?")
    assert found["missing_identifiers"] == ["zzz-99999"]
    assert not any("zzz-99999" in c["text"].lower() for c in found["chunks"])


def test_small_tabs_are_always_shown_whole_so_summary_questions_have_their_data(index):
    found = ce.retrieve(index, "How many rows are there in total?")
    texts = " ".join(c["text"] for c in found["chunks"])
    assert "Metric=Total CBOM rows; Value=300" in texts and "Metric=Go / no-go; Value=GO" in texts
    assert any(c["citation"]["label"] == "Workbook tabs" for c in found["chunks"])


def test_one_question_never_puts_more_than_the_cap_in_front_of_the_model(index):
    found = ce.retrieve(index, "capacitor", top_k=30)
    assert sum(len(c["text"]) for c in found["chunks"]) <= ce.MAX_EVIDENCE_CHARS


def test_a_smaller_budget_is_honoured_and_still_keeps_the_best_row_first(index):
    small = ce.retrieve(index, "What is the price of UBR0123?", max_chars=2500)
    assert sum(len(c["text"]) for c in small["chunks"]) <= 2500
    assert any("UBR0123" in c["text"] for c in small["chunks"])   # matched rows outrank the small-tab filler
    broad_small = ce.retrieve(index, "capacitor", top_k=30, max_chars=2500)
    broad_full = ce.retrieve(index, "capacitor", top_k=30)
    assert sum(len(c["text"]) for c in broad_small["chunks"]) <= 2500
    assert len(broad_small["chunks"]) < len(broad_full["chunks"])   # the full budget really is bigger here


def test_the_newest_export_replaces_the_cached_one(tmp_path):
    path = tmp_path / "CBOM_Report_T.xlsx"
    make_export(path, rows=10)
    assert "Metric=Total CBOM rows; Value=10" in " ".join(c["text"] for c in ce.workbook_index(str(path))["chunks"])
    make_export(path, rows=20)
    os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
    assert "Metric=Total CBOM rows; Value=20" in " ".join(c["text"] for c in ce.workbook_index(str(path))["chunks"])


def test_the_pipeline_state_is_a_citable_chunk():
    chunk = ce.state_chunk("RFQ-1", 2, 8, False, [("BOM", "/inbox/12_BOM_x.xlsx", "CLEAN")])
    assert "active version 2" in chunk["text"] and "pipeline stage 8" in chunk["text"]
    assert "waiting for a human review: no" in chunk["text"] and "BOM: 12_BOM_x.xlsx (CLEAN)" in chunk["text"]
    assert chunk["citation"]["sourceType"] == "file_telemetry" and chunk["citation"]["label"] == "RFQ RFQ-1 status"


def test_the_assistant_sees_stored_values_not_formulas(tmp_path):
    sys.path.insert(0, SUP)
    try:
        import cached_values as cv
    finally:
        sys.path.remove(SUP)
    if cv.find_libreoffice() is None:
        pytest.skip("LibreOffice not installed")
    path = tmp_path / "CBOM_Report_F.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws.append(["Item", "Total"])
    ws.append(["widgets", "=2*21"])
    wb.save(path)
    assert cv.add_cached_values(path)["status"] == "ok"
    text = " ".join(c["text"] for c in ce.workbook_index(str(path))["chunks"])
    assert "Total=42" in text and "=2*21" not in text


def test_a_plain_number_in_the_question_is_not_a_part_number(index):
    found = ce.retrieve(index, "Which parts are above 1.25 or lead time over 20 weeks?")
    assert found["named_identifiers"] == [] and found["missing_identifiers"] == []


def test_named_and_missing_identifiers_are_told_apart(index):
    found = ce.retrieve(index, "Compare UBR0007 with ZZZ-99999")
    assert found["named_identifiers"] == ["ubr0007", "zzz-99999"] and found["missing_identifiers"] == ["zzz-99999"]


def make_crowded_export(path):
    """Like a real export: 15 small tabs that together are bigger than the whole evidence budget, plus a big CBOM."""
    wb = openpyxl.Workbook()
    first = wb.active
    first.title = "Summary"
    first.append(["Metric", "Value"])
    first.append(["Go / no-go", "GO"])
    for n in range(14):
        ws = wb.create_sheet(f"Small {n}")
        ws.append(["Item", "Note", "Amount"])
        for r in range(30):
            ws.append([f"item {n}-{r}", "x" * 60, r])
    cbom = wb.create_sheet("CBOM")
    cbom.append(["cpn", "mpn", "final_price_conv"])
    for i in range(1, 400):
        cbom.append([f"AC{i:04d}FR-0762KL", f"MPN-{i}", round(i * 0.01, 4)])
    wb.save(path)
    return str(path)


def test_small_tabs_never_push_out_the_row_of_a_part_that_exists(tmp_path):
    index = ce.workbook_index(make_crowded_export(tmp_path / "CBOM_Report_C.xlsx"))
    assert sum(len(c["text"]) for c in index["chunks"] if c["always"]) > ce.MAX_EVIDENCE_CHARS  # the crowding is real
    found = ce.retrieve(index, "What is the final price of AC0123FR-0762KL?")
    texts = [c["text"] for c in found["chunks"]]
    assert any("AC0123FR-0762KL" in t for t in texts), "the part's own row must be in the evidence"
    assert found["missing_identifiers"] == []
    assert sum(len(t) for t in texts) <= ce.MAX_EVIDENCE_CHARS


def test_an_aggregate_question_gets_the_summary_tabs_first_when_nothing_matches(tmp_path):
    index = ce.workbook_index(make_crowded_export(tmp_path / "CBOM_Report_C.xlsx"))
    found = ce.retrieve(index, "How are we doing overall?")
    labels = [c["citation"]["label"] for c in found["chunks"]]
    assert labels[0] == "Workbook tabs" and labels[1].startswith("Summary!")


def test_percentages_and_dates_read_the_way_the_sheet_shows_them(tmp_path):
    import datetime
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quotes"
    ws.append(["Supplier", "Margin", "Quoted on"])
    ws.append(["ACME", 0.25, datetime.datetime(2026, 1, 5)])
    ws["B2"].number_format = "0%"
    wb.save(tmp_path / "CBOM_Report_P.xlsx")
    text = " ".join(c["text"] for c in ce.workbook_index(str(tmp_path / "CBOM_Report_P.xlsx"))["chunks"])
    assert "Margin=25%" in text and "Quoted on=2026-01-05" in text and "T00:00" not in text


def test_a_cut_row_says_it_was_cut(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Wide"
    ws.append([f"col{i}" for i in range(80)])
    ws.append(["x" * 40 for _ in range(80)])
    wb.save(tmp_path / "CBOM_Report_W.xlsx")
    chunk = next(c for c in ce.workbook_index(str(tmp_path / "CBOM_Report_W.xlsx"))["chunks"] if c["citation"]["label"].startswith("Wide!"))
    assert chunk["text"].endswith("...[row truncated]") and len(chunk["text"]) < ce.MAX_ROW_CHARS + 30


def test_a_value_with_a_unit_is_not_mistaken_for_a_part_number(index):
    found = ce.retrieve(index, "Show the 10uF, 3.3V, 25V and 0402 parts")
    assert found["named_identifiers"] == [] and found["missing_identifiers"] == []


def test_the_rfqs_own_id_is_not_a_part_number_to_look_up(index):
    found = ce.retrieve(index, "Total for RFQ-CENTUM-PROOF-24?", rfq_id="RFQ-CENTUM-PROOF-24")
    assert found["named_identifiers"] == [] and found["missing_identifiers"] == []


def test_separators_and_case_do_not_hide_a_part_that_exists(index):
    found = ce.retrieve(index, "price of ubr-0123")
    assert found["named_identifiers"] == ["ubr-0123"] and found["missing_identifiers"] == []


def test_the_caller_can_tell_a_list_is_partial(index):
    found = ce.retrieve(index, "capacitor")
    assert found["matched_rows"] >= 299 and found["rows_in_results"] >= 300
    assert len([c for c in found["chunks"] if c["citation"]["label"].startswith("CBOM!")]) < found["matched_rows"]


def test_formula_cells_without_a_stored_value_are_reported(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws.append(["Item", "Total"])
    ws.append(["widgets", "=2*21"])   # written by openpyxl and never recalculated: no stored value
    wb.save(tmp_path / "CBOM_Report_U.xlsx")
    index = ce.workbook_index(str(tmp_path / "CBOM_Report_U.xlsx"))
    assert index["warning"] and index["warning"].startswith("1 of 1 formula cells")


def test_only_the_newest_few_workbooks_stay_cached(tmp_path):
    paths = [make_export(tmp_path / f"CBOM_Report_{n}.xlsx", rows=5) for n in range(6)]
    for p in paths:
        ce.workbook_index(p)
    assert len(ce._cache) <= 4



def test_a_part_that_only_an_attachment_names_is_not_called_missing(index):
    extra = [{"text": "notes.pdf p.1: ZZQ-99001 is approved as the second source", "tokens": ce._tokens("ZZQ-99001 approved second source"),
              "citation": {"sourceType": "attachment", "label": "notes.pdf p.1", "identifier": {"file": "notes.pdf"}},
              "always": False, "pinned": False}]
    found = ce.retrieve(index, "is ZZQ-99001 approved?", extra=extra)
    assert found["named_identifiers"] == ["zzq-99001"] and found["missing_identifiers"] == []
    assert any(c["citation"]["label"] == "notes.pdf p.1" for c in found["chunks"])


def test_a_part_number_at_the_end_of_a_sentence_still_finds_its_row(index):
    found = ce.retrieve(index, "What is the price for UBR0123.")
    assert found["named_identifiers"] == ["ubr0123"] and found["missing_identifiers"] == []
    assert "UBR0123" in found["chunks"][1]["text"] or any("UBR0123" in c["text"] for c in found["chunks"][:6])


def test_formulas_that_evaluate_to_blank_are_not_called_unstored(tmp_path):
    """After a recalculation a formula whose result is "" has no value either: that must not raise the warning."""
    sys.path.insert(0, SUP)
    try:
        import cached_values as cv
    finally:
        sys.path.remove(SUP)
    if cv.find_libreoffice() is None:
        pytest.skip("LibreOffice not installed")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws.append(["Item", "A", "B"])
    for i in range(10):
        ws.append([f"row{i}", f"=1+{i}", '=IF(1=2,"x","")'])
    path = tmp_path / "CBOM_Report_B.xlsx"
    wb.save(path)
    assert ce.workbook_index(str(path))["warning"]          # never recalculated: 20 of 20 have no value
    ce._cache.clear()
    assert cv.add_cached_values(path)["status"] == "ok"
    assert ce.workbook_index(str(path))["warning"] is None   # 10 of 20 blank by design is normal
