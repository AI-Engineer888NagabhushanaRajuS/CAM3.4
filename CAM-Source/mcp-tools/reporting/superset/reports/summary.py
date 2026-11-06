"""Python port of the Summary report (Laravel PHP), live-pipeline version.

Two layers, mirroring the live PHP pipeline:
  1. summary() — port of Tab8Context + Tab8Computer::computeRevisionPartial() +
     Tab8Merger::mergeAndPersist(), collapsed into a single non-chunked pass
     (the original splits CPNs into chunks of 200 for parallel queue processing
     purely for performance; a single Python process can compute the whole
     revision in one pass with mathematically identical results — chunking then
     merging is associative/commutative with computing the full set directly).
     Matches the input/output JSON documented in summary.md.
  2. build_summary_sheet() — port of app/Exports/SummaryExportExcelFormula.php:
     writes a 'Summary' worksheet whose last-revision cells hold live formulas
     referencing '7.0 CBOM VL-{n}'/'Ex Inv VL-{n}' sheets, rather than the
     static JSON values.

No DB access happens here — bom_data/rfqs/fgcounts/proto_qty/centum_id are
supplied by the caller, and the DB write (`summary_json` table upsert) in the
original PHP is out of scope, consistent with every other port in this project.

v2 source schema notes:
  - No `fgcounts` table in the finalized DB -- the FG-level volume-quantity
    multiplier now lives in the `volume` table (fg, volume_name, batch_qty --
    that column is Volume Qty/EAU despite its name, see
    cbom-database-schema-design.md). summary()'s own logic is unchanged; use
    fgcounts_from_volume_rows() (same adapter as price_control.py) to reshape
    `volume` rows before calling summary().
  - `quote_win` (the flat, current-quote-only table) has no revision_no
    column at all. summary()'s existing fallback -- `rev = 0 if
    r.get("revision_no") is None else int(...)` -- already degrades
    correctly: feed it rfqs rows with no `revision_no` key and it produces
    exactly one revision block (revision_no=0) instead of erroring or
    guessing. No code change was needed here for that gap; once a real
    revision-tracked source exists (see cbom-revision-history-redesign.md),
    populating `revision_no` on the adapted rows is enough to get multiple
    revision blocks back, again with no change to this function.
"""

import math
import re
from datetime import datetime

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from currency import convert_currency
from scrap_factor import get_scrap_factor_table


def fgcounts_from_volume_rows(volume_rows):
    """v2 schema adapter: `volume` table rows (fg, volume_name, batch_qty) ->
    the 'fgcounts' shape summary() already expects (fg, volume_no, count).
    Identical to price_control.py's adapter of the same name -- duplicated
    rather than imported, consistent with every other module in this project
    being a standalone, dependency-free file.
    """
    out = []
    for row in volume_rows:
        match = re.match(r"V(\d+)$", str(row.get("volume_name", "")).strip(), re.IGNORECASE)
        if not match:
            continue
        out.append({"fg": row.get("fg"), "volume_no": int(match.group(1)), "count": row.get("batch_qty")})
    return out


