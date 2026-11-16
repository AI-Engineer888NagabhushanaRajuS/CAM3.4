"""Python port of the Lead Time (FG Wise) report (Laravel PHP).

Three layers, mirroring the PHP pipeline:
  1. lead_time_fg_blocks() — port of BlockthreeController::lead_time_fg():
     computes the per-FG lead-time buckets from bom_details_json_data/rfqs,
     matching the input/output JSON documented in lead-time-fg-wise-report.md.
     This is the exact shape persisted to lead_time_fg.json_desc and the only
     shape app/Exports/FgLeadTimeExport.php's array() actually consumes
     correctly — three other call sites in the PHP codebase build differently
     -shaped data for that class and are broken as a result (see the .md's
     "Cross-check notes"); this port follows the one working shape.
  2. flatten_lead_time_fg() — port of FgLeadTimeExport::array()'s own
     dedup-by-FG + horizontal-merge logic: turns the per-FG blocks into the
     flat 2D array actually written to the sheet (one 2-column {LT, Count}
     table per FG, side by side, padded to a common row count).
  3. build_lead_time_fg_sheet() — port of FgLeadTimeExport::styles(): colors
     each 3-column group (2 data columns + 1 spacer) independently, scanning
     for that FG's own last non-blank row rather than the shared padded
     height.

No DB access happens here — bom_details_json_data/rfqs are supplied by the
caller, and the DB write (`lead_time_fg` table upsert) in the original PHP is
out of scope, consistent with every other port in this project.
"""

import re

from openpyxl.styles import Border, Font, PatternFill, Side

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")
_TOTAL_FONT = Font(bold=True)
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)


