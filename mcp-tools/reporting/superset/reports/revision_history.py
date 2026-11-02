"""Python port of the Revision History report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. revision_history_rows() — port of BlockthreeController::revision_history_json():
     computes the literal top-header/sub-header/data rows (Old vs. New
     revision comparison per CPN, per volume), matching the input/output
     JSON documented in revision-history-report.md. This is the exact shape
     persisted to revision_history_json.json_desc.
  2. build_revision_history_sheet() — port of app/Exports/RevisionHistoryExportExcelFormula.php:
     restructures the columns (moves the single input-level "EAU" column
     into a "V{n} EAU" column per volume), then overwrites every "New"-labeled
     and fixed-identity cell with a live formula referencing '7.0 CBOM VL-{v}'
     / 'Ex Inv VL-{v}' — same live-formula pattern as A Class Parts, CBOM VL,
     Ex Inv VL, PCB NRE & FAI Charge, and Mech & EM NRE. "OLD"-labeled cells
     and "In %" are left exactly as the literal values from step 1.

# ponytail: the shipped PHP inserts each "V{n} EAU" column into an
# already-written sheet (removing the old EAU column, then
# insertNewColumnBefore() one at a time, processed in descending
# qty-column order specifically to avoid shifting not-yet-processed insertion
# points). Since this port builds the final column layout directly instead of
# mutating a live sheet, that ordering dance — and the PHP's follow-up
# "rescan for the last Delta column" workaround needed because insertion left
# ambiguous trailing columns — aren't needed: the clean layout already ends
# each block at an unambiguous boundary.

# BUG FIXED (previously preserved as-is to match the shipped PHP, confirmed
# against a real generated workbook showing visible #VALUE! errors in "New
# System Price" cells): unlike every other injected formula, "New System
# Price" (= NewQtyCell * NewUnitPriceCell) had NO IFERROR wrapper in the
# shipped PHP (RevisionHistoryExportExcelFormula.php line 543). Qty/Unit
# Price both fall back to "" via their own IFERROR when the CPN isn't found
# on the Ex Inv/CBOM sheets, and "" * "" (or number * "") is a genuine
# #VALUE! error in Excel — visible directly in the cell, not suppressed.
# "Delta" already came out blank rather than erroring, since its own formula
# IS wrapped in IFERROR and caught the propagated error from a "New System
# Price" cell that was #VALUE! — now it just catches the ordinary "" case
# instead. Per this project's hard requirement that no generated formula may
# ever show #VALUE! on blank/null/non-numeric input, "New System Price" is
# now IFERROR-wrapped like every other injected formula, deviating from PHP
# parity on this one cell deliberately.

No DB access happens here — bom_data/rfqs are supplied by the caller, and
the DB write (`revision_history_json` table upsert) in the original PHP is
out of scope, consistent with every other port in this project.

v2 source schema note: today's `quote_win` table stores only the latest
quote per part -- no revision dimension at all, so this report's Old-vs-New
comparison cannot be produced from it. See
cbom-revision-history-redesign.md for the full design; the short version is
`rfqs_from_quote_win_revision()` below, which adapts a dedicated
`quote_win_revision` table (one row per revision) into the same 'rfqs' shape
revision_history_rows() already expects -- so the core function needs no
changes once real revision data exists. That adapter carries explicit,
flagged assumptions (see its docstring and
cbom-pending-client-clarifications.md) rather than guessing at fields the
given `quote_win_revision` DDL doesn't have -- most importantly, that DDL has
no volume_no column, so multi-volume revision history cannot be produced
correctly until one is added.
"""

import re

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from currency import convert_currency


