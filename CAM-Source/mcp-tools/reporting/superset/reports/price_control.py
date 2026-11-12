"""Python port of the Price Control report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. price_control() — port of PriceControlController::processPriceControl():
     buckets parts into Centum/Customer at the single last quoted volume,
     matching the input/output JSON documented in price_control.md.
  2. build_price_control_sheet() — port of app/Exports/PriceControlExportExcelFormula.php:
     writes a 'Price Control' worksheet whose cells hold live SUMPRODUCT formulas
     against the '7.0 CBOM VL-{last_volume}' sheet, rather than the static bucket sums.

No DB access happens here — rfqs/fgcounts/bom_data are supplied by the caller,
and the DB write (`price_controls` table upsert) in the original PHP is out of
scope, consistent with every other port in this project.

v2 source schema note: the finalized DB has no `fgcounts` table. The FG-level
volume-quantity multiplier this report needs now lives in the `volume` table
(columns: fg, volume_name, batch_qty -- where `batch_qty` is that table's own
misleading name for Volume Qty/EAU, not a batch quantity; see
cbom-database-schema-design.md). price_control()'s own logic is unchanged --
only the shape feeding it changes, so this file adds an adapter
(fgcounts_from_volume_rows) rather than touching price_control() itself.
"""

import re

from openpyxl.styles import Border, Font, PatternFill, Side

from currency import convert_currency


def fgcounts_from_volume_rows(volume_rows):
    """v2 schema adapter: `volume` table rows (fg, volume_name, batch_qty) ->
    the 'fgcounts' shape price_control() already expects (fg, volume_no, count).

    volume.batch_qty is aliased to 'count' here -- it holds Volume Qty/EAU
    despite the column name (see the naming-collision warning in
    cbom-database-schema-design.md); don't confuse it with the separate
    `batch` table, which holds a real batch quantity under the same column
    name. Assumes volume_name follows the 'V{n}' convention seen in every
    example row given -- rows that don't match are skipped rather than guessed.
    """
    out = []
    for row in volume_rows:
        match = re.match(r"V(\d+)$", str(row.get("volume_name", "")).strip(), re.IGNORECASE)
        if not match:
            continue
        out.append({"fg": row.get("fg"), "volume_no": int(match.group(1)), "count": row.get("batch_qty")})
    return out


def _vol_num(volume_no):
    """Numeric volume for ordering and matching. "proto" (and any non-numeric label) is 0,
    below every numbered volume, so a prototype row can never be taken as the last volume."""
    try:
        return int(volume_no)
    except (TypeError, ValueError):
        return 0