def _natural_key(value):
    """Mirrors PHP's ksort(..., SORT_NATURAL) for lead-time-week labels."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]


def lead_time_fg_blocks(payload):
    """Port of BlockthreeController::lead_time_fg(): per-FG lead-time buckets.

    payload: {"bom_details_json_data": [{"CPN":..., "FG":...}, ...],
              "rfqs": [{"cpn":..., "is_L1": bool, "lead_times":..., "volume_no":...}, ...]}
    returns: list of {"fg": ..., "data": [{"lead_time_weeks":..., "count_of_part_number":...}, ...]}
        — one block per FG, in first-seen FG order.
    """
    scrub_items = payload.get("bom_details_json_data", [])
    rfqs = payload.get("rfqs", [])

    cpn_to_fgs = {}
    fg_to_cpns = {}
    for entry in scrub_items:
        cpn = entry.get("CPN", "")
        fg = entry.get("FG", "")
        if cpn and fg:
            cpn_to_fgs.setdefault(cpn, {})[fg] = True
            fg_to_cpns.setdefault(fg, {})[cpn] = True

    rfq_cpns_all = set()
    rfq_has_l1 = set()
    rfq_has_valid_l1_lead = set()
    for rfq in rfqs:
        cpn = str(rfq.get("cpn", ""))
        rfq_cpns_all.add(cpn)
        lead_time = str(rfq.get("lead_times") or "").strip()
        if rfq.get("is_L1"):
            rfq_has_l1.add(cpn)
            if lead_time not in ("", "0"):
                rfq_has_valid_l1_lead.add(cpn)

    l1_rfqs = sorted((r for r in rfqs if r.get("is_L1")), key=lambda r: r.get("volume_no", 0))
    rfq_lead_map = {}
    for rfq in l1_rfqs:
        cpn = str(rfq.get("cpn", ""))
        lead_time = str(rfq.get("lead_times") or "").strip()
        if lead_time in ("", "0"):
            continue
        rfq_lead_map.setdefault(cpn, lead_time)

    fg_buckets = {}  # fg -> lead_time -> set of cpns
    for cpn, lead_time in rfq_lead_map.items():
        for fg in cpn_to_fgs.get(cpn, {}):
            fg_buckets.setdefault(fg, {}).setdefault(lead_time, set()).add(cpn)

    blocks = []
    for fg, cpns_in_fg in fg_to_cpns.items():
        lt_groups = fg_buckets.get(fg, {})
        fg_block = [
            {"lead_time_weeks": lt, "count_of_part_number": len(lt_groups[lt])}
            for lt in sorted(lt_groups, key=_natural_key)
        ]

        missing_count = sum(
            1 for cpn in cpns_in_fg
            if cpn not in rfq_cpns_all or cpn not in rfq_has_l1 or cpn not in rfq_has_valid_l1_lead
        )
        if missing_count > 0:
            fg_block.insert(0, {"lead_time_weeks": "", "count_of_part_number": missing_count})

        fg_block.append({"lead_time_weeks": "Grand Total", "count_of_part_number": len(cpns_in_fg)})

        blocks.append({"fg": fg, "data": fg_block})

    return blocks


def flatten_lead_time_fg(blocks):
    """Port of FgLeadTimeExport::array(): dedupe FGs, build one 2-col table
    per FG, pad to a common row count, and merge horizontally with a
    1-column spacer between tables.
    """
    horizontal_blocks = []
    seen_fgs = set()

    for fg_block in blocks:
        fg = str(fg_block.get("fg", "")).strip()
        if fg in seen_fgs:
            continue
        seen_fgs.add(fg)

        block = [[f"LT in weeks - {fg}", "Count of Part Number"]]
        for entry in fg_block.get("data", []):
            block.append([entry.get("lead_time_weeks", ""), entry.get("count_of_part_number", "")])
        horizontal_blocks.append(block)

    if not horizontal_blocks:
        return [["No FG Lead Time data found"]]

    max_rows = max(len(b) for b in horizontal_blocks)
    for block in horizontal_blocks:
        while len(block) < max_rows:
            block.append(["", ""])

    rows = []
    for row_index in range(max_rows):
        row = []
        for block in horizontal_blocks:
            lt, cnt = block[row_index]
            row.extend([lt, cnt, ""])
        rows.append(row)

    return rows


CBOM_TAB = "7.0 CBOM VL-1"
HELPER_COL = 60     # BH: helper columns sit far right on this tab, one row per CBOM part line, labelled "helper (do not edit)"
_PART_LINE_TEST = "AND({y}<>\"\",RIGHT({y},5)<>\"_PCBA\")"


def write_lead_time_formulas(ws, bounds):
    """Replaces the typed counts with live formulas over the CBOM VL-1 tab's part lines (bounds = (first, last), as the exporter computes them).

    Helper columns (BH..BK) hold, per CBOM part line: the assembly, the part, the lead time, and two first-occurrence flags:
      flag_lt   = 1 for the first line of each (assembly, part, lead time)   -> a part counts once per lead time (the Python rule);
      flag_part = 1 for the first line of each (assembly, part)              -> the grand total counts each part once.
    A bucket is then COUNTIFS(assembly = FG, flag_lt = 1, lead time = label)."""
    first, last = bounds
    n = last - first + 1
    h = HELPER_COL
    c_asm, c_part, c_lt, c_flt, c_fpart = (openpyxl_col(h + i) for i in range(5))
    ws.cell(row=1, column=h).value = "helper (do not edit): assembly"
    ws.cell(row=1, column=h + 1).value = "part"
    ws.cell(row=1, column=h + 2).value = "lead time"
    ws.cell(row=1, column=h + 3).value = "first (part, lead time)"
    ws.cell(row=1, column=h + 4).value = "first (part)"
    last_h = n + 1
    rng = lambda col: f"${col}$2:${col}${last_h}"  # noqa: E731
    for i in range(n):
        r = i + 2                      # helper row
        src = first + i                # CBOM tab row
        ws[f"{c_asm}{r}"] = f"='{CBOM_TAB}'!A{src}"
        ws[f"{c_part}{r}"] = f"='{CBOM_TAB}'!C{src}"
        ws[f"{c_lt}{r}"] = f"=IF('{CBOM_TAB}'!S{src}=\"\",\"\",'{CBOM_TAB}'!S{src})"
        test = _PART_LINE_TEST.format(y=f"{c_part}{r}")
        ws[f"{c_flt}{r}"] = (f"=IF({test},IF(COUNTIFS({c_asm}$2:{c_asm}{r},{c_asm}{r},{c_part}$2:{c_part}{r},{c_part}{r},"
                             f"{c_lt}$2:{c_lt}{r},{c_lt}{r})=1,1,0),0)")
        ws[f"{c_fpart}{r}"] = (f"=IF({test},IF(COUNTIFS({c_asm}$2:{c_asm}{r},{c_asm}{r},{c_part}$2:{c_part}{r},{c_part}{r})=1,1,0),0)")
    for col1 in range(1, ws.max_column + 1, 3):
        head = ws.cell(row=1, column=col1).value
        if not (isinstance(head, str) and head.startswith("LT in weeks - ")):
            continue
        fg = head[len("LT in weeks - "):].strip()
        col2 = col1 + 1
        lab = openpyxl_col(col1)
        for r in range(2, ws.max_row + 1):
            label = ws.cell(row=r, column=col1).value
            count = ws.cell(row=r, column=col2).value
            if label in (None, "") and count in (None, ""):
                continue
            if isinstance(label, str) and label.strip().lower() == "grand total":
                ws.cell(row=r, column=col2).value = f'=COUNTIFS({rng(c_asm)},"{fg}",{rng(c_fpart)},1)'
            else:
                crit = f"{lab}{r}" if label not in (None, "") else '""'
                ws.cell(row=r, column=col2).value = f'=COUNTIFS({rng(c_asm)},"{fg}",{rng(c_flt)},1,{rng(c_lt)},{crit})'


def openpyxl_col(c):
    from openpyxl.utils import get_column_letter
    return get_column_letter(c)


def build_lead_time_fg_sheet(wb, rows, cbom_bounds=None):
    """Port of FgLeadTimeExport::styles(): colors each 3-column group
    independently, using that group's own last non-blank row.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the flat 2D array from flatten_lead_time_fg().
    """
    ws = wb.create_sheet(title="Lead Time (FG Wise)")
    for row in rows:
        ws.append(row)
    if cbom_bounds:
        write_lead_time_formulas(ws, cbom_bounds)

    highest_row = len(rows)
    highest_col = max((len(r) for r in rows), default=0)

    def cell_str(r, c):
        row = rows[r - 1]
        value = row[c - 1] if c - 1 < len(row) else ""
        return "" if value is None else str(value).strip()

    for col1 in range(1, highest_col, 3):
        col2 = col1 + 1

        last_data_row = 1
        for r in range(2, highest_row + 1):
            if cell_str(r, col1) != "" or cell_str(r, col2) != "":
                last_data_row = r

        for c in (col1, col2):
            cell = ws.cell(row=1, column=c)
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT

        for r in range(2, last_data_row + 1):
            val, cnt = cell_str(r, col1), cell_str(r, col2)
            if val.lower() == "grand total":
                fill, font = _TOTAL_FILL, _TOTAL_FONT
            elif val != "" or cnt != "":
                fill, font = _DATA_FILL, None
            else:
                continue
            for c in (col1, col2):
                cell = ws.cell(row=r, column=c)
                cell.fill = fill
                if font is not None:
                    cell.font = font

        for r in range(1, last_data_row + 1):
            for c in (col1, col2):
                ws.cell(row=r, column=c).border = _THIN_BORDER

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "bom_details_json_data": [
            {"CPN": "CPN-1001", "FG": "ASSY-01"},
            {"CPN": "CPN-1002", "FG": "ASSY-01"},
            {"CPN": "CPN-1003", "FG": "ASSY-02"},
        ],
        "rfqs": [
            {"cpn": "CPN-1001", "is_L1": True, "lead_times": "8", "volume_no": 1},
            {"cpn": "CPN-1002", "is_L1": True, "lead_times": "8", "volume_no": 1},
            {"cpn": "CPN-1003", "is_L1": True, "lead_times": "12", "volume_no": 1},
        ],
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    blocks = lead_time_fg_blocks(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(blocks, indent=4))

    by_fg = {b["fg"]: b["data"] for b in blocks}
    assert by_fg["ASSY-01"][0] == {"lead_time_weeks": "8", "count_of_part_number": 2}
    assert by_fg["ASSY-01"][-1] == {"lead_time_weeks": "Grand Total", "count_of_part_number": 2}
    assert by_fg["ASSY-02"][-1] == {"lead_time_weeks": "Grand Total", "count_of_part_number": 1}
    print("lead_time_fg_blocks() self-check passed")

    rows = flatten_lead_time_fg(blocks)
    assert rows[0][:2] == ["LT in weeks - ASSY-01", "Count of Part Number"]
    assert rows[1][:2] == ["8", 2]
    print("flatten_lead_time_fg() self-check passed")

    empty_rows = flatten_lead_time_fg([])
    assert empty_rows == [["No FG Lead Time data found"]]
    print("flatten_lead_time_fg() empty-input self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    ws = build_lead_time_fg_sheet(wb, rows)

    assert ws.title == "Lead Time (FG Wise)"
    assert ws["A1"].fill.fgColor.rgb.endswith("2F5496")
    grand_total_row = next(
        r for r in range(1, ws.max_row + 1) if str(ws.cell(row=r, column=1).value).lower() == "grand total"
    )
    assert ws.cell(row=grand_total_row, column=1).fill.fgColor.rgb.endswith("FFD966")
    print("build_lead_time_fg_sheet() self-check passed")

    wb.save("Lead_Time_FG_Wise_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : Lead_Time_FG_Wise_Output.xlsx")


if __name__ == "__main__":
    _demo()