def rfqs_from_quote_win_revision(revision_rows, commodity_by_cpn=None, volume_no=1):
    """v2 schema adapter: reshapes `quote_win_revision` rows (see
    cbom-revision-history-redesign.md) into the 'rfqs' shape
    revision_history_rows() already expects: cpn, MPN, revision_no, volume_no,
    vol_qty, vol_pricing, commodity, EAU, manufacturer_name, currency.

    Flagged assumptions -- Pending Client Clarification, see
    cbom-pending-client-clarifications.md -- not invented as confirmed logic:
      - `quote_win_revision` has no volume_no column in the DDL as given.
        Every adapted row is stamped with the same `volume_no` (default 1)
        until a real column is added; multi-volume revision history is NOT
        correct until then -- this is a hard dependency, not a workaround.
      - `supplier_name` is used as a stand-in for `manufacturer_name`. These
        are different concepts (the awarded supplier vs. the component
        manufacturer) and Revision History has always compared manufacturer,
        not supplier -- flagged, not silently treated as equivalent.
      - `corrected_mpn` is used as a stand-in for MPN; `quote_win_revision`
        has no separate base-MPN column.
      - `commodity` and `EAU` have no source column on `quote_win_revision`
        at all. Pass `commodity_by_cpn` (e.g. built from `scrub_bom_items`)
        to backfill commodity; EAU is left blank (`None`) rather than guessed.
    """
    commodity_by_cpn = commodity_by_cpn or {}
    out = []
    for row in revision_rows:
        cpn = row.get("part_number")
        out.append({
            "cpn": cpn,
            "MPN": row.get("corrected_mpn"),
            "revision_no": row.get("revision_no"),
            "volume_no": volume_no,
            "vol_qty": row.get("awarded_volume"),
            "vol_pricing": row.get("unit_price"),
            "commodity": commodity_by_cpn.get(cpn),
            "EAU": None,
            "manufacturer_name": row.get("supplier_name"),
            "currency": row.get("currency"),
        })
    return out

_VOLUME_HEADER_COLORS = {1: "74B2E6", 2: "F56767", 3: "75D975", 4: "AD92F8", 5: "FFE06D"}
_VOLUME_DATA_COLORS = {1: "D9EAF7", 2: "FDE2E2", 3: "E2F7E2", 4: "E9E2FD", 5: "FFF7D9"}
_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_FIXED_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_CENTER = Alignment(horizontal="center", vertical="center")


def _natural_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]