def price_control(payload):
    """Port of PriceControlController::processPriceControl().

    payload: {"rfqs": [...], "fgcounts": [...], "bom_data": [...]}
        (rfqs must already be filtered to is_L1 = true)
    returns: {"Centum": {...}, "Customer": {...}, "GrandTotal": {...}, "meta": {...}}
    """
    rfqs = payload.get("rfqs", [])
    fgcounts = payload.get("fgcounts", [])
    bom_data = payload.get("bom_data", [])

    vols = [_vol_num(r["volume_no"]) for r in rfqs if r.get("volume_no")]
    last_volume = max(vols) if vols else None

    if not last_volume or last_volume <= 0:
        return {
            "Centum": {"sum_ext_price": 0.0, "sum_ext_vol_cost": 0.0, "in_percent": 0},
            "Customer": {"sum_ext_price": 0.0, "sum_ext_vol_cost": 0.0, "in_percent": 0},
            "GrandTotal": {"sum_ext_price": 0.0, "sum_ext_vol_cost": 0.0},
        }

    # FGCount::where(...)->groupBy('fg') then ->first() per group -> first occurrence per fg.
    fg_count_by_fg = {}
    for r in fgcounts:
        if _vol_num(r.get("volume_no")) == last_volume:
            fg_count_by_fg.setdefault(r.get("fg"), r)

    # BomData grouped by FG||Assembly||CPN -> each group's rows (only CPN matters here).
    bom_groups = {}
    for row in bom_data:
        if not row.get("CPN"):
            continue
        key = f"{row.get('FG', '')}||{row.get('Assembly', '')}||{row.get('CPN', '')}"
        bom_groups.setdefault(key, []).append(row)

    # RFQ::where(...)->keyBy('cpn') -> LAST occurrence wins for duplicate cpns.
    rfq_by_cpn = {}
    for r in rfqs:
        if _vol_num(r.get("volume_no")) == last_volume:
            rfq_by_cpn[r.get("cpn")] = r

    buckets = {
        "Centum": {"sum_ext_price": 0.0, "sum_ext_vol_cost": 0.0},
        "Customer": {"sum_ext_price": 0.0, "sum_ext_vol_cost": 0.0},
    }

    for key, rows in bom_groups.items():
        fg, _assembly, cpn = key.split("||", 2)

        part_qty = 0.0
        for row in rows:
            if row.get("CPN") == cpn:
                part_qty = float(row.get("Quantity") or 0)
                break
        if part_qty <= 0:
            continue

        rfq = rfq_by_cpn.get(cpn)
        if not rfq:
            continue

        price_control_raw = str(rfq.get("price_control") or "").strip()
        # CNP and CUSTOMER are one bucket, matching the sheet's CNP row (SUMPRODUCT over both).
        bucket = "Customer" if price_control_raw.lower() in ("customer", "cnp") else "Centum"

        fg_count_row = fg_count_by_fg.get(fg)
        vol_qty = float(fg_count_row.get("count") or 0) if fg_count_row else 0.0
        if vol_qty < 0:
            vol_qty = 0.0

        currency = str(rfq.get("currency") or "USD")
        vol_pricing = float(rfq.get("vol_pricing") or 0)
        price_conv = convert_currency(vol_pricing, currency)

        cbom_cost = part_qty * price_conv
        ext_part_vol_price_conv = price_conv * part_qty * vol_qty

        buckets[bucket]["sum_ext_price"] += cbom_cost
        buckets[bucket]["sum_ext_vol_cost"] += ext_part_vol_price_conv

    centum_sum = buckets["Centum"]
    customer_sum = buckets["Customer"]
    centum_percent = (
        round((centum_sum["sum_ext_price"] / centum_sum["sum_ext_vol_cost"]) * 100, 2)
        if centum_sum["sum_ext_vol_cost"] != 0.0 else 0
    )
    customer_percent = (
        round((customer_sum["sum_ext_price"] / customer_sum["sum_ext_vol_cost"]) * 100, 2)
        if customer_sum["sum_ext_vol_cost"] != 0.0 else 0
    )

    return {
        "Centum": {
            "sum_ext_price": centum_sum["sum_ext_price"],
            "sum_ext_vol_cost": centum_sum["sum_ext_vol_cost"],
            "in_percent": centum_percent,
        },
        "Customer": {
            "sum_ext_price": customer_sum["sum_ext_price"],
            "sum_ext_vol_cost": customer_sum["sum_ext_vol_cost"],
            "in_percent": customer_percent,
        },
        "GrandTotal": {
            "sum_ext_price": centum_sum["sum_ext_price"] + customer_sum["sum_ext_price"],
            "sum_ext_vol_cost": centum_sum["sum_ext_vol_cost"] + customer_sum["sum_ext_vol_cost"],
        },
        "meta": {"last_volume": last_volume},
    }


_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)
_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_DATA_FONT = Font(color="000000")
_GRAND_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")


