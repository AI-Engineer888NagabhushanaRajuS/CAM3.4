"""Quote-summary export for RFQ_Flow.

Structure modeled directly on the reference workbook's "Quote" tab
(testing\\reference\\Quote_FY2627-IISPL019_Smartan Controller box_ Box
build_06-08-2026.xlsx, "Quote" sheet): a header block, one column per
volume/build scenario, and a fixed set of cost row labels.

This produces its OWN new workbook -- it does not touch export_bom.py's
existing fixed-template fill or the external template file.

The reference sheet has three value columns per FG (Proto qty, Batch INR,
Batch USD) because that project quotes in two currencies for two build
sizes. RFQ_Flow has neither concept today: processed_bom_items.volume is a
single per-FG production volume (no Proto/Batch distinction), and
selected_unit_price is already normalized to one currency (INR, per
enrichment.py's convert_to_inr()). So this writes one value column per
distinct volume value actually present for the RFQ, in INR only --
matching the reference's row labels exactly, without inventing a second
currency conversion or a Proto/Batch split that isn't backed by real data
here.

Only "BOM cost" is populated (SUM(required_qty * selected_unit_price),
sourced from enrichment.py's single-source selected_unit_price -- never
recomputed independently here). Every other row label from the reference
is written but left blank: those are real business rules (MOQ charges,
material yield, freight/duty, assembly/testing/overhead/profit) that
haven't been defined yet, per explicit instruction not to invent them.

Also builds a second sheet, "Final Structured BoM", matching the reference
workbook's own second sheet: a hierarchical, per-occurrence view (one row
per bom_structure_items occurrence, not consolidated by MPN) with
Level/Product name/local Unit Quantity, joined to processed_bom_items by
mpn for the single-source selected price. See
_build_structured_bom_sheet()'s own docstring for the exact column mapping
and what's deliberately left blank.
"""

import datetime
import json
from pathlib import Path

import duckdb
import pandas as pd
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from config import DB_PATH
# config.py's own import already put mcp-tools/ on sys.path. Single source
# of truth for the "manually edited cell" highlight color -- keep in sync
# with export_bom.py and duck_db_api.py's Gerber export.
from shared.highlight_style import MANUAL_EDIT_FILL_ARGB

OUTPUT_DIR = Path(__file__).resolve().parent / "quote_exports"

# Row labels, in the exact order the reference "Quote" tab uses them.
# ROW_BOM_COST and ROW_MOQ_CHARGES are populated; every other label is
# still structure-only (blank) -- those business rules haven't been defined.
ROW_LABELS = [
    "BOM cost",
    "MOQ Charges for batch",
    "Material Yield %",
    "Frt & Duty chgs",
    "Total BoM Cost",
    "Assy Charges",
    "Testing",
    "Over head and Profits",
    "Final Selling Price",
]
ROW_BOM_COST = "BOM cost"
ROW_MOQ_CHARGES = "MOQ Charges for batch"

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=14)
_LABEL_FONT = Font(bold=True)
_MANUAL_EDIT_FILL = PatternFill("solid", fgColor=MANUAL_EDIT_FILL_ARGB)


def _rfq_has_processed_items(conn, rfq_id):
    """Basic "was this RFQ actually imported/enriched" gate -- separate from
    _fetch_quote_rows()'s own per-FG cost breakdown below, which needs a
    different, per-occurrence source (see that function's docstring)."""
    count = conn.execute(
        "SELECT COUNT(*) FROM processed_bom_items WHERE CAST(rfq_id AS VARCHAR) = ?",
        [rfq_id],
    ).fetchone()[0]
    return count > 0