def revision_history_rows(payload):
    """Port of BlockthreeController::revision_history_json(): Old-vs-New revision rollup.

    payload: {"centum_id": ..., "bom_data": [{"CPN":..., "Assembly":..., "Description":..., "MPN":...}, ...],
        "rfqs": [{"cpn":..., "MPN":..., "revision_no":..., "volume_no":..., "vol_qty":...,
                  "vol_pricing":..., "commodity":..., "EAU":..., "manufacturer_name":..., "currency":...}, ...]}
    returns: 2D list — top-header row, sub-header row, then one row per CPN
        (in bom_data CPN order), matching revision_history_json.json_desc.
    """
    centum_id = payload.get("centum_id") or "-"
    bom_data = payload.get("bom_data", [])
    rfqs = payload.get("rfqs", [])

    rfqs_cpns = []
    seen_cpns = set()
    for entry in bom_data:
        cpn = entry.get("CPN")
        if cpn is not None and cpn not in seen_cpns:
            seen_cpns.add(cpn)
            rfqs_cpns.append(cpn)

    bom_by_cpn = {}
    for entry in bom_data:
        cpn = entry.get("CPN")
        if cpn is not None and cpn not in bom_by_cpn:
            bom_by_cpn[cpn] = entry

    rfqs_data = {}  # cpn -> revision_no -> volume_no -> {...}
    for row in rfqs:
        cpn, rev_no, vol_no = row.get("cpn"), row.get("revision_no"), row.get("volume_no")
        rfqs_data.setdefault(cpn, {}).setdefault(rev_no, {})[vol_no] = {
            "vol_qty": row.get("vol_qty"),
            "vol_pricing": row.get("vol_pricing"),
            "Commodity": row.get("commodity"),
            "Manufacturer": row.get("manufacturer_name"),
            "MPN": row.get("MPN"),
            "EAU": row.get("EAU"),
            "currency": row.get("currency"),
        }

    # Highest numbered volume, not the number of volumes: a CPN that only has volume 2 must
    # still get its V2 columns (a count gave 1 and dropped V2).
    max_volume = 0
    for revisions in rfqs_data.values():
        for volumes in revisions.values():
            for vol_no in volumes:
                if str(vol_no).isdigit():
                    max_volume = max(max_volume, int(vol_no))

    sub_headers = ["S. No", "Revision", "Assembly", "CPN", "Description", "Commodity", "Manufacturer", "MPN", "EAU"]
    for v in range(1, max_volume + 1):
        sub_headers += [f"V{v} OLD System QTY", f"V{v} New System QTY"]
    volume_start_col = 10
    for v in range(1, max_volume + 1):
        sub_headers += [f"V{v} OLD Unit Price in $", f"V{v} New Unit Price in $", "In %"]
    cost_per_product_start_col = 9 + 2 * max_volume + 1
    for v in range(1, max_volume + 1):
        sub_headers += [f"V{v} OLD System Price in $", f"V{v} New System Price in $", "Delta"]
    cost_per_volume_start_col = cost_per_product_start_col + 3 * max_volume
    sub_headers += ["CBOM Ref No", "Remarks"]

    top_headers = [""] * len(sub_headers)
    top_headers[volume_start_col - 1] = "Volume Quantity"
    top_headers[cost_per_product_start_col - 1] = "Cost per Product"
    top_headers[cost_per_volume_start_col - 1] = "Cost per Volume"

    rows = [top_headers, sub_headers]
    s_no = 1

    for cpn in rfqs_cpns:
        cpn_revisions = rfqs_data.get(cpn, {})
        bom_row = bom_by_cpn.get(cpn, {"Assembly": "-", "Description": "-", "MPN": "-"})

        rev_keys = sorted(cpn_revisions, key=_natural_key)
        # PHP quirk preserved: end()/prev() on an empty array yield `false`,
        # and `$lastRev ?? '-'` doesn't catch `false` (only `null`) — so a
        # CPN with zero RFQ revisions gets a literal `false` Revision cell,
        # not "-".
        last_rev = rev_keys[-1] if rev_keys else False
        second_last_rev = rev_keys[-2] if len(rev_keys) >= 2 else False

        last_data = dict(sorted(cpn_revisions.get(last_rev, {}).items())) if last_rev is not False else {}
        prev_data = dict(sorted(cpn_revisions.get(second_last_rev, {}).items())) if second_last_rev is not False else {}

        first_entry = next(iter(last_data.values()), {})
        row = [
            s_no, last_rev if last_rev is not None else "-",
            bom_row.get("Assembly", "-"), cpn, bom_row.get("Description", "-"),
            first_entry.get("Commodity", "-"), first_entry.get("Manufacturer", "-"),
            bom_row.get("MPN", "-"), first_entry.get("EAU", "-"),
        ]
        s_no += 1

        for v in range(1, max_volume + 1):
            old_qty = float(prev_data[v]["vol_qty"]) if prev_data.get(v, {}).get("vol_qty") is not None else "-"
            new_qty = float(last_data[v]["vol_qty"]) if last_data.get(v, {}).get("vol_qty") is not None else "-"
            row += [old_qty, new_qty]

        for v in range(1, max_volume + 1):
            old_price = "-"
            if v in prev_data and prev_data[v].get("vol_pricing") is not None:
                cur = prev_data[v].get("currency", "USD")
                converted = convert_currency(prev_data[v]["vol_pricing"], cur)
                old_price = f"{converted:.2f}"
            new_price = "-"
            if v in last_data and last_data[v].get("vol_pricing") is not None:
                cur = last_data[v].get("currency", "USD")
                converted = convert_currency(last_data[v]["vol_pricing"], cur)
                new_price = f"{converted:.2f}"
            row += [old_price, new_price, "-"]

        for v in range(1, max_volume + 1):
            old_qty_v = float(prev_data[v]["vol_qty"]) if prev_data.get(v, {}).get("vol_qty") is not None else None
            new_qty_v = float(last_data[v]["vol_qty"]) if last_data.get(v, {}).get("vol_qty") is not None else None

            old_price_v = None
            if v in prev_data:
                cur = prev_data[v].get("currency", "USD")
                base = prev_data[v].get("vol_pricing") or 0
                old_price_v = convert_currency(base, cur)

            new_price_v = None
            if v in last_data:
                cur = last_data[v].get("currency", "USD")
                base = last_data[v].get("vol_pricing") or 0
                new_price_v = convert_currency(base, cur)

            old_total = old_qty_v * old_price_v if old_qty_v is not None and old_price_v is not None else None
            new_total = new_qty_v * new_price_v if new_qty_v is not None and new_price_v is not None else None

            row.append(f"$ {old_total:,.2f}" if old_total is not None else "-")
            row.append(f"$ {new_total:,.2f}" if new_total is not None else "-")
            row.append(f"$ {new_total - old_total:,.2f}" if old_total is not None and new_total is not None else "-")

        row += [centum_id, "-"]
        rows.append(row)

    return rows


