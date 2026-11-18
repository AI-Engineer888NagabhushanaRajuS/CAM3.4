"""Python port of BlockthreeController::sum_and_count_detail() (Laravel PHP).

Pure transform: takes the upstream JSON payload described in
sum_and_count_detailed.md and returns the output payload described there too.

Also includes build_sum_and_count_detailed_sheet(), a port of the Laravel
SumAndCountDetailedExportExcelFormula export: given that same output
payload, it writes a "Sum & Count Detailed" worksheet whose cells hold
live Excel formulas (matching the original) rather than static values.
Those formulas look up raw CBOM sheets ('7.0 CBOM Proto', '7.0 CBOM
VL-{n}') that must exist elsewhere in the same workbook — this module
does not evaluate them.
"""

import re

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


def _to_float(value):
    """Mirror PHP's forgiving (float) cast: non-numeric -> 0.0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sum_and_count_detail(payload):
    """Per-Assembly + CPN breakdown.

    Proto/VL-n columns are unconditionally set equal to each row's own
    Scrub Bom Sum/Count — the original PHP never checks RFQ presence at
    row level, so Is Sum Same / Is Count Same always come out "True".
    This is a known quirk of the source logic, preserved here as-is.

    payload: {"scrub_bom_items": [...], "rfqs": [...]}
    returns: list of row dicts, one per unique (Assembly, CPN) pair.
    """
    items = payload.get("scrub_bom_items", [])
    rfqs = payload.get("rfqs", [])

    assembly_groups = {}
    for item in items:
        assembly = item.get("Assembly")
        cpn = item.get("CPN")
        # Same rule as sum_and_count.py: a row without a quantity is not part of the BOM sum.
        if not assembly or not cpn or item.get("Quantity") is None:
            continue
        cpn_groups = assembly_groups.setdefault(assembly, {})
        cpn_groups.setdefault(cpn, []).append(item)

    # proto-first ordering -- see sum_and_count.py's identical sort key for why a plain
    # sorted() would misorder "proto" (lexicographically last, not first).
    unique_volumes = sorted(
        {rfq.get("volume_no") for rfq in rfqs if rfq.get("volume_no") is not None},
        key=lambda v: (0, 0) if str(v).lower() == "proto" else (1, int(v)),
    )
    volume_labels = [f"VL-{v}" for v in unique_volumes]

    rows = []
    for assembly, cpn_groups in assembly_groups.items():
        for cpn, group_items in cpn_groups.items():
            # A repeated CPN under one assembly sums every row, as the summary does.
            qty = sum(_to_float(item["Quantity"]) for item in group_items)
            count = len(group_items)

            row = {
                "Assembly": assembly,
                "CPN": cpn,
                "Scrub Bom Sum": qty,
                "Scrub Bom Count": count,
                "Proto Sum": qty,
                "Proto Count": count,
            }

            sum_same = [qty]
            count_same = [count]

            for label in volume_labels:
                row[f"{label} Sum"] = qty
                row[f"{label} Count"] = count
                sum_same.append(qty)
                count_same.append(count)

            row["Is Sum Same"] = "True" if len(set(sum_same)) == 1 else "False"
            row["Is Count Same"] = "True" if len(set(count_same)) == 1 else "False"

            rows.append(row)

    return rows


def _header_meta(headers):
    """Column metadata (label, index, letter) for non-empty string headers."""
    return [
        {"label": label, "index": i, "column": get_column_letter(i + 1)}
        for i, label in enumerate(headers)
        if isinstance(label, str) and label != ""
    ]


def _resolve_meta(header_meta, candidates):
    """First header meta matching any candidate label, in candidate order."""
    for candidate in candidates:
        for meta in header_meta:
            if meta["label"] == candidate:
                return meta
    return None


def _sheet_name_for_volume(label):
    normalized = label.strip().lower()
    if normalized in ("proto", "prototype"):
        return "7.0 CBOM Proto"
    return f"7.0 CBOM VL-{label.strip()}"


def _collect_volume_columns(header_meta):
    """Detect 'VL-{n} Sum'/'VL-{n} Count' column pairs and their raw sheet."""
    volumes = []
    for meta in header_meta:
        match = re.match(r"^VL-(.+) Sum$", meta["label"], re.IGNORECASE)
        if not match:
            continue
        label = match.group(1).strip()
        volumes.append({
            "label": label,
            "sheet_name": _sheet_name_for_volume(label),
            "sum_meta": meta,
            "count_meta": _resolve_meta(header_meta, [f"VL-{label} Count"]),
        })
    return volumes


def _consistency_formula(columns_meta, row_number):
    """=AND(a=b, b=c, ...) chaining consecutive columns on the same row."""
    columns_meta = [c for c in columns_meta if c]
    if len(columns_meta) < 2:
        return None
    comparisons = [
        f"{columns_meta[i]['column']}{row_number}={columns_meta[i + 1]['column']}{row_number}"
        for i in range(len(columns_meta) - 1)
    ]
    return "=AND(" + ", ".join(comparisons) + ")" if comparisons else None


def _quote_sheet(name):
    return "'" + name.replace("'", "''") + "'"


_START_ROW_REF = "$AL$1"
_END_ROW_REF = "$AK$1"

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_DATA_FONT = Font(color="000000")
# Explicit 8-digit ARGB (not a bare 6-digit RGB string) -- openpyxl otherwise defaults
# the alpha channel to 00 (fully transparent) for a conditional-formatting dxf fill,
# which renders as invisible in Excel even though the color is technically "set".
_MISMATCH_FILL = PatternFill("solid", fgColor="FFFF0000")


def _bounded_range(sheet_name, column_letter):
    """Dynamic range on a raw CBOM sheet, bounded by the shared AL1/AK1 helper cells."""
    sheet = _quote_sheet(sheet_name)
    return (
        f"INDEX({sheet}!${column_letter}:${column_letter}, {_START_ROW_REF})"
        f":INDEX({sheet}!${column_letter}:${column_letter}, {_END_ROW_REF})"
    )


def _average_formula(sheet_name, assembly_meta, part_meta, row_number):
    avg_range = _bounded_range(sheet_name, "I")
    assembly_range = _bounded_range(sheet_name, "B")
    part_range = _bounded_range(sheet_name, "C")
    assembly_cell = f"{assembly_meta['column']}{row_number}"
    part_cell = f"{part_meta['column']}{row_number}"
    return (
        f"=IFERROR(AVERAGEIFS({avg_range}, {assembly_range}, {assembly_cell}, "
        f"{part_range}, {part_cell}), 0)"
    )


def _count_formula(sheet_name, assembly_meta, part_meta, row_number):
    assembly_range = _bounded_range(sheet_name, "B")
    part_range = _bounded_range(sheet_name, "C")
    assembly_cell = f"{assembly_meta['column']}{row_number}"
    part_cell = f"{part_meta['column']}{row_number}"
    # COUNTIFS, not an array product: LibreOffice returns #VALUE!/#REF! for the array form, and COUNTIFS is
    # native to Excel 2007+. CPNs hold no wildcard or operator characters, so the match is the same.
    return f"=IF(COUNTIFS({assembly_range}, {assembly_cell}, {part_range}, {part_cell}) > 0, 1, 0)"


def build_sum_and_count_detailed_sheet(wb, rows, cbom_bounds, include_proto=True):
    """Port of SumAndCountDetailedExportExcelFormula: live-formula sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts produced by sum_and_count_detail().
    cbom_bounds: (first_data_row, last_data_row) for '7.0 CBOM VL-1', computed
        once in Python via cbom_vl.cbom_vl_bounds() -- the exact same values the
        AL1/AK1 cells below used to compute at Excel runtime via
        MATCH("Part Number", $C:$C, 0)+1 / LOOKUP(2, 1/($C:$C<>""), ROW($C:$C)),
        both full-column scans. Required (no default): a missing/wrong value here
        should raise loudly rather than risk silently under-bounding every formula
        on this sheet (they all key off _bounded_range(), itself keyed off AL1/AK1).
    include_proto: replaces resolveIncludeProto($bomId) — see
        sum_and_count.py's build_sum_and_count_sheet() for why this is
        now an explicit parameter instead of a DB lookup.

    Proto/VL-n cells become AVERAGEIFS/COUNT formulas against raw CBOM
    sheets ('7.0 CBOM Proto', '7.0 CBOM VL-{n}') that must exist
    elsewhere in the same workbook, bounded by helper cells written to
    AL1/AK1 (then hidden). Is Sum Same/Is Count Same become AND()
    formulas over this sheet's own columns. Rows are sorted so
    mismatches come first, exactly as the original PHP does.
    """
    display_rows = [dict(row) for row in rows]
    if not include_proto:
        for row in display_rows:
            row.pop("Proto Sum", None)
            row.pop("Proto Count", None)

    def sort_key(row):
        both_true = (
            str(row.get("Is Sum Same", "")).upper() == "TRUE"
            and str(row.get("Is Count Same", "")).upper() == "TRUE"
        )
        return 1 if both_true else 0

    display_rows.sort(key=sort_key)

    ws = wb.create_sheet(title="Sum & Count Detailed")
    if not display_rows:
        return ws

    headers = list(display_rows[0].keys())
    ws.append(headers)
    for row in display_rows:
        ws.append(list(row.values()))

    header_meta = _header_meta(headers)
    assembly_meta = _resolve_meta(header_meta, ["Assembly", "FG (Assembly)"])
    part_meta = _resolve_meta(header_meta, ["Part Number", "CPN", "Part Number ID", "Mfg Part Number"])
    scrub_sum_meta = _resolve_meta(header_meta, ["Scrub Bom Sum"])
    scrub_count_meta = _resolve_meta(header_meta, ["Scrub Bom Count"])
    proto_sum_meta = _resolve_meta(header_meta, ["Proto Sum"])
    proto_count_meta = _resolve_meta(header_meta, ["Proto Count"])
    is_sum_same_meta = _resolve_meta(header_meta, ["Is Sum Same"])
    is_count_same_meta = _resolve_meta(header_meta, ["Is Count Same"])
    volume_columns = _collect_volume_columns(header_meta)

    sum_metas = [m for m in [scrub_sum_meta, proto_sum_meta] + [v["sum_meta"] for v in volume_columns] if m]
    count_metas = [m for m in [scrub_count_meta, proto_count_meta] + [v["count_meta"] for v in volume_columns] if m]

    for row_number in range(2, len(display_rows) + 2):
        if assembly_meta and part_meta:
            if proto_sum_meta:
                ws.cell(row=row_number, column=proto_sum_meta["index"] + 1).value = _average_formula(
                    "7.0 CBOM Proto", assembly_meta, part_meta, row_number
                )
            if proto_count_meta:
                ws.cell(row=row_number, column=proto_count_meta["index"] + 1).value = _count_formula(
                    "7.0 CBOM Proto", assembly_meta, part_meta, row_number
                )
            for volume in volume_columns:
                if volume["sum_meta"]:
                    ws.cell(row=row_number, column=volume["sum_meta"]["index"] + 1).value = _average_formula(
                        volume["sheet_name"], assembly_meta, part_meta, row_number
                    )
                if volume["count_meta"]:
                    ws.cell(row=row_number, column=volume["count_meta"]["index"] + 1).value = _count_formula(
                        volume["sheet_name"], assembly_meta, part_meta, row_number
                    )

        if is_sum_same_meta and len(sum_metas) >= 2:
            ws.cell(row=row_number, column=is_sum_same_meta["index"] + 1).value = _consistency_formula(
                sum_metas, row_number
            )
        if is_count_same_meta and len(count_metas) >= 2:
            ws.cell(row=row_number, column=is_count_same_meta["index"] + 1).value = _consistency_formula(
                count_metas, row_number
            )

    last_row = len(display_rows) + 1
    last_col_letter = get_column_letter(len(headers))

    for row_cells in ws[f"A1:{last_col_letter}1"]:
        for cell in row_cells:
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT

    if last_row >= 2:
        data_range = f"A2:{last_col_letter}{last_row}"
        for row_cells in ws[data_range]:
            for cell in row_cells:
                cell.font = _DATA_FONT

        if is_sum_same_meta and is_count_same_meta:
            formula = (
                f"=NOT(AND(${is_sum_same_meta['column']}2=TRUE, "
                f"${is_count_same_meta['column']}2=TRUE))"
            )
            ws.conditional_formatting.add(data_range, FormulaRule(formula=[formula], fill=_MISMATCH_FILL))

    # ponytail: no native auto-size in openpyxl; approximate from content length
    for col_index, header in enumerate(headers, start=1):
        letter = get_column_letter(col_index)
        max_len = len(str(header))
        for row in display_rows:
            max_len = max(max_len, len(str(list(row.values())[col_index - 1])))
        ws.column_dimensions[letter].width = max_len + 2

    first_data_row, last_data_row = cbom_bounds
    ws["AL1"] = first_data_row
    ws["AK1"] = last_data_row
    ws.column_dimensions["AL"].hidden = True
    ws.column_dimensions["AK"].hidden = True

    return ws


def _demo():
    payload = {
        "bom_upload_id": 123,
        "scrub_bom_items": [
            {"Assembly": "ASSY-001", "CPN": "CPN-1001", "Quantity": 10},
            {"Assembly": "ASSY-001", "CPN": "CPN-1002", "Quantity": 5},
        ],
        "rfqs": [
            {"cpn": "CPN-1001", "volume_no": 1},
            {"cpn": "CPN-1001", "volume_no": 2},
        ],
    }

    expected = [
        {
            "Assembly": "ASSY-001",
            "CPN": "CPN-1001",
            "Scrub Bom Sum": 10.0,
            "Scrub Bom Count": 1,
            "Proto Sum": 10.0,
            "Proto Count": 1,
            "VL-1 Sum": 10.0,
            "VL-1 Count": 1,
            "VL-2 Sum": 10.0,
            "VL-2 Count": 1,
            "Is Sum Same": "True",
            "Is Count Same": "True",
        },
        {
            "Assembly": "ASSY-001",
            "CPN": "CPN-1002",
            "Scrub Bom Sum": 5.0,
            "Scrub Bom Count": 1,
            "Proto Sum": 5.0,
            "Proto Count": 1,
            "VL-1 Sum": 5.0,
            "VL-1 Count": 1,
            "VL-2 Sum": 5.0,
            "VL-2 Count": 1,
            "Is Sum Same": "True",
            "Is Count Same": "True",
        },
    ]

    result = sum_and_count_detail(payload)
    assert result == expected, f"unexpected output: {result}"
    print("sum_and_count_detail self-check passed")

    from openpyxl import Workbook

    # sum_and_count_detail() always produces "True"/"True" rows (documented
    # quirk); fake one mismatched row here purely to exercise the sheet
    # builder's sort behaviour.
    mismatched_row = dict(result[0])
    mismatched_row["Is Sum Same"] = "False"
    sheet_rows = [result[1], mismatched_row]

    wb = Workbook()
    ws = build_sum_and_count_detailed_sheet(wb, sheet_rows, cbom_bounds=(18, 500), include_proto=True)

    assert ws.title == "Sum & Count Detailed"
    num_headers = len(expected[0])
    header_row = [ws.cell(row=1, column=i).value for i in range(1, num_headers + 1)]
    assert header_row == list(expected[0].keys()), header_row

    # Mismatched row must sort before the all-True row.
    assert ws.cell(row=2, column=2).value == "CPN-1001"  # mismatched_row's CPN
    assert ws.cell(row=3, column=2).value == "CPN-1002"  # result[1]'s CPN

    # Proto Sum (col E) for row 2 -> AVERAGEIFS against '7.0 CBOM Proto'.
    assert ws.cell(row=2, column=5).value == (
        "=IFERROR(AVERAGEIFS("
        "INDEX('7.0 CBOM Proto'!$I:$I, $AL$1):INDEX('7.0 CBOM Proto'!$I:$I, $AK$1), "
        "INDEX('7.0 CBOM Proto'!$B:$B, $AL$1):INDEX('7.0 CBOM Proto'!$B:$B, $AK$1), A2, "
        "INDEX('7.0 CBOM Proto'!$C:$C, $AL$1):INDEX('7.0 CBOM Proto'!$C:$C, $AK$1), B2), 0)"
    )

    # AL1/AK1 are now literal ints computed in Python (see cbom_vl.cbom_vl_bounds()),
    # not runtime MATCH/LOOKUP full-column scans.
    assert ws["AL1"].value == 18 and ws["AK1"].value == 500
    assert ws.column_dimensions["AL"].hidden is True
    assert ws.column_dimensions["AK"].hidden is True
    assert len(list(ws.conditional_formatting)) == 1
    print("build_sum_and_count_detailed_sheet self-check passed")


if __name__ == "__main__":
    _demo()