def _fetch_quote_rows(conn, rfq_id):
    """One row per (fg, volume), with the FG total material cost computed from
    bom_structure_items (genuinely one row per BOM occurrence, correctly
    scoped to a single real FG) joined to processed_bom_items' single-source
    selected_unit_price by mpn -- NOT grouped by processed_bom_items.fg/
    required_qty directly.

    Why not processed_bom_items directly: consolidate_bom() (bom_processing.py)
    deliberately consolidates by MPN ALONE, across the whole BOM -- when the
    same MPN is shared by multiple FGs (routine for connectors/screws/labels
    in a multi-harness BOM), its fg column becomes a comma-joined list of every
    FG that part appears under, and required_qty becomes the SUM of that
    part's demand across all of them. Grouping by that fg string and summing
    "required_qty * selected_unit_price" silently inflates BOM cost by
    however many FGs share that part (confirmed on real data: a shared-part
    fg group produced a >1000x-too-large total). bom_structure_items has no
    such merging -- each row is exactly one BOM occurrence under exactly one
    real fg -- so this joins there instead for a correct per-FG total.

    Returns an empty (but correctly-columned) frame if bom_structure_items
    doesn't exist yet (an RFQ imported before that table existed) -- the
    caller degrades to an empty "Quote" cost breakdown rather than crashing,
    same graceful-degradation convention as _fetch_structure_rows() below.
    """
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'bom_structure_items'"
    ).fetchone()
    if not exists:
        return pd.DataFrame(columns=["fg", "volume", "bom_cost", "unpriced_parts", "total_parts"])

    return conn.execute(
        """
        SELECT
            s.fg,
            s.volume,
            SUM(COALESCE(s.bom_qty, 0) * COALESCE(s.hierarchy_multiplier, 1)
                * COALESCE(p.selected_unit_price, 0)) AS bom_cost,
            SUM(CASE WHEN p.selected_unit_price IS NULL THEN 1 ELSE 0 END)
                AS unpriced_parts,
            COUNT(*) AS total_parts
        FROM bom_structure_items s
        LEFT JOIN processed_bom_items p
            ON CAST(p.rfq_id AS VARCHAR) = CAST(s.rfq_id AS VARCHAR)
            AND UPPER(TRIM(p.mpn)) = UPPER(TRIM(s.mpn))
        WHERE CAST(s.rfq_id AS VARCHAR) = ?
        GROUP BY s.fg, s.volume
        ORDER BY s.fg, s.volume
        """,
        [rfq_id],
    ).fetchdf()


def _fetch_costed_mpns_for_moq(conn, rfq_id):
    """One row per costed MPN (processed_bom_items is already one row per
    unique MPN, required_qty already summed across every BOM row that MPN
    appeared on -- see bom_processing.py's consolidate_bom() -- so no extra
    grouping is needed here). Only MPNs with a real selected_unit_price
    ("costed") are included; excluded/uncosted MPNs never reach this query.
    """
    return conn.execute(
        """
        SELECT mpn, required_qty, selected_moq, selected_unit_price, selected_supplier
        FROM processed_bom_items
        WHERE CAST(rfq_id AS VARCHAR) = ?
          AND selected_unit_price IS NOT NULL
        """,
        [rfq_id],
    ).fetchdf()


def _compute_moq_charges_for_batch(conn, rfq_id):
    """MOQ Charges for Batch = SUM over every costed MPN of
    MAX(selected_moq - required_qty, 0) * selected_unit_price.

    selected_moq/selected_unit_price are read together from the SAME winning
    distributor (select_best_distributor_price() in enrichment.py) -- this
    never re-selects a price or MOQ source independently, per the
    requirement that Final Cost/MOQ Charges/Quote Readiness/Reports all use
    one shared final-price selection.

    Missing/invalid required_qty, selected_moq, or selected_unit_price on a
    given MPN contributes 0 to the total rather than raising -- a data gap on
    one part must not fail the whole batch total. Logs one line per MPN
    (mpn, required_qty, moq, price, moq_difference, charge) so the final
    total is auditable back to any individual part.
    """
    df = _fetch_costed_mpns_for_moq(conn, rfq_id)

    total = 0.0

    print("\n==================== MOQ CHARGES FOR BATCH TRACE ====================")
    print(f"{'MPN':<20} {'RequiredQty':>12} {'MOQ':>10} {'Price':>10} {'MOQDiff':>10} {'Charge':>12}")

    for _, row in df.iterrows():
        mpn = row["mpn"]
        required_qty = row["required_qty"]
        moq = row["selected_moq"]
        price = row["selected_unit_price"]

        valid = (
            required_qty is not None and not pd.isna(required_qty)
            and moq is not None and not pd.isna(moq)
            and price is not None and not pd.isna(price)
        )

        if not valid:
            moq_difference = 0.0
            charge = 0.0
        else:
            moq_difference = max(moq - required_qty, 0)
            charge = moq_difference * price

        total += charge

        print(
            f"{str(mpn):<20} {required_qty if required_qty is not None else '-':>12} "
            f"{moq if moq is not None else '-':>10} {price if price is not None else '-':>10} "
            f"{moq_difference:>10.2f} {charge:>12.2f}"
        )

    print(f"{'TOTAL MOQ CHARGES FOR BATCH':<54} {total:>12.2f}")
    print("=======================================================================\n")

    return total