def _final_sub_headers(max_volume):
    headers = ["S. No", "Revision", "Assembly", "CPN", "Description", "Commodity", "Manufacturer", "MPN"]
    for v in range(1, max_volume + 1):
        headers += [f"V{v} OLD System QTY", f"V{v} New System QTY", f"V{v} EAU"]
    for v in range(1, max_volume + 1):
        headers += [f"V{v} OLD Unit Price in $", f"V{v} New Unit Price in $", "In %"]
    for v in range(1, max_volume + 1):
        headers += [f"V{v} OLD System Price in $", f"V{v} New System Price in $", "Delta"]
    headers += ["CBOM Ref No", "Remarks"]
    return headers


def _final_top_headers(max_volume):
    sub = _final_sub_headers(max_volume)
    top = [""] * len(sub)
    top[8] = "Volume Quantity"
    top[8 + 3 * max_volume] = "Cost per Product"
    top[8 + 6 * max_volume] = "Cost per Volume"
    return top


def _remap_data_row(orig_row, max_volume):
    """Drops the standalone EAU value; makes room for a per-volume EAU cell
    (filled in with a formula later) right after each volume's New Qty.
    """
    row = list(orig_row[:8])  # S.No..MPN — drop EAU at index 8
    orig_vol_start = 9
    for v in range(max_volume):
        row += [orig_row[orig_vol_start + 2 * v], orig_row[orig_vol_start + 2 * v + 1], ""]
    cost_product_start = 9 + 2 * max_volume
    row += orig_row[cost_product_start: cost_product_start + 3 * max_volume]
    cost_volume_start = cost_product_start + 3 * max_volume
    row += orig_row[cost_volume_start: cost_volume_start + 3 * max_volume]
    row += orig_row[cost_volume_start + 3 * max_volume:]  # CBOM Ref No, Remarks
    return row


def _cbom_range(v, col, cbom_bounds):
    """cbom_bounds: (first_data_row, last_data_row) for '7.0 CBOM VL-{v}', computed
    once in Python via cbom_vl.cbom_vl_bounds() instead of the two runtime probes this
    used to run per formula (MATCH("FG part number", $A:$A, 0)+1, itself correct, and
    MATCH(9.99999999999999E+307, $AX:$AX) -- $AX doesn't exist in cbom_vl.py's 49-column
    layout (A..AW), so that probe always failed and silently fell back to a hardcoded
    2000, a latent under-bound for any FG with more than 2000 CBOM VL rows. The real
    last-row value computed here fixes that as a side effect, not just a perf change.
    """
    sheet = f"7.0 CBOM VL-{v}"
    first_data_row, last_data_row = cbom_bounds
    return f"INDEX('{sheet}'!${col}:${col}, {first_data_row}):INDEX('{sheet}'!${col}:${col}, {last_data_row})"