def build_price_control_sheet(wb, data, cbom_last_row, last_volume=None, contract_names=None):
    """Port of PriceControlExportExcelFormula: live-formula 'Price Control' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    data: the dict produced by price_control().
    cbom_last_row: last data row of the '7.0 CBOM VL-{n}' sheet this sheet's
        formulas reference -- the same (first_data_row, last_data_row)[1] value
        computed once in Python via cbom_vl.cbom_vl_bounds() and already threaded
        into every other sheet builder that references that sheet (see
        aclass_parts.py/sum_and_count_detailed.py/ex_inv_vl.py), so this sheet's
        SUMPRODUCT formulas scan a bounded range instead of the full
        1,048,576-row column -- see Test_fixes/EXCEL_LOAD_PERFORMANCE.md. Required
        (no default): a missing/wrong value here should raise loudly rather than
        risk silently under-bounding every formula on this sheet.
    last_volume: overrides data['meta']['last_volume'] (matches the constructor's
        optional param); clamped to >=1. Defaults to data['meta']['last_volume'] or 1.
    contract_names: list of discovered contract-name strings (matches
        CBOMWorkbookExport::extractContractNames() — out of scope to compute here,
        pass them in if you have them).
    """
    contract_names = contract_names or []
    resolved_last_volume = int(last_volume if last_volume is not None else data.get("meta", {}).get("last_volume", 1))
    if resolved_last_volume < 1:
        resolved_last_volume = 1

    has_grand_total = "GrandTotal" in data
    sheet_name = f"7.0 CBOM VL-{resolved_last_volume}"

    # Bounded to the sheet's actual last data row, not a full 1,048,576-row column --
    # a full-column SUMPRODUCT here was one of the most expensive formula shapes in
    # the workbook and a major contributor to Excel appearing frozen/unresponsive on
    # open (see Test_fixes/EXCEL_LOAD_PERFORMANCE.md). >=1 guard: a bound of 0 (the
    # "no assembly-block data at all" case from cbom_vl_bounds()) would produce an
    # invalid $1:$0 range.
    bound_row = max(int(cbom_last_row), 1)
    pc_range = f"'{sheet_name}'!$W$1:$W${bound_row}"
    is_data_range = f"'{sheet_name}'!$AF$1:$AF${bound_row}"
    ext_price_range = f"'{sheet_name}'!$N$1:$N${bound_row}"
    ext_vol_range = f"'{sheet_name}'!$O$1:$O${bound_row}"
    # Direct boolean comparison, not UPPER(TRIM(...))="TRUE" -- this column is
    # TRUE/blank for real data rows (only the repeating block header rows hold
    # the literal text "Is Data"), so routing it through text-coercion
    # functions across a million-row array is unnecessary and was producing
    # #VALUE! in practice; a direct =TRUE comparison is equivalent for every
    # value actually present here (TRUE stays TRUE; "Is Data" and blank both
    # correctly evaluate to FALSE) without the text coercion.
    is_data_expr = f"{is_data_range}=TRUE"
    pc_upper = f"UPPER(TRIM({pc_range}))"

    rows = [["Price Control", "Sum of Ext Price (Splits) #1 (Conv.)", "Sum of Ext Vol Cost (Splits) #1", "In %"]]

    # N(range) coerces each whole-column reference to numbers (blank/text "" cells -> 0)
    # before SUMPRODUCT multiplies it against the boolean arrays -- without it, SUMPRODUCT
    # errors with #VALUE! the instant ANY row anywhere in that column holds text (which it
    # always will: header/spacer rows, or any real data row whose price/qty inputs were
    # left blank upstream), not just when THIS bucket's own matching rows are blank. A
    # blanket IFERROR(...,0) around the whole SUMPRODUCT would "fix" the symptom but
    # silently zero out a real, correct total the instant any unrelated row elsewhere had
    # a blank price -- N() fixes the actual cause instead (same pattern as cbom_vl.py).
    # CORRECTION (checked in native Excel 16.0, 11 Nov): N(range) is NOT array-wise in Excel (it returns the first cell only), so SUMPRODUCT got
    # arrays of different sizes and every cell of this tab was #VALUE! (the Manifest then read NO-GO); LibreOffice and the formula engine
    # accept it, which is why it was never seen. The plain range as its own SUMPRODUCT argument already treats text cells as 0 in Excel, which
    # is all the comment above wanted from N().
    ext_price_n = ext_price_range
    ext_vol_n = ext_vol_range

    rows.append([
        "Centum",
        f'=SUMPRODUCT(--({pc_upper}="CENTUM"),--({is_data_expr}),{ext_price_n})',
        f'=SUMPRODUCT(--({pc_upper}="CENTUM"),--({is_data_expr}),{ext_vol_n})',
        "",
    ])
    rows.append([
        "CNP",
        f'=SUMPRODUCT(--(({pc_upper}="CNP")+({pc_upper}="CUSTOMER")),--({is_data_expr}),{ext_price_n})',
        f'=SUMPRODUCT(--(({pc_upper}="CNP")+({pc_upper}="CUSTOMER")),--({is_data_expr}),{ext_vol_n})',
        "",
    ])
    for contract_name in contract_names:
        upper_name = str(contract_name).strip().upper()
        if not upper_name:
            continue
        upper_name = upper_name.replace('"', '""')
        rows.append([
            contract_name,
            f'=SUMPRODUCT(--({pc_upper}="{upper_name}"),--({is_data_expr}),{ext_price_n})',
            f'=SUMPRODUCT(--({pc_upper}="{upper_name}"),--({is_data_expr}),{ext_vol_n})',
            "",
        ])

    if has_grand_total:
        data_row_end = len(rows)
        rows.append(["Grand Total", f"=SUM(B2:B{data_row_end})", f"=SUM(C2:C{data_row_end})", ""])
        grand_total_row_number = len(rows)
        for excel_row in range(2, grand_total_row_number):
            rows[excel_row - 1][3] = f"=IF($C${grand_total_row_number}=0,0,C{excel_row}/$C${grand_total_row_number})"

    ws = wb.create_sheet(title="Price Control")
    for row in rows:
        ws.append(row)

    row_count = len(rows)

    for r in range(1, row_count + 1):
        for c in range(1, 5):
            ws.cell(row=r, column=c).border = _THIN_BORDER

    for c in range(1, 5):
        cell = ws.cell(row=1, column=c)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL

    if row_count > 2:
        for r in range(2, row_count):
            for c in range(1, 5):
                cell = ws.cell(row=r, column=c)
                cell.font = _DATA_FONT
                cell.fill = _DATA_FILL

    if has_grand_total:
        for c in range(1, 5):
            cell = ws.cell(row=row_count, column=c)
            cell.font = _DATA_FONT
            cell.fill = _GRAND_TOTAL_FILL

    last_data_row = row_count - (1 if has_grand_total else 0)
    format_end_row = row_count if has_grand_total else last_data_row
    for r in range(2, format_end_row + 1):
        for c in (2, 3):
            ws.cell(row=r, column=c).number_format = '"$"#,##0.0000'  # exactly 4 decimal places
    if last_data_row > 1:
        for r in range(2, last_data_row + 1):
            ws.cell(row=r, column=4).number_format = "0.00%"

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "rfqs": [
            {
                "cpn": "CPN-3001",
                "is_L1": True,
                "volume_no": 2,
                "price_control": "Customer",
                "currency": "USD",
                "vol_pricing": 1.50
            },
            {
                "cpn": "CPN-3002",
                "is_L1": True,
                "volume_no": 2,
                "price_control": "Centum",
                "currency": "USD",
                "vol_pricing": 0.80
            }
        ],
        "fgcounts": [
            {
                "fg": "ASSY-01",
                "volume_no": 2,
                "count": 100
            }
        ],
        "bom_data": [
            {
                "CPN": "CPN-3001",
                "FG": "ASSY-01",
                "Assembly": "ASSY-01",
                "Quantity": 10
            },
            {
                "CPN": "CPN-3002",
                "FG": "ASSY-01",
                "Assembly": "ASSY-01",
                "Quantity": 5
            }
        ]
    }

    # v2 schema self-check: the `volume` table shape adapts cleanly to the
    # 'fgcounts' shape price_control() already expects, so the demo payload's
    # own fgcounts list can be produced from it directly.
    volume_rows = [{"fg": "ASSY-01", "volume_name": "V2", "batch_qty": 100}]
    assert fgcounts_from_volume_rows(volume_rows) == payload["fgcounts"]
    print("fgcounts_from_volume_rows() self-check passed")

    print("\n========== INPUT ==========\n")
    print(json.dumps(payload, indent=4))

    result = price_control(payload)

    print("\n========== OUTPUT ==========\n")
    print(json.dumps(result, indent=4))

    wb = Workbook()

    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    build_price_control_sheet(
        wb,
        result,
        cbom_last_row=100,  # demo-only stand-in; the real caller passes cbom_vl_bounds()[1]
        contract_names=["Acme Direct"]
    )

    output_file = "Price_Control_Output.xlsx"
    wb.save(output_file)

    print("\n===================================")
    print("Price Control report generated.")
    print(f"Excel File : {output_file}")
    print("===================================")


if __name__ == "__main__":
    _demo()