# Column headers for the "Final Structured BoM" sheet that don't vary by volume --
# the per-volume Unit Price/System Price/Remarks blocks are appended after these,
# one block per distinct volume present for this RFQ (same convention as the
# "Quote" sheet's per-volume columns above).
_STRUCTURED_HEADERS = [
    "Product name", "Level", "Item#", "Unit Quantity", "UOM", "Description",
    "Recommended Vendor", "Vendor Part No.", "Manufacturer", "Manufacturer Part No.",
    "SPIRIT P/N", "ORACLE P/N", "Clarification", "Response", "MyTC Comments",
]

# Which processed_bom_items column holds a given distributor's own part number --
# selected_supplier names which of the 3 distributors was actually chosen, so the
# matching part-number column can be looked up rather than showing all 3.
_SUPPLIER_PART_NUMBER_COLUMN = {
    "DigiKey": "digikey_part_number",
    "Element14": "element14_part_number",
    "Mouser": "mouser_part_number",
}


_STRUCTURE_COLUMNS = [
    "occurrence_order", "fg", "bom_level", "item_num", "cpn", "description",
    "mfr", "mpn", "commodity", "bom_qty", "hierarchy_multiplier", "uom",
]


def _fetch_structure_rows(conn, rfq_id):
    """One row per BOM occurrence, in original file order -- NOT consolidated by
    MPN (that's processed_bom_items' job). See bom_to_database.py's
    process_bom_structure_to_database()/bom_processing.py's expand_bom_with_volume()
    for where these rows and their hierarchy_multiplier come from.

    bom_structure_items is created lazily by import_bom (CREATE TABLE IF NOT
    EXISTS) -- an RFQ imported before this table existed has no rows in it, and
    on a fresh DB the table itself may not exist yet at all. Either way, the
    "Final Structured BoM" sheet degrades to empty rather than this (or the
    "Quote" sheet, which shares this same connection/call) crashing outright.
    """
    exists = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'bom_structure_items'"
    ).fetchone()
    if not exists:
        return pd.DataFrame(columns=_STRUCTURE_COLUMNS)

    return conn.execute(
        """
        SELECT occurrence_order, fg, bom_level, item_num, cpn, description, mfr,
               mpn, commodity, bom_qty, hierarchy_multiplier, uom
        FROM bom_structure_items
        WHERE CAST(rfq_id AS VARCHAR) = ?
        ORDER BY occurrence_order
        """,
        [rfq_id],
    ).fetchdf()


def _fetch_pricing_by_mpn(conn, rfq_id):
    """mpn (upper-stripped, matching consolidate_bom()'s own normalization) ->
    that row's single-source selected price/supplier plus every distributor's own
    part number (to resolve _SUPPLIER_PART_NUMBER_COLUMN against).

    Also carries bom_item_id/manually_edited_fields through, even though the
    dict itself is keyed by mpn -- the highlighting decision in
    _build_structured_bom_sheet() below reads manually_edited_fields straight
    off THIS already-matched row object, never re-derives "was this edited"
    from the bare mpn string a second time. mpn is only the join key to reach
    the right processed_bom_items row in the first place (each real row is
    still its own bom_item_id underneath); per explicit instruction, edit
    metadata must never be trusted via mpn-string equality alone."""
    df = conn.execute(
        """
        SELECT bom_item_id, mpn, selected_unit_price, selected_currency, selected_supplier,
               digikey_part_number, element14_part_number, mouser_part_number,
               manually_edited_fields
        FROM processed_bom_items
        WHERE CAST(rfq_id AS VARCHAR) = ?
        """,
        [rfq_id],
    ).fetchdf()
    by_mpn = {}
    for _, r in df.iterrows():
        mpn = str(r["mpn"] or "").strip().upper()
        if mpn:
            by_mpn[mpn] = r
    return by_mpn


def _edited_fields_of(pricing_row):
    """Parses manually_edited_fields off a processed_bom_items row object
    (as carried through _fetch_pricing_by_mpn) -- the single source of truth
    every highlight decision in this file reads."""
    if pricing_row is None:
        return set()
    try:
        return set(json.loads(pricing_row.get("manually_edited_fields") or "[]"))
    except (TypeError, ValueError):
        return set()