def _identity_formula(v, target_col, asm_cell, cpn_cell, cbom_bounds):
    b = _cbom_range(v, "B", cbom_bounds)
    c = _cbom_range(v, "C", cbom_bounds)
    l = _cbom_range(v, "L", cbom_bounds)
    target = _cbom_range(v, target_col, cbom_bounds)
    base = f"INDEX({target}, MATCH(1, INDEX(({b}={asm_cell})*({c}={cpn_cell})*({l}>0),0),0))"
    fallback = f"INDEX({target}, MATCH(1, INDEX(({b}={asm_cell})*({c}={cpn_cell}),0),0))"
    return f'=IFERROR({base}, IFERROR({fallback}, ""))'


def _qty_eau_formula(v, cpn_cell, ex_inv_last_row):
    sheet = f"Ex Inv VL-{v}"
    return (
        f"=IFERROR(SUMIFS('{sheet}'!$G$5:$G${ex_inv_last_row}, "
        f"'{sheet}'!$A$5:$A${ex_inv_last_row}, {cpn_cell}), \"\")"
    )


def _unit_price_formula(v, asm_cell, cpn_cell, cbom_bounds):
    k = _cbom_range(v, "K", cbom_bounds)
    b = _cbom_range(v, "B", cbom_bounds)
    c = _cbom_range(v, "C", cbom_bounds)
    l = _cbom_range(v, "L", cbom_bounds)
    base = f"INDEX({k}, MATCH(1, INDEX(({b}={asm_cell})*({c}={cpn_cell})*({l}>0),0),0))"
    fallback = f"INDEX({k}, MATCH(1, INDEX(({b}={asm_cell})*({c}={cpn_cell}),0),0))"
    return f'=IFERROR({base}, IFERROR({fallback}, ""))'


def _volume_for_header(sub_headers, col_index):
    """Returns the volume number a column belongs to, for coloring purposes.

    Mirrors the PHP's regex checks plus its "look at the previous column"
    handling for 'In %' and 'Delta', which don't carry a volume number in
    their own label — only 'V{n} New Unit Price in $' / 'V{n} New System
    Price in $' immediately precede them, by construction.
    """
    header = sub_headers[col_index]
    m = re.match(r"^V(\d+)", header)
    if m:
        return int(m.group(1))
    if header in ("In %", "Delta") and col_index > 0:
        m = re.match(r"^V(\d+)", sub_headers[col_index - 1])
        if m:
            return int(m.group(1))
    return None