def _is_numeric(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except ValueError:
            return False
    return False


def _price_conv(price, currency):
    return round(convert_currency(price, currency), 4)


def _scrap_percent(price_conv):
    """Scrap percentage for this MOQ-cost calculation's own unit price -- sourced from
    the same logic_db.scrap_factor_settings table as everywhere else in this pipeline
    (queries.py's cbom columns, the CBOM VL-1 sheet's own live formulas -- see
    scrap_factor.py), not hardcoded thresholds/percentages.

    Unlike scrap_factor.classify_price() (used where "not eligible" should mean "no
    class assigned at all"), this ALWAYS returns a numeric percent -- the MOQ-cost math
    below (net_excess_cost, etc.) has no null-handling for a missing scrap percent, and
    price_conv here can legitimately be 0.0 (an RFQ with no real pricing data, defaulted
    via rfq.get(..., 0.0)) -- the lowest configured tier's own percentage is the
    fallback for a non-positive price, matching this function's pre-existing behavior
    (previously a hardcoded `ELSE 0.05`).
    """
    tiers = sorted(get_scrap_factor_table(), key=lambda t: t["min_price"], reverse=True)
    for tier in tiers:
        if price_conv >= tier["min_price"]:
            return tier["scrap_percent"]
    return tiers[-1]["scrap_percent"] if tiers else 0.0


def _first_where_volume(entries, vol_no):
    """vol_no=None means 'proto'. Falls back to entries[0] if nothing matches
    (a real quirk in the original — 'proto' pricing can end up borrowed from a
    non-proto entry when no true proto RFQ row exists for that CPN)."""
    for e in entries:
        if vol_no is None and not e.get("volume_no"):
            return e
        if vol_no is not None and e.get("volume_no") == vol_no:
            return e
    return entries[0] if entries else None


def summary(payload):
    """Port of the live Tab 8 pipeline (Tab8Context + Tab8Computer + Tab8Merger).

    payload: {
        "centum_id": str, "proto_qty": number,
        "bom_data": [{"FG","Assembly","CPN","Quantity","inventory_stock"}, ...],
        "rfqs": [{"cpn","revision_no","volume_no","currency","proto_pricing",
                  "vol_pricing","package_qty","vol_moq","vol_qty"}, ...],
        "fgcounts": [{"fg","volume_no","count"}, ...],
    }
    returns: list of per-revision dicts (see summary.md), sorted revision 0
        first then ascending.
    """
    centum_id = payload.get("centum_id") or "CENTUM-ID"
    proto_qty_global = float(payload.get("proto_qty") or 0)
    bom_data = payload.get("bom_data", [])
    rfqs = payload.get("rfqs", [])
    fgcounts = payload.get("fgcounts", [])

    # --- context (Tab8Context) ---
    by_cpn = {}
    inv_by_cpn = {}
    part_qty_by_key = {}
    for r in bom_data:
        cpn = str(r.get("CPN", ""))
        key = f"{r.get('FG', '')}|{r.get('Assembly', '')}|{cpn}"
        by_cpn.setdefault(cpn, []).append({
            "FG": r.get("FG", ""),
            "Assembly": r.get("Assembly", ""),
            "Quantity": float(r["Quantity"]) if _is_numeric(r.get("Quantity")) else 0.0,
            "inventory_stock": float(r["inventory_stock"]) if _is_numeric(r.get("inventory_stock")) else None,
        })
        if key not in part_qty_by_key:
            part_qty_by_key[key] = float(r["Quantity"]) if _is_numeric(r.get("Quantity")) else 0.0
        if cpn not in inv_by_cpn and _is_numeric(r.get("inventory_stock")):
            inv_by_cpn[cpn] = float(r["inventory_stock"])

    rfq_by_cpn_vol = {}
    rfq_by_cpn_rev = {}
    volume_nos_set = set()
    for r in rfqs:
        cpn = str(r.get("cpn", ""))
        rev = 0 if r.get("revision_no") is None else int(r["revision_no"])
        vol_no = int(r["volume_no"]) if r.get("volume_no") else None
        entry = {
            "volume_no": vol_no,
            "currency": r.get("currency") or "USD",
            "proto_pricing": float(r["proto_pricing"]) if _is_numeric(r.get("proto_pricing")) else 0.0,
            "vol_pricing": float(r["vol_pricing"]) if _is_numeric(r.get("vol_pricing")) else 0.0,
            "package_qty": float(r["package_qty"]) if _is_numeric(r.get("package_qty")) else 0.0,
            "vol_moq": float(r["vol_moq"]) if _is_numeric(r.get("vol_moq")) else 0.0,
            "vol_qty": float(r["vol_qty"]) if _is_numeric(r.get("vol_qty")) else 0.0,
        }
        rfq_by_cpn_rev.setdefault(rev, {}).setdefault(cpn, []).append(entry)
        if vol_no is not None:
            rfq_by_cpn_vol[f"{rev}|{cpn}|{vol_no}"] = entry
            volume_nos_set.add(vol_no)
        else:
            rfq_by_cpn_vol[f"{rev}|{cpn}|proto"] = entry

    volume_nos = sorted(volume_nos_set)

    fg_vol_count = {}
    for r in fgcounts:
        fg_vol_count[f"{r.get('fg')}|{int(r.get('volume_no') or 0)}"] = float(r.get("count") or 0)

    revisions = sorted(rfq_by_cpn_rev.keys(), key=lambda r: (r is None, r if r is not None else 0))

    return [
        _compute_revision(
            rev, rfq_by_cpn_rev, by_cpn, inv_by_cpn, part_qty_by_key, rfq_by_cpn_vol,
            volume_nos, fg_vol_count, centum_id, proto_qty_global,
        )
        for rev in revisions
    ]


def _compute_revision(rev, rfq_by_cpn_rev, by_cpn, inv_by_cpn, part_qty_by_key, rfq_by_cpn_vol,
                       volume_nos, fg_vol_count, centum_id, proto_qty_global):
    rev_entries_by_cpn = rfq_by_cpn_rev.get(rev, {})

    total_moq_costs = {"proto": 0.0}
    for v in volume_nos:
        total_moq_costs[v] = 0.0

    # 1) Precompute MOQ costs (net-excess/scrap-factor math, same family as BOM Matrix).
    for cpn in rev_entries_by_cpn:
        entries = by_cpn.get(cpn, [])
        if not entries:
            continue
        inventory_stock = inv_by_cpn.get(cpn, 0.0)

        for vol in ["proto"] + list(volume_nos):
            lookup_key = f"{rev}|{cpn}|proto" if vol == "proto" else f"{rev}|{cpn}|{vol}"
            rfq = rfq_by_cpn_vol.get(lookup_key)
            if not rfq:
                continue

            price = rfq.get("proto_pricing", 0.0) if vol == "proto" else rfq.get("vol_pricing", 0.0)
            price_conv = _price_conv(price, rfq.get("currency", "USD"))

            # NOTE: 'proto_qty' is never set on an RFQ entry (see docstring/md)
            # so this is always 0.0 for vol == 'proto' — a preserved quirk.
            ext_vol_qty = rfq.get("proto_qty", 0.0) if vol == "proto" else rfq.get("vol_qty", 0.0)
            moq = 0.0 if vol == "proto" else rfq.get("vol_moq", 0.0)
            package = max(1.0, rfq.get("package_qty", 1.0))

            scrap_percent = _scrap_percent(price_conv)
            shortage_qty = ext_vol_qty - inventory_stock if ext_vol_qty > inventory_stock else 0.0
            scrap_factor = shortage_qty * (1 + scrap_percent)
            excess_after_current = inventory_stock - ext_vol_qty if inventory_stock > ext_vol_qty else 0.0

            floor = 0.0 if vol == "proto" else moq
            net_order_qty = floor if scrap_factor <= floor else math.ceil(scrap_factor / package) * package

            net_excess_qty = net_order_qty + excess_after_current - scrap_factor
            net_excess_cost = abs(round(net_excess_qty * price_conv, 4))

            key = "proto" if vol == "proto" else vol
            total_moq_costs[key] += net_excess_cost

    # 2) Build per-FG rollup (cost + ext_part_vol_price_conv).
    summary_grouped = {}
    for cpn, entries in rev_entries_by_cpn.items():
        rows = by_cpn.get(cpn, [])
        if not rows:
            continue

        combinations = {}
        for row in rows:
            key = f"{row['FG']}|{row['Assembly']}|{cpn}"
            if key not in combinations:
                combinations[key] = {
                    "FG": row["FG"],
                    "partQty": part_qty_by_key.get(key, 1.0),
                }

        for key, info in combinations.items():
            fg = info["FG"]
            part_qty = info["partQty"]

            summary_grouped.setdefault(fg, {})

            # Proto
            rfq_proto = _first_where_volume(entries, None) or {}
            proto_pricing = _price_conv(rfq_proto.get("proto_pricing", 0.0), rfq_proto.get("currency", "USD"))

            ext_vol_qty = part_qty * proto_qty_global
            ext_price_conv = part_qty * proto_pricing
            ext_part_vol_price_conv = (ext_price_conv * ext_vol_qty) / part_qty if part_qty > 0.0 else 0.0

            proto_row = summary_grouped[fg].setdefault("proto", {
                "volume": "proto", "vol_qty": 0.0, "vol_pricing": 0.0,
                "ext_part_vol_price_conv": 0.0, "MOQ_cost": 0.0, "cbom_cost": 0.0,
            })
            proto_row["vol_pricing"] += proto_pricing
            proto_row["ext_part_vol_price_conv"] += ext_part_vol_price_conv
            proto_row["cbom_cost"] += ext_price_conv

            # Volumes
            for entry in entries:
                vol_no = entry.get("volume_no") or 0
                if vol_no <= 0:
                    continue
                vol_qty = fg_vol_count.get(f"{fg}|{vol_no}", 0.0)
                vol_pricing = _price_conv(entry.get("vol_pricing", 0.0), entry.get("currency", "USD"))

                ext_vol_qty = part_qty * vol_qty
                ext_price_conv = part_qty * vol_pricing
                ext_part_vol_price_conv = (ext_price_conv * ext_vol_qty) / part_qty if part_qty > 0.0 else 0.0

                vol_row = summary_grouped[fg].setdefault(vol_no, {
                    "volume": vol_no, "vol_qty": 0.0, "vol_pricing": 0.0,
                    "ext_part_vol_price_conv": 0.0, "MOQ_cost": 0.0, "cbom_cost": 0.0,
                })
                vol_row["vol_pricing"] += vol_pricing
                vol_row["ext_part_vol_price_conv"] += ext_part_vol_price_conv
                vol_row["cbom_cost"] += ext_price_conv

    # 3) Set vol_qty once per FG (not accumulated).
    for fg, fg_data in summary_grouped.items():
        if "proto" in fg_data:
            fg_data["proto"]["vol_qty"] = proto_qty_global
        for vol_no in volume_nos:
            if vol_no in fg_data:
                fg_data[vol_no]["vol_qty"] = fg_vol_count.get(f"{fg}|{vol_no}", 0.0)

    # 4) Flatten into assemblies + totals.
    assemblies = []
    totals_by_volume = {}
    for fg, volumes in summary_grouped.items():
        sorted_keys = sorted(volumes.keys(), key=lambda k: (0, -1) if k == "proto" else (1, k))
        assembly_summary = {"Assembly": fg, "volumes": []}
        for vk in sorted_keys:
            vol_data = volumes[vk]
            key = vol_data["volume"]
            assembly_summary["volumes"].append({
                "volume": key,
                "vol_qty": round(vol_data["vol_qty"], 2),
                "vol_pricing": round(vol_data["vol_pricing"], 4),
                "ext_part_vol_price_conv": round(vol_data["ext_part_vol_price_conv"], 4),
                "MOQ_cost": 0.0,  # always 0 at assembly level, by design
                "cbom_cost": round(vol_data["cbom_cost"], 4),
            })
            tot = totals_by_volume.setdefault(key, {
                "volume": key, "vol_qty": 0.0, "vol_pricing": 0.0,
                "ext_part_vol_price_conv": 0.0, "MOQ_cost": 0.0, "cbom_cost": 0.0,
            })
            tot["vol_pricing"] += vol_data["vol_pricing"]
            tot["vol_qty"] += vol_data["vol_qty"]
            tot["ext_part_vol_price_conv"] += vol_data["ext_part_vol_price_conv"]
            tot["MOQ_cost"] = total_moq_costs.get(key, 0.0)
            tot["cbom_cost"] += vol_data["cbom_cost"]
        assemblies.append(assembly_summary)

    totals = []
    for vol in totals_by_volume.values():
        moq_cost = vol["MOQ_cost"]
        ext = vol["ext_part_vol_price_conv"]
        in_percent = f"{round((moq_cost / ext) * 100, 2)}%" if ext > 0 else ""
        totals.append({
            "volume": vol["volume"],
            "vol_pricing": round(vol["vol_pricing"], 4),
            "ext_part_vol_price_conv": round(vol["ext_part_vol_price_conv"], 4),
            "MOQ_cost": round(moq_cost, 4),
            "cbom_cost": round(vol["cbom_cost"], 4),
            "in_percent": in_percent,
        })
    totals.sort(key=lambda t: (0, -1) if t["volume"] == "proto" else (1, t["volume"]))

    return {"revision_no": rev, "centum_id": centum_id, "assemblies": assemblies, "totals": totals}


def _filter_proto(revisions):
    """Port of SummaryExportExcelFormula::filterJsonData(): strips 'proto' volume rows."""
    filtered = []
    for rev_block in revisions:
        new_block = dict(rev_block)
        new_block["totals"] = [v for v in rev_block.get("totals", []) if v.get("volume") != "proto"]
        new_assemblies = []
        for asm in rev_block.get("assemblies", []):
            new_asm = dict(asm)
            new_asm["volumes"] = [v for v in asm.get("volumes", []) if v.get("volume") != "proto"]
            new_assemblies.append(new_asm)
        new_block["assemblies"] = new_assemblies
        filtered.append(new_block)
    return filtered


_THIN_SIDE = Side(style="thin", color="000000")
_THICK_SIDE = Side(style="thick", color="000000")
_CENTER = Alignment(horizontal="center")


def _fill(rgb):
    return PatternFill("solid", fgColor=rgb)


def _style_range(ws, col1, row1, col2, row2, fill=None, font=None, alignment=None):
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            cell = ws.cell(row=r, column=c)
            if fill is not None:
                cell.fill = fill
            if font is not None:
                cell.font = font
            if alignment is not None:
                cell.alignment = alignment


def _border_all(ws, col1, row1, col2, row2, side):
    border = Border(left=side, right=side, top=side, bottom=side)
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            ws.cell(row=r, column=c).border = border


def _border_outline(ws, col1, row1, col2, row2, side):
    for r in range(row1, row2 + 1):
        for c in range(col1, col2 + 1):
            cell = ws.cell(row=r, column=c)
            b = cell.border
            cell.border = Border(
                left=side if c == col1 else b.left,
                right=side if c == col2 else b.right,
                top=side if r == row1 else b.top,
                bottom=side if r == row2 else b.bottom,
            )


def build_summary_sheet(wb, revisions, cbom_row_counts, include_proto=True, now=None):
    """Port of SummaryExportExcelFormula: live-formula 'Summary' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    revisions: the list of dicts produced by summary().
    cbom_row_counts: {cbom_sheet_name: last_row} for every '7.0 CBOM VL-{n}'/
        '7.0 CBOM Proto' sheet this workbook will contain -- computed early via
        cbom_vl.cbom_vl_rows() (before those sheets are actually built later in
        exporter.py) purely to get len(rows), so this sheet's cross-references to
        them can be bounded instead of scanning full columns.
    include_proto: replaces resolveIncludeProto($bomId) — pass the same
        true/false that check would have produced from bom_details.proto.
    now: overrides PHP's now() for the revision-header date label (defaults
        to the real current time); pass a fixed datetime for deterministic tests.
    """
    json_data = revisions if include_proto else _filter_proto(revisions)
    now = now or datetime.now()

    ws = wb.create_sheet(title="Summary")

    sheet_data = [["CBOM Summary"]]

    today_str = now.strftime("%d-%b-%Y")
    row2 = ["", "", ""]
    for rev_block in json_data:
        vol_count = len(rev_block["totals"])
        label = f"{rev_block['centum_id']}, Rev-{rev_block['revision_no']}, {today_str}"
        row2 += [label] * (vol_count * 2)
    sheet_data.append(row2)

    row3 = ["", "", "Assembly"]
    for rev_block in json_data:
        for vol in rev_block["totals"]:
            vol_label = "Proto Volume" if vol["volume"] == "proto" else f"Volume-{vol['volume']}"
            cost_label = "CBOM Cost Proto" if vol["volume"] == "proto" else f"CBOM Cost VL-{vol['volume']}"
            row3.append(vol_label)
            row3.append(cost_label)
    sheet_data.append(row3)

    if json_data and json_data[0].get("assemblies"):
        for asm_block in json_data[0]["assemblies"]:
            row = ["", "", asm_block["Assembly"]]
            for rev_block in json_data:
                # Match by assembly name within each revision: revisions do not share assembly
                # membership or order, so a positional index showed another FG's numbers.
                by_name = {a["Assembly"]: a for a in rev_block.get("assemblies", [])}
                volumes = (by_name.get(asm_block["Assembly"]) or {}).get("volumes", [])
                for i in range(len(rev_block["totals"])):
                    vol = volumes[i] if i < len(volumes) else {}
                    row.append(vol.get("vol_qty", ""))
                    row.append(vol.get("cbom_cost", ""))
            sheet_data.append(row)

    cbom_cost_row = ["", "", ""]
    for rev_block in json_data:
        for vol in rev_block["totals"]:
            cbom_cost_row += ["", vol.get("cbom_cost", "")]
    sheet_data.append(cbom_cost_row)

    sheet_data.append(["", "", ""])
    sheet_data.append(["", "", ""])

    ext_row = ["", "", "Ext Vol Conv Price #1"]
    for rev_block in json_data:
        for vol in rev_block["totals"]:
            ext_row += ["", vol.get("ext_part_vol_price_conv", "")]
    sheet_data.append(ext_row)

    sheet_data.append(["", "", ""])

    moq_row = ["", "", "MOQ Cost"]
    for rev_block in json_data:
        for vol in rev_block["totals"]:
            moq_row += ["", vol.get("MOQ_cost", "")]
    sheet_data.append(moq_row)

    in_percent_row = ["", "", "In %"]
    for rev_block in json_data:
        for vol in rev_block["totals"]:
            in_percent_row += ["", vol.get("in_percent", "")]
    sheet_data.append(in_percent_row)

    for row in sheet_data:
        ws.append(row)

    highest_row = len(sheet_data)
    highest_col = max(len(r) for r in sheet_data)

    ws.merge_cells("A1:Z1")
    ws["A1"].font = Font(bold=True, size=14)

    start_col_index = 4
    for rev_block in json_data:
        vol_span = len(rev_block["totals"]) * 2
        # A block with no volumes left (e.g. proto-only with include_proto=False) spans zero
        # columns; merging it would invert the range (end 3 < start 4) and abort the export.
        if vol_span == 0:
            continue
        end_col_index = start_col_index + vol_span - 1
        ws.merge_cells(start_row=2, start_column=start_col_index, end_row=2, end_column=end_col_index)
        _style_range(ws, start_col_index, 2, end_col_index, 2, fill=_fill("2F5496"),
                     font=Font(bold=True, color="FFFFFF"), alignment=_CENTER)
        _border_outline(ws, start_col_index, 2, end_col_index, 2, _THICK_SIDE)
        start_col_index += vol_span

    _style_range(ws, 3, 3, highest_col, 3, fill=_fill("D9E2F3"), font=Font(bold=True))
    _border_all(ws, 3, 3, highest_col, 3, _THIN_SIDE)

    total_start_row = highest_row - 5
    _style_range(ws, 3, 4, highest_col, total_start_row - 1, fill=_fill("F2F6FC"))
    _border_all(ws, 3, 4, highest_col, total_start_row - 1, _THIN_SIDE)

    for row in range(total_start_row, highest_row + 1):
        for col in range(1, highest_col + 1):
            cell = ws.cell(row=row, column=col)
            if cell.value not in (None, ""):
                cell.fill = _fill("FFC000")
                cell.border = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)

    # Currency format on every "cost" column (E, G, I, ... i.e. odd column index >= 5).
    # ponytail: PHP walks column LETTERS with ord() math that silently breaks past
    # column Z (two-letter columns) — we use column INDEX parity instead, which is
    # what the PHP was actually trying to express and stays correct for wide sheets.
    for col_index in range(4, highest_col + 1):
        if (col_index - 3) % 2 == 0:
            for row in range(4, highest_row + 1):
                ws.cell(row=row, column=col_index).number_format = '"$"#,##0.0000'  # exactly 4 decimal places

    ws.freeze_panes = "A4"

    try:
        rev_count = len(json_data)
        if rev_count > 0:
            last_rev_index = rev_count - 1
            last_rev_block = json_data[last_rev_index]

            start_col_index = 4
            for i in range(last_rev_index):
                start_col_index += len(json_data[i].get("totals", [])) * 2

            assembly_count = len(json_data[0]["assemblies"]) if json_data and json_data[0].get("assemblies") else 0

            if last_rev_block.get("totals") and assembly_count > 0:
                first_asm_row = 4
                last_asm_row = 3 + assembly_count
                cbom_cost_total_row = 4 + assembly_count
                ext_vol_conv_price_row = 7 + assembly_count
                moq_cost_row = 9 + assembly_count
                in_percent_row_num = 10 + assembly_count

                for idx, vol in enumerate(last_rev_block["totals"]):
                    vol_val = vol.get("volume")
                    if vol_val is None:
                        continue
                    vol_no_str = str(vol_val)
                    if vol_no_str == "1":
                        continue  # handled separately below, exactly like the source

                    qty_col_index = start_col_index + (idx * 2)
                    cost_col_index = qty_col_index + 1
                    cost_col = get_column_letter(cost_col_index)

                    cbom_sheet = "7.0 CBOM Proto" if vol_no_str == "proto" else f"7.0 CBOM VL-{vol_no_str}"
                    ex_inv_sheet = "Ex Inv VL-proto" if vol_no_str == "proto" else f"Ex Inv VL-{vol_no_str}"
                    cbom_last_row = cbom_row_counts[cbom_sheet]

                    for r in range(first_asm_row, last_asm_row + 1):
                        ws.cell(row=r, column=qty_col_index).value = (
                            f"=IFERROR(INDEX('{cbom_sheet}'!$F$1:$F${cbom_last_row}, "
                            f"MATCH(Summary!$C{r}, '{cbom_sheet}'!$C$1:$C${cbom_last_row}, 0)),\"\")"
                        )
                        ws.cell(row=r, column=cost_col_index).value = (
                            f"=IFERROR(INDEX('{cbom_sheet}'!$E$1:$E${cbom_last_row}, "
                            f"MATCH(Summary!$C{r}, '{cbom_sheet}'!$C$1:$C${cbom_last_row}, 0)),0)"
                        )

                    ws.cell(row=cbom_cost_total_row, column=cost_col_index).value = (
                        f"=SUBTOTAL(109,Summary!${cost_col}${first_asm_row}:${cost_col}${last_asm_row})"
                    )
                    ws.cell(row=ext_vol_conv_price_row, column=cost_col_index).value = (
                        f"=IFERROR(INDEX('{cbom_sheet}'!$G$1:$G${cbom_last_row}, "
                        f"MATCH(\"TOTAL\", '{cbom_sheet}'!$C$1:$C${cbom_last_row}, 0)),0)"
                    )
                    ws.cell(row=moq_cost_row, column=cost_col_index).value = f"=IFERROR('{ex_inv_sheet}'!$A$2,0)"
                    ws.cell(row=in_percent_row_num, column=cost_col_index).value = (
                        f"=IFERROR({cost_col}{moq_cost_row}/{cost_col}{ext_vol_conv_price_row},\"\")"
                    )
                    ws.cell(row=in_percent_row_num, column=cost_col_index).number_format = "0.00%"

            vol1_idx = None
            if last_rev_block.get("totals"):
                for idx, vol in enumerate(last_rev_block["totals"]):
                    vol_val = vol.get("volume")
                    if vol_val != "proto" and str(vol_val) == "1":
                        vol1_idx = idx
                        break

            if vol1_idx is not None and assembly_count > 0:
                qty_col_index = start_col_index + (vol1_idx * 2)
                cost_col_index = qty_col_index + 1
                cost_col = get_column_letter(cost_col_index)

                first_asm_row = 4
                last_asm_row = 3 + assembly_count

                vol_no1 = str(last_rev_block["totals"][vol1_idx].get("volume", "1"))
                cbom_sheet1 = "7.0 CBOM Proto" if vol_no1 == "proto" else f"7.0 CBOM VL-{vol_no1}"
                ex_inv_sheet1 = "Ex Inv VL-proto" if vol_no1 == "proto" else f"Ex Inv VL-{vol_no1}"
                cbom_last_row1 = cbom_row_counts[cbom_sheet1]

                for row in range(first_asm_row, last_asm_row + 1):
                    ws.cell(row=row, column=qty_col_index).value = (
                        f"=IFERROR(INDEX('{cbom_sheet1}'!$F$1:$F${cbom_last_row1}, "
                        f"MATCH(Summary!$C{row}, '{cbom_sheet1}'!$C$1:$C${cbom_last_row1}, 0)),\"\")"
                    )
                    ws.cell(row=row, column=cost_col_index).value = (
                        f"=IFERROR(INDEX('{cbom_sheet1}'!$E$1:$E${cbom_last_row1}, "
                        f"MATCH(Summary!$C{row}, '{cbom_sheet1}'!$C$1:$C${cbom_last_row1}, 0)),0)"
                    )

                cbom_cost_total_row = 4 + assembly_count
                ext_vol_conv_price_row = 7 + assembly_count
                moq_cost_row = 9 + assembly_count
                in_percent_row_num = 10 + assembly_count

                ws.cell(row=cbom_cost_total_row, column=cost_col_index).value = (
                    f"=SUBTOTAL(109,Summary!${cost_col}${first_asm_row}:${cost_col}${last_asm_row})"
                )
                ws.cell(row=ext_vol_conv_price_row, column=cost_col_index).value = (
                    f"=IFERROR(INDEX('{cbom_sheet1}'!$G$1:$G${cbom_last_row1}, "
                    f"MATCH(\"TOTAL\", '{cbom_sheet1}'!$C$1:$C${cbom_last_row1}, 0)),0)"
                )
                ws.cell(row=moq_cost_row, column=cost_col_index).value = f"=IFERROR('{ex_inv_sheet1}'!$A$2,0)"
                ws.cell(row=in_percent_row_num, column=cost_col_index).value = (
                    f"=IFERROR({cost_col}{moq_cost_row}/{cost_col}{ext_vol_conv_price_row},\"\")"
                )
                ws.cell(row=in_percent_row_num, column=cost_col_index).number_format = "0.00%"
    except Exception:
        pass  # mirrors the original's silent try/catch around formula injection

    return ws