def _build_structured_bom_sheet(wb, structure_df, pricing_by_mpn, fg_to_volume):
    """Builds "Final Structured BoM", matching the reference workbook's own second
    sheet: a hierarchical, per-occurrence view (Level/Product name/local Unit
    Quantity), not the MPN-consolidated view the "Quote" sheet's BOM cost uses.

    - Product name: the row's immediate parent's own identifier, with the
      parent's own description in parentheses when known (reconstructed via a
      level stack over occurrence_order -- bom_structure_items stores each row's
      OWN level, not an explicit parent reference, so the parent is whichever
      still-open stack frame has the next-lower level). A Level-1 row's "parent"
      is its FG -- shown bare (no parenthetical description), since the FG
      marker row itself is never one of the expanded occurrences and so has no
      stored description here.
    - Item#: a sequential counter over Level-1 rows only, in occurrence order --
      not bom_structure_items' own item_num column, which is a raw per-row
      template field, not a level-1-only sequence. Blank for every deeper level,
      matching the reference's own convention.
    - Recommended Vendor / Vendor Part No.: selected_supplier / that supplier's
      own part-number column, joined by mpn -- blank when no distributor matched
      (expected for non-electronic parts; not every row will have one).
    - Unit Price in INR / System Price in INR: one column pair per distinct
      volume present for this RFQ (blank for a row's own non-matching volume
      columns, since each row's FG has exactly one volume). Unit Price =
      selected_unit_price (already INR-normalized); System Price = bom_qty
      (local, within this row's own immediate parent) * hierarchy_multiplier --
      the correct hierarchy-weighted cost for ONE occurrence through its own
      ancestor chain, deliberately not multiplied by the FG's volume (that
      total is what the "Quote" sheet's BOM cost row already covers).
    - SPIRIT P/N, ORACLE P/N, Clarification, Response, MyTC Comments, Remarks:
      structural columns only, left blank on every row -- no data source for
      these anywhere in RFQ_Flow; same "don't invent it, leave it blank"
      principle already applied to the Quote sheet's Assy/Testing/Overhead rows.
    """
    ws = wb.create_sheet(title="Final Structured BoM")

    volumes = sorted({v for v in fg_to_volume.values() if v is not None})

    header_row = 1
    ws.append(list(_STRUCTURED_HEADERS))
    volume_col_start = {}
    col = len(_STRUCTURED_HEADERS) + 1
    for volume in volumes:
        ws.cell(row=header_row, column=col, value=f"Unit Price in INR (Vol {volume})")
        ws.cell(row=header_row, column=col + 1, value=f"System Price in INR (Vol {volume})")
        ws.cell(row=header_row, column=col + 2, value="Remarks")
        volume_col_start[volume] = col
        col += 3
    last_col = col - 1

    for c in range(1, last_col + 1):
        cell = ws.cell(row=header_row, column=c)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT

    # (level, own identifier, own description) frames for still-open ancestors --
    # popped whenever a row's own level is <= the frame's level, mirroring
    # expand_bom_with_volume()'s own stack-walk invariant (display-only here;
    # no quantity/price math happens against this stack).
    stack = []
    level1_counter = 0
    row_idx = header_row + 1

    for _, r in structure_df.iterrows():
        level = r["bom_level"]
        level = None if pd.isna(level) else int(level)
        own_id = str(r["mpn"] or r["cpn"] or "").strip()
        own_desc = r["description"]

        if level is not None:
            while stack and stack[-1][0] >= level:
                stack.pop()

        if stack:
            parent_id, parent_desc = stack[-1][1], stack[-1][2]
            product_name = f"{parent_id}({parent_desc})" if parent_desc else parent_id
        else:
            product_name = str(r["fg"] or "")

        item_num = None
        if level == 1:
            level1_counter += 1
            item_num = level1_counter

        mpn_key = own_id.upper()
        pricing = pricing_by_mpn.get(mpn_key)
        vendor = pricing["selected_supplier"] if pricing is not None else None
        vendor_part_no = None
        if pricing is not None and vendor in _SUPPLIER_PART_NUMBER_COLUMN:
            vendor_part_no = pricing.get(_SUPPLIER_PART_NUMBER_COLUMN[vendor])
        # Raw BOM fields on THIS row (product_name/qty/uom/description/mfr/mpn
        # in columns 1-10 above) come from bom_structure_items, a separate
        # table the Final BOM Preview's edit endpoint never writes to -- they
        # are intentionally NEVER highlighted here, only the selected_*
        # pricing fields below, which genuinely do come from
        # processed_bom_items (via pricing, matched through this row's own
        # bom_item_id -- see _fetch_pricing_by_mpn's docstring).
        edited_fields = _edited_fields_of(pricing)

        ws.cell(row=row_idx, column=1, value=product_name)
        ws.cell(row=row_idx, column=2, value=level)
        ws.cell(row=row_idx, column=3, value=item_num)
        ws.cell(row=row_idx, column=4, value=r["bom_qty"])
        ws.cell(row=row_idx, column=5, value=r["uom"])
        ws.cell(row=row_idx, column=6, value=own_desc)
        vendor_cell = ws.cell(row=row_idx, column=7, value=vendor)
        if "selected_supplier" in edited_fields:
            vendor_cell.fill = _MANUAL_EDIT_FILL
        ws.cell(row=row_idx, column=8, value=vendor_part_no)
        ws.cell(row=row_idx, column=9, value=r["mfr"])
        ws.cell(row=row_idx, column=10, value=r["mpn"])
        # 11-15 (SPIRIT P/N, ORACLE P/N, Clarification, Response, MyTC Comments):
        # left blank -- see docstring.

        own_volume = fg_to_volume.get(r["fg"])
        if (
            pricing is not None
            and pricing.get("selected_unit_price") is not None
            and own_volume in volume_col_start
        ):
            unit_price = pricing["selected_unit_price"]
            multiplier = r["hierarchy_multiplier"]
            multiplier = 1.0 if pd.isna(multiplier) else multiplier
            system_price = (r["bom_qty"] or 0) * multiplier * unit_price
            vcol = volume_col_start[own_volume]
            unit_price_cell = ws.cell(row=row_idx, column=vcol, value=unit_price)
            unit_price_cell.number_format = "#,##0.0000"
            system_price_cell = ws.cell(row=row_idx, column=vcol + 1, value=system_price)
            system_price_cell.number_format = "#,##0.00"
            if "selected_unit_price" in edited_fields:
                # System Price is a computed function of the edited unit
                # price (times bom_qty/hierarchy_multiplier) -- highlighted
                # too since its value genuinely reflects the manual edit,
                # not a copy of separate, un-edited data.
                unit_price_cell.fill = _MANUAL_EDIT_FILL
                system_price_cell.fill = _MANUAL_EDIT_FILL

        stack.append((level if level is not None else 0, own_id, own_desc))
        row_idx += 1

    for c in range(1, last_col + 1):
        ws.column_dimensions[get_column_letter(c)].width = 22

    return ws