def build_revision_history_sheet(wb, rows, cbom_bounds_by_volume, ex_inv_row_counts):
    """Port of RevisionHistoryExportExcelFormula: writes and styles the
    'Revision History' sheet, restructuring EAU into a per-volume column and
    overwriting New/identity cells with live formulas.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the 2D list produced by revision_history_rows() (original layout,
        with the standalone EAU column).
    cbom_bounds_by_volume: {v: (first_data_row, last_data_row)} for every numeric
        volume's '7.0 CBOM VL-{v}' sheet -- computed early via
        cbom_vl.cbom_vl_bounds() before those sheets are actually built later in
        exporter.py. Required (no default): a missing entry should raise loudly
        rather than risk silently under-bounding a formula.
    ex_inv_row_counts: {"Ex Inv VL-{v}": last_row} for every 'Ex Inv VL-{v}' sheet,
        computed early via len(ex_inv_vl.ex_inv_vl_rows(...)).
    """
    max_volume = sum(1 for h in rows[1] if re.match(r"^V\d+ New System QTY$", h))
    sub_headers = _final_sub_headers(max_volume)
    top_headers = _final_top_headers(max_volume)
    data_rows = [_remap_data_row(r, max_volume) for r in rows[2:]]

    ws = wb.create_sheet(title="Revision History")
    ws.append(top_headers)
    ws.append(sub_headers)
    for row in data_rows:
        ws.append(row)

    last_col = len(sub_headers)
    last_row = 2 + len(data_rows)

    fixed_labels = {"S. No", "Revision", "Assembly", "CPN", "Description", "Commodity", "Manufacturer", "MPN",
                    "CBOM Ref No", "Remarks"}
    for col in range(1, last_col + 1):
        header = sub_headers[col - 1]
        cell = ws.cell(row=2, column=col)
        if header in fixed_labels:
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            data_fill = _FIXED_DATA_FILL
        else:
            v = _volume_for_header(sub_headers, col - 1)
            data_fill = None
            if v is not None:
                v_wrapped = (v - 1) % 5 + 1
                cell.fill = PatternFill("solid", fgColor=_VOLUME_HEADER_COLORS[v_wrapped])
                data_fill = PatternFill("solid", fgColor=_VOLUME_DATA_COLORS[v_wrapped])

        if data_fill is not None:
            for r in range(3, last_row + 1):
                ws.cell(row=r, column=col).fill = data_fill

    for col_idx, label in ((8, "Volume Quantity"), (8 + 3 * max_volume, "Cost per Product"),
                            (8 + 6 * max_volume, "Cost per Volume")):
        cell = ws.cell(row=1, column=col_idx + 1)
        cell.value = label
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _CENTER

    # Confirmed real-data bug (RFQ-000012): when this RFQ has zero rfqs rows (e.g.
    # QuoteWin never successfully ingested for this rfq_id), max_volume is 0, and
    # each of these ranges inverts (start_column 9 > end_column 8) -- openpyxl's
    # CellRange validation then raises "8 must be greater than 9" and aborts the
    # whole export. There is nothing to merge when there are no volume columns at
    # all, so skip -- matches ref_volume's own "max_volume >= 1" guard below.
    if max_volume >= 1:
        ws.merge_cells(start_row=1, start_column=9, end_row=1, end_column=8 + 3 * max_volume)
        ws.merge_cells(start_row=1, start_column=9 + 3 * max_volume, end_row=1, end_column=8 + 6 * max_volume)
        ws.merge_cells(start_row=1, start_column=9 + 6 * max_volume, end_row=1, end_column=8 + 9 * max_volume)

    idx = {name: i for i, name in enumerate(sub_headers)}
    assembly_col, cpn_col = idx["Assembly"] + 1, idx["CPN"] + 1
    # The reference volume is the lowest numbered volume that has CBOM bounds (not a hard-coded 1).
    volume_numbers = [int(m.group(1)) for h in rows[1] for m in [re.match(r"^V(\d+) New System QTY$", str(h))] if m]
    available_volumes = [v for v in volume_numbers if v in cbom_bounds_by_volume]
    ref_volume = min(available_volumes) if available_volumes else None

    for r in range(3, last_row + 1):
        asm_cell = f"{get_column_letter(assembly_col)}{r}"
        cpn_cell = f"{get_column_letter(cpn_col)}{r}"

        if ref_volume is not None:
            ref_cbom_bounds = cbom_bounds_by_volume[ref_volume]
            for label, col_key in (("Description", "D"), ("Commodity", "E"), ("Manufacturer", "F"), ("MPN", "G")):
                col = idx[label] + 1
                ws.cell(row=r, column=col, value=_identity_formula(ref_volume, col_key, asm_cell, cpn_cell, ref_cbom_bounds))

        for v in range(1, max_volume + 1):
            new_qty_col = idx[f"V{v} New System QTY"] + 1
            eau_col = idx[f"V{v} EAU"] + 1
            new_unit_col = idx[f"V{v} New Unit Price in $"] + 1
            new_sys_col = idx[f"V{v} New System Price in $"] + 1
            old_sys_col = idx[f"V{v} OLD System Price in $"] + 1

            # A volume with no CBOM/Ex Inv sheet (e.g. V1 for an RFQ that starts at volume 2) has
            # nothing to reference: its formula cells stay blank rather than pointing at a missing sheet.
            if v not in cbom_bounds_by_volume or f"Ex Inv VL-{v}" not in ex_inv_row_counts:
                continue
            ex_inv_last_row = ex_inv_row_counts[f"Ex Inv VL-{v}"]
            cbom_bounds = cbom_bounds_by_volume[v]
            new_qty_formula = _qty_eau_formula(v, cpn_cell, ex_inv_last_row)
            ws.cell(row=r, column=new_qty_col, value=new_qty_formula)
            ws.cell(row=r, column=eau_col, value=_qty_eau_formula(v, cpn_cell, ex_inv_last_row))
            ws.cell(row=r, column=new_unit_col, value=_unit_price_formula(v, asm_cell, cpn_cell, cbom_bounds))

            new_qty_cell = f"{get_column_letter(new_qty_col)}{r}"
            new_unit_cell = f"{get_column_letter(new_unit_col)}{r}"
            # IFERROR wrap added (deviates from the shipped PHP, which leaves this cell
            # unwrapped -- see module docstring): New Qty / New Unit Price both fall back
            # to "" via their own IFERROR whenever the CPN isn't found on the Ex Inv/CBOM
            # sheets, and ""*"" (or number*"") is a genuine #VALUE! in Excel, not 0 -- this
            # was visible directly in real generated workbooks. Fixed per the hard
            # requirement that no generated formula may ever show #VALUE! on blank/null/
            # non-numeric input; "" fallback keeps this a descriptive per-row cell that
            # stays blank rather than a numeric aggregate that should fall back to 0.
            ws.cell(row=r, column=new_sys_col, value=f'=IFERROR({new_qty_cell}*{new_unit_cell}, "")')

            new_sys_cell = f"{get_column_letter(new_sys_col)}{r}"
            old_sys_cell = f"{get_column_letter(old_sys_col)}{r}"
            delta_col = idx[f"V{v} New System Price in $"] + 2  # 'Delta' immediately follows New System Price
            ws.cell(
                row=r, column=delta_col,
                value=f'=IFERROR({new_sys_cell}-VALUE(SUBSTITUTE(SUBSTITUTE({old_sys_cell},"$",""),",","")),"")',
            )

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "centum_id": "CE-1234",
        "bom_data": [
            {"CPN": "CPN-1001", "Assembly": "ASSY-01", "Description": "Resistor 10k", "MPN": "MPN-ABC-123"},
        ],
        "rfqs": [
            {"cpn": "CPN-1001", "MPN": "MPN-ABC-123", "revision_no": "R1", "volume_no": 1,
             "vol_qty": 900, "vol_pricing": 150.0, "commodity": "Passive", "EAU": 1000,
             "manufacturer_name": "ACME", "currency": "USD"},
            {"cpn": "CPN-1001", "MPN": "MPN-ABC-123", "revision_no": "R2", "volume_no": 1,
             "vol_qty": 1000, "vol_pricing": 155.0, "commodity": "Passive", "EAU": 1000,
             "manufacturer_name": "ACME", "currency": "USD"},
        ],
    }

    print("\n========== INPUT ==========")
    print(json.dumps(payload, indent=4))

    rows = revision_history_rows(payload)

    print("\n========== OUTPUT ==========")
    print(json.dumps(rows, indent=4))

    assert rows[0][9] == "Volume Quantity" and rows[0][11] == "Cost per Product" and rows[0][14] == "Cost per Volume"
    assert rows[1][:9] == ["S. No", "Revision", "Assembly", "CPN", "Description", "Commodity", "Manufacturer", "MPN", "EAU"]
    assert len(rows[1]) == 19  # 9 fixed + 2 + 3 + 3 + 2, for max_volume=1
    data_row = rows[2]
    assert data_row[1] == "R2"  # last (natural-sorted) revision
    assert data_row[9] == 900.0 and data_row[10] == 1000.0  # OLD/New Qty
    assert data_row[14] == "$ 135,000.00" and data_row[15] == "$ 155,000.00" and data_row[16] == "$ 20,000.00"
    print("revision_history_rows() self-check passed")

    empty_row_payload = {"centum_id": "-", "bom_data": [{"CPN": "CPN-9999", "Assembly": "-", "Description": "-", "MPN": "-"}], "rfqs": []}
    empty_rows = revision_history_rows(empty_row_payload)
    assert empty_rows[2][1] is False  # preserved PHP quirk: no revisions -> literal `false`, not "-"
    print("revision_history_rows() no-RFQ-revision quirk self-check passed")

    # v2 schema self-check: quote_win_revision rows adapt into the same
    # 'rfqs' shape used above, so revision_history_rows() runs unmodified.
    revision_rows = [
        {"part_number": "CPN-1001", "revision_no": "R1", "corrected_mpn": "MPN-ABC-123",
         "unit_price": 150.0, "awarded_volume": 900, "currency": "USD", "supplier_name": "Acme Corp"},
        {"part_number": "CPN-1001", "revision_no": "R2", "corrected_mpn": "MPN-ABC-123",
         "unit_price": 155.0, "awarded_volume": 1000, "currency": "USD", "supplier_name": "Acme Corp"},
    ]
    adapted_rfqs = rfqs_from_quote_win_revision(revision_rows, commodity_by_cpn={"CPN-1001": "Passive"})
    adapted_rows = revision_history_rows({
        "centum_id": "CE-1234",
        "bom_data": payload["bom_data"],
        "rfqs": adapted_rfqs,
    })
    assert adapted_rows[2][1] == "R2" and adapted_rows[2][5] == "Passive"
    print("rfqs_from_quote_win_revision() self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    cbom_bounds_by_volume = {1: (18, 500)}
    ex_inv_row_counts = {"Ex Inv VL-1": 200}
    ws = build_revision_history_sheet(wb, rows, cbom_bounds_by_volume, ex_inv_row_counts)

    assert ws.title == "Revision History"
    assert ws.cell(row=2, column=8).value == "MPN"  # standalone EAU column is gone
    assert ws.cell(row=2, column=9).value == "V1 OLD System QTY"
    assert ws.cell(row=2, column=10).value == "V1 New System QTY"
    assert ws.cell(row=2, column=11).value == "V1 EAU"  # inserted right after "V1 New System QTY"
    formula = ws.cell(row=3, column=5).value  # Description
    assert formula.startswith("=IFERROR(INDEX(") and "7.0 CBOM VL-1" in formula
    qty_formula = ws.cell(row=3, column=10).value  # V1 New System QTY
    assert "Ex Inv VL-1" in qty_formula
    assert ws.cell(row=3, column=11).value == qty_formula  # EAU formula identical to Qty (see module docstring)
    print("build_revision_history_sheet() self-check passed")

    # Column layout for max_volume=1 (1-based): ...11=V1 EAU, 12=V1 OLD Unit
    # Price, 13=V1 New Unit Price, 14=In %, 15=V1 OLD System Price,
    # 16=V1 New System Price, 17=Delta, 18=CBOM Ref No, 19=Remarks.
    final_headers = _final_sub_headers(1)
    assert final_headers[15] == "V1 New System Price in $" and final_headers[16] == "Delta"

    # New System Price (col 16) must be IFERROR-wrapped — fixes the shipped
    # #VALUE! bug (confirmed against a real generated workbook) per this
    # project's hard requirement that no generated formula may ever show
    # #VALUE! on blank/null/non-numeric input.
    new_sys_price_formula = ws.cell(row=3, column=16).value
    assert new_sys_price_formula.startswith('=IFERROR(') and new_sys_price_formula.endswith(', "")')
    delta_formula = ws.cell(row=3, column=17).value
    assert delta_formula.startswith("=IFERROR(")
    print("New System Price #VALUE! bug fix self-check passed")

    # "In %" (col 14) and "Delta" (col 17) must be colored to match their
    # volume, same as every other cell in that volume's block.
    in_pct_header_fill = ws.cell(row=2, column=14).fill.fgColor.rgb
    unit_price_header_fill = ws.cell(row=2, column=13).fill.fgColor.rgb  # "V1 New Unit Price in $"
    assert in_pct_header_fill == unit_price_header_fill
    delta_data_fill = ws.cell(row=3, column=17).fill.fgColor.rgb
    new_sys_data_fill = ws.cell(row=3, column=16).fill.fgColor.rgb  # "V1 New System Price in $"
    assert delta_data_fill == new_sys_data_fill
    print("'In %'/'Delta' volume-coloring self-check passed")

    wb.save("Revision_History_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : Revision_History_Output.xlsx")


if __name__ == "__main__":
    _demo()