def _demo():
    import json
    from openpyxl import Workbook

    payload = {
        "centum_id": "CE-1234_1",
        "proto_qty": 100,

        "bom_data": [
            {
                "FG": "ASSY-01",
                "Assembly": "ASSY-01",
                "CPN": "CPN-4001",
                "Quantity": 10,
                "inventory_stock": 20
            }
        ],

        "rfqs": [
            # Proto RFQ
            {
                "cpn": "CPN-4001",
                "revision_no": 0,
                "volume_no": None,
                "currency": "USD",
                "proto_pricing": 2.25,
                "vol_pricing": 0,
                "package_qty": 100,
                "vol_moq": 0,
                "vol_qty": 0
            },

            # Volume-1 RFQ
            {
                "cpn": "CPN-4001",
                "revision_no": 0,
                "volume_no": 1,
                "currency": "USD",
                "proto_pricing": 0,
                "vol_pricing": 1.50,
                "package_qty": 100,
                "vol_moq": 500,
                "vol_qty": 1000
            }
        ],

        "fgcounts": [
            {
                "fg": "ASSY-01",
                "volume_no": 1,
                "count": 100
            }
        ]
    }

    # v2 schema self-check: `volume` table rows adapt cleanly to the
    # 'fgcounts' shape summary() already expects.
    volume_rows = [{"fg": "ASSY-01", "volume_name": "V1", "batch_qty": 100}]
    assert fgcounts_from_volume_rows(volume_rows) == payload["fgcounts"]
    print("fgcounts_from_volume_rows() self-check passed")

    # v2 schema self-check: no revision_no available (as from today's flat
    # quote_win) degrades to a single revision_no=0 block, not an error.
    no_revision_rfqs = [{k: v for k, v in r.items() if k != "revision_no"} for r in payload["rfqs"]]
    degraded_result = summary({**payload, "rfqs": no_revision_rfqs})
    assert len(degraded_result) == 1 and degraded_result[0]["revision_no"] == 0
    print("no-revision-data degradation self-check passed")

    print("\n================ INPUT ================\n")
    print(json.dumps(payload, indent=4))

    result = summary(payload)

    print("\n================ OUTPUT ================\n")
    print(json.dumps(result, indent=4))

    wb = Workbook()

    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    build_summary_sheet(
        wb,
        result,
        cbom_row_counts={"7.0 CBOM VL-1": 500, "7.0 CBOM Proto": 300},
        include_proto=True
    )

    output_file = "Summary_Output.xlsx"
    wb.save(output_file)

    print("\n======================================")
    print("Summary report generated successfully.")
    print(f"Excel File : {output_file}")
    print("======================================")



if __name__ == "__main__":
    _demo()