def build_quote_summary(rfq_id, customer_name=None, customer_rfq_ref=None,
                         quote_ref=None, attention=None):

    rfq_id = str(rfq_id).strip()

    with duckdb.connect(DB_PATH) as conn:
        if not _rfq_has_processed_items(conn, rfq_id):
            raise ValueError(
                f"No processed_bom_items rows found for rfq_id={rfq_id!r} -- "
                f"run BOM import and distributor enrichment first."
            )
        rows_df = _fetch_quote_rows(conn, rfq_id)
        structure_df = _fetch_structure_rows(conn, rfq_id)
        pricing_by_mpn = _fetch_pricing_by_mpn(conn, rfq_id)
        moq_charges_total = _compute_moq_charges_for_batch(conn, rfq_id)

    fgs = sorted(rows_df["fg"].dropna().unique().tolist())
    volumes = sorted(rows_df["volume"].dropna().unique().tolist())

    # (fg, volume) -> {"bom_cost": ..., "unpriced_parts": ..., "total_parts": ...}
    by_fg_volume = {
        (r["fg"], r["volume"]): r
        for _, r in rows_df.iterrows()
    }

    # RFQ_Flow's model is one production volume per FG (see module docstring) --
    # this dict feeds _build_structured_bom_sheet()'s per-row volume-column lookup.
    fg_to_volume = dict(zip(rows_df["fg"], rows_df["volume"]))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quote"

    # ---------------- Header block ----------------

    ws["C2"] = f"Quotation Summary — RFQ {rfq_id}"
    ws["C2"].font = _TITLE_FONT

    header_fields = [
        ("Customer Name", customer_name),
        ("Customer RFQ Reference No.", customer_rfq_ref),
        ("Quote Ref #", quote_ref),
        ("Quotation Date", datetime.date.today()),
        ("Kind Attention", attention),
    ]
    for offset, (label, value) in enumerate(header_fields):
        row = 4 + offset
        ws.cell(row=row, column=3, value=label).font = _LABEL_FONT
        ws.cell(row=row, column=4, value=value)

    # ---------------- Column layout ----------------
    # One value column per volume scenario, in INR (selected_unit_price is
    # already INR-normalized) -- see module docstring for why this differs
    # from the reference's Proto/Batch-INR/Batch-USD 3-column block.

    first_value_col = 5  # column E
    volume_cols = {
        volume: first_value_col + i for i, volume in enumerate(volumes)
    }

    label_row = 10
    unit_row = 11

    ws.cell(row=label_row, column=2, value="Description")
    for volume, col in volume_cols.items():
        cell = ws.cell(row=label_row, column=col, value=f"Volume {volume} (INR)")
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    # ---------------- Row labels + BOM cost values ----------------

    def _write_row(row_idx, label, values_by_volume=None):
        ws.cell(row=row_idx, column=2, value=label).font = _LABEL_FONT
        if values_by_volume:
            for volume, col in volume_cols.items():
                value = values_by_volume.get(volume)
                if value is not None:
                    ws.cell(row=row_idx, column=col, value=value).number_format = "#,##0.00"

    current_row = unit_row + 1

    if len(fgs) > 1:
        # One BOM-cost row per FG, matching the reference's per-FG breakdown,
        # plus a total row across every FG for this RFQ.
        for fg in fgs:
            values = {
                volume: by_fg_volume[(fg, volume)]["bom_cost"]
                for volume in volumes
                if (fg, volume) in by_fg_volume
            }
            _write_row(current_row, f"BOM cost — {fg}", values)
            current_row += 1

        total_values = {
            volume: rows_df.loc[rows_df["volume"] == volume, "bom_cost"].sum()
            for volume in volumes
        }
        _write_row(current_row, ROW_BOM_COST, total_values)
        current_row += 1
    else:
        fg = fgs[0] if fgs else None
        values = {
            volume: by_fg_volume[(fg, volume)]["bom_cost"]
            for volume in volumes
            if (fg, volume) in by_fg_volume
        }
        _write_row(current_row, ROW_BOM_COST, values)
        current_row += 1

    # Every other reference row label: structure only, no value -- see
    # module docstring. Left as an explicit blank cell, not omitted, so the
    # sheet's row structure matches the reference workbook.
    for label in ROW_LABELS:
        if label == ROW_BOM_COST:
            continue
        if label == ROW_MOQ_CHARGES:
            # A single whole-batch total (required_qty on processed_bom_items
            # is already summed across every FG sharing an MPN -- see
            # _compute_moq_charges_for_batch()'s own docstring), not
            # decomposable per volume/FG the way BOM cost is -- shown
            # identically in every volume column rather than fabricating a
            # per-volume split the underlying data doesn't support.
            _write_row(current_row, label, {volume: moq_charges_total for volume in volumes})
            current_row += 1
            continue
        _write_row(current_row, label)
        current_row += 1

    # ---------------- Coverage note (not a reference-sheet row -- purely
    # informational, so a missing distributor price isn't silently invisible) ----------------

    unpriced_total = int(rows_df["unpriced_parts"].sum())
    if unpriced_total:
        ws.cell(
            row=current_row + 1,
            column=2,
            value=(
                f"Note: {unpriced_total} of {int(rows_df['total_parts'].sum())} "
                f"part rows have no selected distributor price and were excluded "
                f"from BOM cost above."
            ),
        )

    for col in range(2, first_value_col + len(volumes)):
        ws.column_dimensions[get_column_letter(col)].width = 22

    _build_structured_bom_sheet(wb, structure_df, pricing_by_mpn, fg_to_volume)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"Quote_Summary_{rfq_id}_{timestamp}.xlsx"
    wb.save(output_path)

    return {
        "status": "success",
        "rfq_id": rfq_id,
        "fgs": fgs,
        "volumes": volumes,
        "unpriced_parts": unpriced_total,
        "total_parts": int(rows_df["total_parts"].sum()),
        "structured_bom_rows": len(structure_df),
        "output_file": str(output_path),
    }


if __name__ == "__main__":

    rfq_id = input("Enter RFQ ID: ").strip()

    result = build_quote_summary(rfq_id)

    print("\n========================================")
    print(" QUOTE SUMMARY")
    print("========================================")
    print(f"RFQ ID           : {result['rfq_id']}")
    print(f"FGs              : {result['fgs']}")
    print(f"Volumes          : {result['volumes']}")
    print(f"Unpriced parts   : {result['unpriced_parts']} / {result['total_parts']}")
    print(f"Structured BoM rows : {result['structured_bom_rows']}")
    print(f"Output file      : {result['output_file']}")
