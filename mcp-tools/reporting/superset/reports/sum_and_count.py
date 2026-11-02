"""Python port of BlockthreeController::sum_and_count() (Laravel PHP).

Pure transform: takes the upstream JSON payload described in
sum_and_count.md and returns the output payload described there too.

Also includes build_sum_and_count_sheet(), a port of the Laravel
SumAndCountExportExcelFormula export: given that same output payload,
it writes a "Sum & Count" worksheet whose cells hold live Excel
formulas (matching the original) rather than static values. Those
formulas only resolve correctly once opened in Excel alongside a
'Sum & Count Detailed' sheet built the same way (see
sum_and_count_detailed.py) — this module does not evaluate them.
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


def sum_and_count(payload):
    """Per-Assembly rollup of scrub BOM sum/count vs Proto/volume RFQ coverage.

    payload: {"scrub_bom_items": [...], "rfqs": [...]}
    returns: list of row dicts, one per unique Assembly.
    """
    items = payload.get("scrub_bom_items", [])
    rfqs = payload.get("rfqs", [])

    groups = {}
    for item in items:
        assembly = item.get("Assembly")
        cpn = item.get("CPN")
        if not assembly or not cpn or item.get("Quantity") is None:
            continue
        groups.setdefault(assembly, []).append(item)

    # proto-first ordering (matches Summary/BOM Matrix's own volume-column ordering) --
    # volume_no values are now homogeneous strings ("proto", "1", "2", ...); a plain
    # sorted() would put "proto" last (lexicographic, 'p' > any digit).
    unique_volumes = sorted(
        {rfq.get("volume_no") for rfq in rfqs if rfq.get("volume_no") is not None},
        key=lambda v: (0, 0) if str(v).lower() == "proto" else (1, int(v)),
    )

    rows = []
    for assembly, group_items in groups.items():
        scrub_cpns = {item["CPN"] for item in group_items}
        scrub_sum = sum(_to_float(item["Quantity"]) for item in group_items)
        scrub_count = len(group_items)

        has_proto = any(
            str(rfq.get("volume_no")).lower() == "proto" and rfq.get("cpn") in scrub_cpns for rfq in rfqs
        )
        proto_sum = scrub_sum if has_proto else 0
        proto_count = scrub_count if has_proto else 0

        row = {
            "Assembly": assembly,
            "Scrub Bom Sum": scrub_sum,
            "Scrub Bom Count": scrub_count,
            "Proto Sum": proto_sum,
            "Proto Count": proto_count,
        }

        sum_values = [scrub_sum, proto_sum]
        count_values = [scrub_count, proto_count]

        for v in unique_volumes:
            has_volume = any(
                str(rfq.get("volume_no")) == str(v) and rfq.get("cpn") in scrub_cpns
                for rfq in rfqs
            )
            vol_sum = scrub_sum if has_volume else 0
            vol_count = scrub_count if has_volume else 0

            row[f"VL-{v} Sum"] = vol_sum
            row[f"VL-{v} Count"] = vol_count

            sum_values.append(vol_sum)
            count_values.append(vol_count)

        row["Is Sum Same"] = len(set(sum_values)) == 1
        row["Is Count Same"] = len(set(count_values)) == 1

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


def _collect_volume_columns(header_meta):
    """Detect 'VL-{n} Sum'/'VL-{n} Count' column pairs from the header."""
    volumes = []
    for meta in header_meta:
        match = re.match(r"^VL-(.+) Sum$", meta["label"], re.IGNORECASE)
        if not match:
            continue
        label = match.group(1).strip()
        volumes.append({
            "label": label,
            "sum_meta": meta,
            "count_meta": _resolve_meta(header_meta, [f"VL-{label} Count"]),
        })
    return volumes


def _build_detailed_column_map(volume_columns, include_proto):
    """Column letters as they appear (positionally) on the Detailed sheet."""
    column_map = {}
    column_index = 1

    primary_columns = [
        ["Assembly", "FG (Assembly)", "FG", "Assembly Name"],
        ["CPN", "Part Number", "Part Number ID", "Mfg Part Number"],
        ["Scrub Bom Sum"],
        ["Scrub Bom Count"],
    ]
    if include_proto:
        primary_columns += [["Proto Sum"], ["Proto Count"]]

    for aliases in primary_columns:
        letter = get_column_letter(column_index)
        column_index += 1
        for alias in aliases:
            column_map[alias] = letter

    for volume in volume_columns:
        sum_letter = get_column_letter(column_index)
        column_index += 1
        count_letter = get_column_letter(column_index)
        column_index += 1
        column_map[f"VL-{volume['label']} Sum"] = sum_letter
        column_map[f"VL-{volume['label']} Count"] = count_letter

    column_map["Is Sum Same"] = get_column_letter(column_index)
    column_index += 1
    column_map["Is Count Same"] = get_column_letter(column_index)

    return column_map


def _detailed_column_range(column_map, candidates, detailed_last_row):
    for candidate in candidates:
        if candidate in column_map:
            col = column_map[candidate]
            return f"'Sum & Count Detailed'!${col}$1:${col}${detailed_last_row}"
    return None


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


_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_DATA_FONT = Font(color="000000")
# Explicit 8-digit ARGB (not a bare 6-digit RGB string) -- openpyxl otherwise defaults
# the alpha channel to 00 (fully transparent) for a conditional-formatting dxf fill,
# which renders as invisible in Excel even though the color is technically "set".
_MISMATCH_FILL = PatternFill("solid", fgColor="FFFF0000")


def build_sum_and_count_sheet(wb, rows, detailed_last_row, include_proto=True):
    """Port of SumAndCountExportExcelFormula: live-formula 'Sum & Count' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the list of dicts produced by sum_and_count().
    detailed_last_row: last row of the 'Sum & Count Detailed' sheet this workbook
        will contain -- computed early via len(sum_and_count_detailed.sum_and_count_detail(...))
        (before that sheet is actually built later in exporter.py) so this sheet's
        SUMIFS formulas can be bounded instead of scanning full columns.
    include_proto: replaces resolveIncludeProto($bomId) — the caller
        supplies the same true/false that PHP derived from
        bom_details.proto, since DB access is out of scope here.

    Every Sum/Count cell is overwritten with a SUMIFS formula that
    re-derives the value from the 'Sum & Count Detailed' sheet, and
    Is Sum Same/Is Count Same become AND() formulas over this sheet's
    own columns — exactly as the original PHP does. Rows are sorted so
    mismatches (Is Sum Same/Is Count Same not both true) come first.
    """
    display_rows = [dict(row) for row in rows]
    if not include_proto:
        for row in display_rows:
            row.pop("Proto Sum", None)
            row.pop("Proto Count", None)

    def sort_key(row):
        both_true = row.get("Is Sum Same") is True and row.get("Is Count Same") is True
        return 1 if both_true else 0

    display_rows.sort(key=sort_key)

    ws = wb.create_sheet(title="Sum & Count")
    if not display_rows:
        return ws

    headers = list(display_rows[0].keys())
    ws.append(headers)
    for row in display_rows:
        ws.append(list(row.values()))

    header_meta = _header_meta(headers)
    assembly_meta = _resolve_meta(header_meta, ["Assembly", "FG (Assembly)", "FG"])
    scrub_sum_meta = _resolve_meta(header_meta, ["Scrub Bom Sum"])
    scrub_count_meta = _resolve_meta(header_meta, ["Scrub Bom Count"])
    proto_sum_meta = _resolve_meta(header_meta, ["Proto Sum"])
    proto_count_meta = _resolve_meta(header_meta, ["Proto Count"])
    is_sum_same_meta = _resolve_meta(header_meta, ["Is Sum Same"])
    is_count_same_meta = _resolve_meta(header_meta, ["Is Count Same"])
    volume_columns = _collect_volume_columns(header_meta)
    column_map = _build_detailed_column_map(volume_columns, include_proto)

    aggregate_metas = [scrub_sum_meta, scrub_count_meta, proto_sum_meta, proto_count_meta]
    for volume in volume_columns:
        aggregate_metas += [volume["sum_meta"], volume["count_meta"]]

    sum_metas = [m for m in [scrub_sum_meta, proto_sum_meta] + [v["sum_meta"] for v in volume_columns] if m]
    count_metas = [m for m in [scrub_count_meta, proto_count_meta] + [v["count_meta"] for v in volume_columns] if m]

    assembly_range = _detailed_column_range(
        column_map, ["Assembly", "FG (Assembly)", "FG", "Assembly Name"], detailed_last_row
    )

    for row_number in range(2, len(display_rows) + 2):
        if assembly_meta and assembly_range:
            assembly_cell = f"{assembly_meta['column']}{row_number}"
            for meta in aggregate_metas:
                if not meta:
                    continue
                value_range = _detailed_column_range(column_map, [meta["label"]], detailed_last_row)
                if not value_range:
                    continue
                formula = f"=IFERROR(SUMIFS({value_range}, {assembly_range}, {assembly_cell}), 0)"
                ws.cell(row=row_number, column=meta["index"] + 1).value = formula

        if is_sum_same_meta and len(sum_metas) >= 2:
            ws.cell(row=row_number, column=is_sum_same_meta["index"] + 1).value = (
                _consistency_formula(sum_metas, row_number)
            )
        if is_count_same_meta and len(count_metas) >= 2:
            ws.cell(row=row_number, column=is_count_same_meta["index"] + 1).value = (
                _consistency_formula(count_metas, row_number)
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
                cell.fill = _DATA_FILL
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

    return ws


def _demo():
    payload = {
        "bom_upload_id": 123,
        "scrub_bom_items": [
            {"Assembly": "ASSY-001", "CPN": "CPN-1001", "Quantity": 10},
            {"Assembly": "ASSY-001", "CPN": "CPN-1002", "Quantity": 5},
            {"Assembly": "ASSY-002", "CPN": "CPN-2001", "Quantity": 20},
        ],
        "rfqs": [
            {"cpn": "CPN-1001", "volume_no": 1},
            {"cpn": "CPN-1001", "volume_no": 2},
        ],
    }

    expected = [
        {
            "Assembly": "ASSY-001",
            "Scrub Bom Sum": 15.0,
            "Scrub Bom Count": 2,
            "Proto Sum": 15.0,
            "Proto Count": 2,
            "VL-1 Sum": 15.0,
            "VL-1 Count": 2,
            "VL-2 Sum": 15.0,
            "VL-2 Count": 2,
            "Is Sum Same": True,
            "Is Count Same": True,
        },
        {
            "Assembly": "ASSY-002",
            "Scrub Bom Sum": 20.0,
            "Scrub Bom Count": 1,
            "Proto Sum": 0,
            "Proto Count": 0,
            "VL-1 Sum": 0,
            "VL-1 Count": 0,
            "VL-2 Sum": 0,
            "VL-2 Count": 0,
            "Is Sum Same": False,
            "Is Count Same": False,
        },
    ]

    result = sum_and_count(payload)
    assert result == expected, f"unexpected output: {result}"
    print("sum_and_count self-check passed")

    from openpyxl import Workbook

    wb = Workbook()
    ws = build_sum_and_count_sheet(wb, result, detailed_last_row=50, include_proto=True)

    assert ws.title == "Sum & Count"
    header_row = [c.value for c in ws[1]]
    assert header_row == list(expected[0].keys()), header_row

    # Mismatched row (ASSY-002) must sort before the all-True row (ASSY-001).
    assert ws.cell(row=2, column=1).value == "ASSY-002"
    assert ws.cell(row=3, column=1).value == "ASSY-001"

    # Scrub Bom Sum (col B) for row 2 -> SUMIFS against the Detailed sheet's
    # Scrub Bom Sum column (C), filtered by this row's Assembly (col A).
    assert ws.cell(row=2, column=2).value == (
        "=IFERROR(SUMIFS('Sum & Count Detailed'!$C$1:$C$50, "
        "'Sum & Count Detailed'!$A$1:$A$50, A2), 0)"
    )

    # Is Sum Same (col J) for row 2 -> AND() chain over this sheet's own
    # Scrub/Proto/VL-n sum columns (B, D, F, H).
    assert ws.cell(row=2, column=10).value == "=AND(B2=D2, D2=F2, F2=H2)"

    assert len(list(ws.conditional_formatting)) == 1
    print("build_sum_and_count_sheet self-check passed")


if __name__ == "__main__":
    _demo()
