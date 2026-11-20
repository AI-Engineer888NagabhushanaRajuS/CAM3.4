"""Python port of the 7.0 CBOM VL report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. cbom_vl_rows() — port of CBOMVolumeSheetExcelFormula::generateRows():
     builds the literal 2D row layout (top summary section, padding, and
     per-Assembly/FG data blocks) for one volume (or 'proto'), matching the
     input/output JSON documented in cbom-vl-report.md. Supports both the
     hierarchical_order-driven ordering and the alphabetical FG-then-Assembly
     fallback.
  2. build_cbom_vl_sheet() — port of the same class's static layout: sheet
     title, header/data/TOTAL row coloring, per-assembly block coloring, and
     the currency reference table (J1:K4).

# ponytail: the shipped PHP class also overwrites ~15 columns (K, N, O, U,
# AG-AW), the J10:K17 validation/Status counts, and the M9/M11 MOQ Cost cells
# with live, self-referential Excel formulas (SUMPRODUCT/INDEX-MATCH over the
# sheet's own just-written rows, plus a cross-sheet reference into this
# volume's own Ex Inv VL sheet for MOQ Cost) — all now reproduced in
# build_cbom_vl_sheet() with dynamic (not hardcoded) row bounds.

No DB access happens here — cbomJson is supplied by the caller.

v2 source schema note: `_data_row()` already reads `v.get("batch_qty", "")`
and `v.get("supplierType", "")` as plain dict lookups -- no code change was
needed when their confirmed sources became the `batch` table (fg, volume,
batch_qty) and `quote_win.supplier_type` respectively (previously gaps; see
cbom-database-schema-design.md). Only the loader that builds the per-volume
dicts under `data[assembly][fg][i]["volumes"]` needs to populate those two
keys now instead of leaving them blank.
"""

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from currency import get_currency_rates, get_default_quote_currency
from scrap_factor import get_scrap_factor_table

NUM_COLS = 50
_RESERVED_KEYS = {"summary", "validation_counts", "project_name", "total_MOQ_costs", "hierarchical_order"}

# The first 8 carry a live formula already verified against the reference workbook. The
# last 5 were restored per explicit, specified business logic (not reverse-engineered
# from a reference file) -- see the formula overlay in build_cbom_vl_sheet().
_VALIDATION_LABELS = [
    "Count of Total CPNs", "Count of Unique CPNs", "Count of Shared CPNs",
    "Total Occurrences of Shared CPNs", "Total Line Items", "Uncosted Line Items Count",
    "CPNs with diff. price", "CPNs with diff. MPNs",
    "Wrong MPNs w.r.t Scrub BOM", "MOQ Missing Count", "SPQ Missing Count",
    "PKG > MOQ", "Commodity Missing Count",
]

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")
_NO_FILL = PatternFill(fill_type=None)  # grid borders only, no colour on data cells
# Explicit 8-digit ARGB (not a bare 6-digit RGB string) -- openpyxl otherwise defaults
# the alpha channel to 00 (fully transparent) for a conditional-formatting dxf fill,
# which renders as invisible in Excel even though the color is technically "set".
_ISSUE_FILL = PatternFill("solid", fgColor="FFFF0000")
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)


def _headers(display_volume):
    return [
        "FG part number", "Assembly", "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number",
        "Unit", "Part Qty", f"Ext Vol Qty #{display_volume}", f"Price (Splits) #{display_volume} (Conv.)",
        f"Price #{display_volume} (Original)", "Currency (Original)", f"Ext Price (Splits) #{display_volume} (Conv.)",
        f"Ext Part Vol Price (Splits) #{display_volume} (Conv.)", "Supp Name", "Pkg Qty", "MOQ", "Lead Time",
        "NRE Charge", "NRE Charge (Conv.)", "NCNR", "Price Control", "Long Comment", "Price Type", "Exp Date",
        "MFR in Customer BOM", "Corrected MPN", "End Use Statement", "Supplier Type", "Line No.", "Is Data",
        "Batch Qty", "Is Assembly", "Parent Line No.", "ABC Classification", "Scrap", "New Supp", "Is Price Same",
        "Is MPN Same", "Is Costed", "Recurring Count", "Mfg. Part Num in Scrub Bom", "MOQ Qty Present",
        "Pkg Qty Present", "PKg Qty <= MOQ", "Assembly+Parent Line", "Part Num+Line", "FG Part Qty",
        "FG Ext Price (Conv.)",
    ]


def _find_volume(volumes, volume):
    for v in volumes or []:
        if v.get("volume") == volume:
            return v
    return None


def _spacer_row():
    row = [""] * NUM_COLS
    row[0] = " "
    return row


def _data_row(item, assembly, v):
    # v.get("ABC_classification", "")/v.get("scrap_percent", "") below (columns 36/37,
    # AJ/AK) are placeholders only -- build_cbom_vl_sheet()'s per-row formula overlay
    # always overwrites them with a live MATCH/INDEX lookup against the hidden "Scrap
    # Factor" sheet, same treatment as AM/AN/AO/AP. v.get("batch_qty", "") (column 33,
    # AG) is likewise a placeholder only -- overwritten with a live recursive
    # FG/Assembly/Part-Number lookup against the hidden "Batch Settings" sheet.
    v = v or {}
    return [
        item.get("FG", ""), assembly, item.get("CPN", ""), item.get("part_description", ""), item.get("commodity", ""),
        v.get("manufacturerName", ""), v.get("MPN", ""), v.get("UOM", ""), item.get("part_qty", ""),
        v.get("ext_vol_qty", ""), v.get("price_conv", ""), v.get("price_original", ""), v.get("currency", ""),
        v.get("ext_price_conv", ""), v.get("ext_part_vol_price_conv", ""), v.get("supplierName", ""),
        v.get("packageQty", ""), v.get("MOQ", ""), v.get("leadTime", ""), v.get("nre_charge", ""), v.get("nre_charge_conv", ""),
        v.get("NCNR", ""), v.get("price_control", ""), v.get("long_comment", ""), v.get("price_type", ""),
        v.get("expiry_date", ""), v.get("MFRinScrubBOM"), v.get("corrected_mpn", ""), item.get("end_use_statement", ""),
        v.get("supplierType", ""), item.get("line_no", ""), v.get("isData", ""), v.get("batch_qty", ""),
        item.get("isAssembly", ""), item.get("parent_line_no", ""), v.get("ABC_classification", ""), v.get("scrap_percent", ""),
        item.get("new_supplier", ""), item.get("isPriceSame", ""), item.get("isMPNSame", ""), v.get("isCosted", ""),
        item.get("recurring_count", ""), item.get("isMFGpartNumberInScrubBOM", ""), v.get("isMoqPresent", ""),
        v.get("isPkgQtyPresent", ""),
        v.get("pckQtyVsMoq", ""), "", "", item.get("fg_part_qty", ""),
        "",  # FG Ext Price (Conv.) -- 100% live formula (AW x K), no Python-side value
    ]


def _assembly_label(assembly, fg, item):
    group_path = item.get("assembly_group_path") or item.get("group_path")
    if group_path:
        return f"*** Assembly: {assembly} Line#{group_path}"
    return f"*** Assembly: {assembly} || FG: {fg}"


def cbom_vl_rows(data, volume):
    """Port of CBOMVolumeSheetExcelFormula::generateRows(): the full 2D sheet layout.

    data: cbomJson — {"project_name", "summary": [...], "hierarchical_order": [...]?,
        <assembly>: {<fg>: [items...]}, ...}
    volume: int volume number, or the string 'proto'.
    returns: list of rows (each a list of NUM_COLS values).
    """
    project_name = data.get("project_name", "")
    display_volume = "1" if volume == "proto" else str(volume)

    top_section = [
        ["", "", "Awards Costed BOM", "", "", ""],
        ["", "", "Template:", "", "", "Centum Costed BOM_Internal"],
        ["", "", "Project:", "", "", f"{project_name} - VOL - {volume}"],
        ["", "", "Volume:", "", "", str(volume)],
        ["", "", "Currency:", "", "", "USD"],
        ["", "", "Report On:", "", "", "Selected Cost"],
        ["", "", "Sort By:", "", "", "Part Number"],
        ["", "", "*** Assembly Summary"],
        ["", "", "Assembly", "Description", f"Ext Price #{display_volume} (Conv.)",
         f"Ext Vol Qty #{display_volume}", f"Ext Part Vol Price #{display_volume} (Conv.)", "Batch Qty"],
    ]

    summary = data.get("summary", [])
    ext_price_conv_total = 0
    ext_part_vol_price_total = 0
    for item in summary:
        vol = _find_volume(item.get("volumes"), volume) or {}
        ext_price_conv_total += vol.get("ext_price_conv", 0) or 0
        ext_part_vol_price_total += vol.get("ext_part_vol_price_conv", 0) or 0
        top_section.append([
            "", "", item.get("FG", ""), item.get("Description", ""),
            vol.get("ext_price_conv", ""), vol.get("ext_vol_qty", ""),
            vol.get("ext_part_vol_price_conv", ""), vol.get("batch_qty", ""),
        ])
    top_section.append(["", "", "TOTAL", "", ext_price_conv_total, "", ext_part_vol_price_total, ""])

    top_section_count = len(top_section)
    # ponytail: floor was a hardcoded "23" guess; the real constraint is that
    # the assembly block can't start before the Validation table (J10:K17,
    # 9 + len(_VALIDATION_LABELS) rows) ends -- verified against the
    # reference workbook (8-row table -> last padding row 17, block starts 18).
    start_data_row = max(top_section_count + 2, 9 + len(_VALIDATION_LABELS))
    padding = [_spacer_row() for _ in range(start_data_row - top_section_count)]

    headers = _headers(display_volume)
    rows = []

    hierarchy_order = data.get("hierarchical_order") or []
    if hierarchy_order:
        last_assembly_key = None
        for node in hierarchy_order:
            fg, assembly, cpn = node.get("fg", ""), node.get("assembly", ""), node.get("cpn", "")
            if not fg or not assembly or not cpn:
                continue
            items = (data.get(assembly) or {}).get(fg)
            if not items:
                continue
            item = next((it for it in items if it.get("CPN") == cpn), None)
            if not item:
                continue

            assembly_key = f"{assembly}||{fg}"
            if last_assembly_key != assembly_key:
                if last_assembly_key is not None:
                    rows.append(_spacer_row())
                    rows.append(_spacer_row())
                rows.append([_assembly_label(assembly, fg, item)])
                rows.append(list(headers))
                last_assembly_key = assembly_key

            v = _find_volume(item.get("volumes"), volume)
            rows.append(_data_row(item, assembly, v))

        if last_assembly_key is not None:
            rows.append(_spacer_row())
            rows.append(_spacer_row())
    else:
        fg_to_assemblies = {}
        for assembly, fg_groups in data.items():
            if assembly in _RESERVED_KEYS:
                continue
            for fg in fg_groups:
                fg_to_assemblies.setdefault(fg, []).append(assembly)

        for fg in sorted(fg_to_assemblies):
            for assembly in sorted(fg_to_assemblies[fg]):
                items = (data.get(assembly) or {}).get(fg, [])
                sample_item = items[0] if items else {}
                rows.append([_assembly_label(assembly, fg, sample_item)])
                rows.append(list(headers))
                for item in items:
                    v = _find_volume(item.get("volumes"), volume)
                    rows.append(_data_row(item, assembly, v))
                rows.append(_spacer_row())
                rows.append(_spacer_row())

    return top_section + padding + rows


def cbom_vl_bounds(data, volume):
    """Computes the same (first_data_row, last_data_row) that consumers elsewhere
    (aclass_parts.py, ex_inv_vl.py, sum_and_count_detailed.py) used to compute at
    Excel runtime via two full-column scans against a '7.0 CBOM VL-{n}' sheet:
    MATCH("Part Number", $C:$C, 0)+1 (first real data row, right after this sheet's
    first assembly-block header row) and LOOKUP(2, 1/($C:$C<>""), ROW($C:$C)) (last
    row with a non-blank Part Number). Both scanned up to 1,048,576 rows per formula
    at Excel-open time; this computes the identical values once in Python, from the
    exact same row layout cbom_vl_rows()/build_cbom_vl_sheet() write, before those
    sheets are actually built (see exporter.py).

    Returns (0, 0) if the sheet would have no assembly-block data at all (matching
    the original formulas' own IFERROR fallback behavior on a sheet with no match).
    """
    rows = cbom_vl_rows(data, volume)
    header_row = None
    last_row = 0
    for i, row in enumerate(rows):
        c_val = row[2] if len(row) > 2 else ""
        if header_row is None and c_val == "Part Number":
            header_row = i + 1  # 1-indexed physical row of the header
        if c_val not in (None, ""):
            last_row = i + 1  # 1-indexed physical row; keeps advancing to the last non-blank
    first_data_row = (header_row + 1) if header_row is not None else 0
    return first_data_row, last_row


def _style_range(ws, start_row, end_row, start_col, end_col, fill, font=None):
    for row in range(start_row, end_row + 1):
        for col in range(start_col, end_col + 1):
            cell = ws.cell(row=row, column=col)
            cell.fill = fill
            cell.border = _THIN_BORDER
            if font is not None:
                cell.font = font


def _apply_number_format(ws, col, row1, row2, fmt):
    for row in range(row1, row2 + 1):
        ws.cell(row=row, column=col).number_format = fmt


def build_scrap_factor_sheet(wb):
    """Creates the hidden "Scrap Factor" configuration sheet -- one row per active tier
    from scrap_factor.get_scrap_factor_table() (Postgres logic_db.scrap_factor_settings,
    the single source of truth the whole pipeline reads from; see that module's own
    docstring). CBOM VL-n sheets' ABC Classification/Scrap columns look values up
    against this sheet live via MATCH/INDEX (see the AJ/AK overlay in
    build_cbom_vl_sheet() below) instead of any hardcoded threshold/class/percentage --
    changing a tier only means editing this table's backing DB rows, never this code.

    Ordered by min_price ASCENDING (the opposite of build_scrap_class_case_sql()'s own
    descending SQL walk) -- MATCH's approximate-match mode (match_type=1) requires its
    lookup array sorted ascending, and relies on that ordering plus contiguous,
    gap-free tiers to correctly implement "min inclusive, max exclusive" bucketing:
    MATCH returns the position of the largest value <= the lookup price.

    Hidden via ws.sheet_state -- an internal config table, not something an end user
    should see or edit inside the exported workbook itself. Built once per export
    (exporter.py calls this before its per-volume CBOM VL sheet loop), not once per
    volume -- every "7.0 CBOM VL-n"/"7.0 CBOM Proto" sheet references this same sheet.
    """
    ws = wb.create_sheet(title="Scrap Factor")
    ws.append(["Min Price", "Max Price", "Scrap Class", "Scrap Percentage"])
    for tier in get_scrap_factor_table():
        ws.append([tier["min_price"], tier["max_price"], tier["scrap_class"], tier["scrap_percent"]])
    _style_range(ws, 1, 1, 1, 4, _HEADER_FILL, _HEADER_FONT)
    if ws.max_row >= 2:
        _apply_number_format(ws, 4, 2, ws.max_row, "0.00%")
    for col_idx in range(1, 5):
        ws.column_dimensions[get_column_letter(col_idx)].width = 14
    ws.sheet_state = "hidden"
    return ws


def build_batch_settings_sheet(wb, data):
    """Creates the hidden "Batch Settings" configuration sheet -- one row per (FG,
    Volume) pair, across EVERY detected volume (not just one), since this sheet is
    built once for the whole workbook while build_cbom_vl_sheet() runs once per volume.
    Sourced from data["summary"] (cbomJson's own per-FG list, each already carrying a
    "volumes" list with that FG's own batch_qty per volume -- the exact same value
    cbom_vl_rows()'s own Assembly Summary block displays in column H for whichever
    volume that specific sheet covers; see excel_mappings.py::to_cbom_tree_payload()).

    Every top-level component's own live Batch Qty (AG) formula (see the per-row
    overlay in build_cbom_vl_sheet()) reads its ROOT input from this sheet instead of a
    static Python value -- changing an FG's Batch Qty here recalculates every
    component's Batch Qty beneath it, throughout the whole hierarchy.

    Columns: FG | Volume | Batch Qty | FG|Volume (a precomputed helper key -- avoids
    needing an array-entered/CSE MATCH against a live-concatenated FG&"|"&Volume range,
    which isn't safely portable across Excel versions without explicit array entry).

    Hidden via ws.sheet_state -- an internal config table, not something an end user
    should see or edit inside the exported workbook itself (unhiding it is exactly how
    a user would change an FG's Batch Qty and have Excel recalculate the column).
    """
    ws = wb.create_sheet(title="Batch Settings")
    ws.append(["FG", "Volume", "Batch Qty", "FG|Volume"])
    for item in data.get("summary", []):
        fg = item.get("FG", "")
        for vol in item.get("volumes") or []:
            vol_no = vol.get("volume")
            ws.append([fg, str(vol_no), vol.get("batch_qty") or 0, f"{fg}|{vol_no}"])
    _style_range(ws, 1, 1, 1, 4, _HEADER_FILL, _HEADER_FONT)
    for col_idx in range(1, 5):
        ws.column_dimensions[get_column_letter(col_idx)].width = 18
    ws.sheet_state = "hidden"
    return ws


def build_cbom_vl_sheet(wb, data, volume, expected_row_count=None):
    """Port of CBOMVolumeSheetExcelFormula: writes and styles a '7.0 CBOM VL-n' sheet.

    wb: an openpyxl.Workbook to append the sheet to.
    data: the same cbomJson payload passed to cbom_vl_rows().
    volume: int volume number, or 'proto'.
    expected_row_count: optional -- the row count exporter.py computed early (via its
        own call to cbom_vl_rows()/cbom_vl_bounds()) and already threaded into other
        sheets' cross-references to this one. cbom_vl_rows() is a pure function of
        (data, volume), so calling it again here is guaranteed to reproduce the same
        result -- this assert exists purely as a guard rail against a future code
        change accidentally breaking that guarantee (e.g. filtering `rows` after this
        point), which would otherwise silently under-bound every formula elsewhere in
        the workbook pointing at this sheet (see EXCEL_LOAD_PERFORMANCE.md's own
        "most dangerous failure mode" warning).
    """
    title = "7.0 CBOM Proto" if volume == "proto" else f"7.0 CBOM VL-{volume}"
    rows = cbom_vl_rows(data, volume)
    if expected_row_count is not None:
        assert len(rows) == expected_row_count, (
            f"{title}: expected {expected_row_count} rows (threaded into other sheets' "
            f"cross-references), but cbom_vl_rows() produced {len(rows)} -- would silently "
            f"under/over-bound every formula elsewhere in the workbook pointing at this sheet."
        )

    ws = wb.create_sheet(title=title)
    for row in rows:
        ws.append(row)

    summary = data.get("summary", [])
    summary_header_row = 9
    summary_data_start = 10
    summary_data_end = summary_data_start + len(summary) - 1
    total_row = summary_data_end + 1

    _style_range(ws, summary_header_row, summary_header_row, 3, 8, _HEADER_FILL, _HEADER_FONT)
    if summary_data_end >= summary_data_start:
        _style_range(ws, summary_data_start, summary_data_end, 3, 8, _NO_FILL)
    _style_range(ws, total_row, total_row, 3, 8, _TOTAL_FILL)

    # total_row == top_section_count (both equal 10 + len(summary)) -- so this
    # reproduces cbom_vl_rows()'s own start_data_row without threading it through.
    # Computed here (rather than just before its first use further below) so the
    # Assembly Summary block's own formulas, next, can also be bounded by it instead
    # of scanning full columns.
    start_data_row = max(total_row + 2, 9 + len(_VALIDATION_LABELS))
    first_data_row = start_data_row + 1
    last_data_row = len(rows)

    # Assembly Summary block -- Ext Price (E): cbom_vl_rows() writes a static
    # placeholder value into this cell (top_section, from data["summary"]'s per-FG
    # ext_price_conv -- see excel_mappings.py::to_cbom_tree_payload()); overwritten
    # below with a live per-FG SUMIFS formula, per explicit business-rule request
    # ("CBOM Summary" FG Total Cost must be calculated dynamically) -- so editing a
    # price/quantity elsewhere on this sheet recalculates this total live instead of
    # requiring Python regeneration. Ext Part Vol Price (G) is UNCHANGED (still the
    # static placeholder from cbom_vl_rows(), not part of this specific request) --
    # only Ext Price (E) becomes a live formula.
    #
    # =SUMIFS($AX-range, $A-range, $C{row}, $AH-range, "<>TRUE") -- sums column AX
    # ("FG Ext Price (Conv.)", = FG Part Qty (AW) x Price Conv (K), see the per-row
    # overlay above) for every row anywhere under this FG (column A -- regardless of
    # nesting depth) whose Is Assembly (AH) is not TRUE.
    #
    # This replaced two earlier attempts, both confirmed wrong by direct real-data
    # verification (RFQ-000042's BJ26901B, ref $872.72; RFQ-000032's
    # LM2853-243695-006, ref $880.51):
    #   1. `=SUMIFS($N-range, $A-range, $C{row})` (FG column, no Is-Assembly filter):
    #      DOUBLE-COUNTS whenever a structural sub-assembly's own row has a
    #      price-rollup value (see excel_mappings.py's _structural_rollup()) -- both
    #      that row's own (correctly FG-qty-weighted) Ext Price AND its children's
    #      rows get summed. BJ26901B: $1,291.22 (+47.9%).
    #   2. `=SUMIFS($N-range, $B-range, $C{row})` (Assembly column, top-level only):
    #      only sums rows whose IMMEDIATE parent is the FG directly, silently
    #      excluding everything nested under any intermediate sub-assembly. Happens
    #      to be numerically close when every sub-assembly sits at the top level and
    #      its own rollup is complete, but its correctness is CONTINGENT on that
    #      rollup succeeding at every intermediate level -- a partial/failed rollup
    #      anywhere silently drops that whole subtree's cost.
    #   3. `=SUMIFS($N-range, $A-range, $C{row}, $AH-range, "<>TRUE")` (FG column,
    #      WITH Is-Assembly excluded): closer, but N = Part Qty (I, the row's LOCAL
    #      quantity relative to its immediate parent) x K -- correct only when I
    #      already equals the true FG-wide quantity, i.e. when nothing between this
    #      row and the FG root is used more than once. UNDERCOUNTS any row nested
    #      under a sub-assembly used multiple times within the FG (e.g. BJ26901B's
    #      RXLRBL0267, used 4x, and RXLRBL0195, used 2x -- their children's Part Qty
    #      is LOCAL to one instance of the parent, not multiplied up). BJ26901B:
    #      $793.38 (-9.09%).
    #
    # column AX fixes this by summing AW (FG Part Qty = Part Qty x this row's
    # CUMULATIVE hierarchy_multiplier, confirmed in scrub_bom_processing.py's
    # _build_hierarchy_multipliers() to compound across the ENTIRE ancestor chain up
    # to the FG root, not just one level) x K instead of I x K -- so a leaf part's
    # contribution is correctly weighted by how many times ALL of its ancestor
    # sub-assemblies are used, regardless of nesting depth, without depending on any
    # intermediate structural row's own price rollup being complete. Sources cost
    # directly from purchased/leaf rows (which always carry a genuine quoted price)
    # -- the same AW+"Is Assembly<>TRUE" pattern reports/aclass_parts.py already
    # relies on for its own "Part Qty" column. Verified: reproduces $891.33 (+2.13%)
    # for BJ26901B and the exact $880.51 (0% gap) for LM2853-243695-006 (a deeply
    # nested FG with no repeated sub-assemblies, where all candidate formulas agree).
    if summary_data_end >= summary_data_start:
        for _i in range(len(summary)):
            _summary_row = summary_data_start + _i
            ws.cell(row=_summary_row, column=5).value = (
                f'=SUMIFS($AX${first_data_row}:$AX${last_data_row}, '
                f'$A${first_data_row}:$A${last_data_row}, $C{_summary_row}, '
                f'$AH${first_data_row}:$AH${last_data_row}, "<>TRUE")'
            )
            ws.cell(row=_summary_row, column=7).value = f'=F{_summary_row}*E{_summary_row}'
        ws.cell(row=total_row, column=5).value = f'=SUM(E{summary_data_start}:E{summary_data_end})'
        ws.cell(row=total_row, column=7).value = f'=SUM(G{summary_data_start}:G{summary_data_end})'

    # Currency conversion table -- dynamic length (admin can add/remove currencies via
    # Settings -> Currencies), not hardcoded to exactly 3 rows. currency_table_last_row
    # is threaded through to the per-row Price Splits (K) and NRE Charge (Conv.) (U)
    # formula overlays below, which INDEX/MATCH against this same J:K range.
    ws["J1"], ws["K1"] = "Currency", "Value"
    _rates = get_currency_rates()
    for _i, (_code, _rate) in enumerate(_rates.items()):
        ws[f"J{2 + _i}"], ws[f"K{2 + _i}"] = _code, _rate
    currency_table_last_row = 1 + len(_rates)
    # Quote-currency reference cell -- formulas below read this instead of a baked-in
    # literal, so the sheet is self-documenting about which currency it was generated
    # for, and matches today's exact behavior when it's USD (rate 1.0).
    ws["M1"], ws["N1"] = "Quote Currency", get_default_quote_currency()
    # Scrap Factor sheet's own data range (row 1 header, rows 2..N one per active tier) --
    # threaded into the AJ/AK MATCH/INDEX overlay below. Calling get_scrap_factor_table()
    # again here (rather than accepting a row count as a parameter) is safe: it's
    # cached for the run and build_scrap_factor_sheet() (called once, before the
    # per-volume loop -- see exporter.py) wrote exactly one row per element of that
    # same cached list, so the two counts can never diverge.
    scrap_last_row = 1 + len(get_scrap_factor_table())
    # Batch Settings sheet's own data range (row 1 header, one row per (FG, Volume) pair
    # across EVERY detected volume -- not just this sheet's own volume) -- threaded into
    # the Batch Qty (AG) top-level-parent lookup below. Recomputed here from `data`
    # (the exact same cbomJson payload build_batch_settings_sheet() itself iterates,
    # called once before the per-volume loop -- see exporter.py) rather than passed as a
    # parameter, so the two counts can never diverge, same reasoning as scrap_last_row.
    batch_settings_last_row = 1 + sum(len(item.get("volumes") or []) for item in data.get("summary", []))
    _style_range(ws, 1, 1, 10, 11, _HEADER_FILL, _HEADER_FONT)
    _style_range(ws, 2, max(4, currency_table_last_row), 10, 10, _NO_FILL)
    _style_range(ws, 2, max(4, currency_table_last_row), 11, 11, _TOTAL_FILL)

    # Validation/Status (J9:K17) and MOQ Cost (M9:M11) -- live formulas,
    # transcribed byte-for-byte from the reference workbook's real cells
    # (not re-derived), with the two hardcoded absolute bounds ($AP$18:$AP$106
    # etc. in the reference, which is just *that* file's own fixed data
    # range) replaced by this sheet's own dynamic first/last per-part-row
    # bounds, and the reference's hardcoded 'Ex Inv VL-1' cross-sheet ref
    # replaced by this volume's own Ex Inv VL sheet name.
    ws["J9"], ws["K9"] = "Validation", "Status"
    _style_range(ws, 9, 9, 10, 11, _HEADER_FILL, _HEADER_FONT)
    for i, label in enumerate(_VALIDATION_LABELS):
        ws.cell(row=10 + i, column=10, value=label)
    _style_range(ws, 10, 9 + len(_VALIDATION_LABELS), 10, 10, _NO_FILL)
    _style_range(ws, 10, 9 + len(_VALIDATION_LABELS), 11, 11, _TOTAL_FILL)

    # start_data_row/first_data_row/last_data_row were already computed above (needed
    # earlier for the Assembly Summary block's own bounded formulas).
    ws.cell(row=10, column=11).value = (
        f'=SUMPRODUCT(($AP${first_data_row}:$AP${last_data_row}=1)*'
        f'($C${first_data_row}:$C${last_data_row}<>""))'
    )
    ws.cell(row=11, column=11).value = "=K10-K12"
    ws.cell(row=12, column=11).value = (
        f'=SUMPRODUCT(($AP${first_data_row}:$AP${last_data_row}=2)*'
        f'($C${first_data_row}:$C${last_data_row}<>""))'
    )
    ws.cell(row=13, column=11).value = "=K14-K11"
    ws.cell(row=14, column=11).value = (
        f'=SUMPRODUCT(--(($AF${first_data_row}:$AF${last_data_row}=TRUE)+'
        f'($AF${first_data_row}:$AF${last_data_row}="TRUE")+'
        f'($AF${first_data_row}:$AF${last_data_row}=FALSE)+'
        f'($AF${first_data_row}:$AF${last_data_row}="FALSE")>0))'
    )
    # Uncosted Line Items Count: a plain, un-deduped count of real data rows with Is
    # Costed=FALSE -- same grain as Total Line Items (K14) above, matching the
    # business-rule spec confirmed against the Lam Research reference workbook
    # (Test_fixes/validation_files): "filter using Is Assembly and Is Costed to
    # determine genuinely uncosted rows", no CPN-level dedup. An EARLIER pass at this
    # fix added a Recurring Count = 1 dedup gate (matching K10/K12/K16/K17's own
    # distinct-CPN counting pattern) based on a coincidental near-match (55 vs a
    # reference target of 54) -- that was the wrong grain: the reference's own 847-row
    # sheet is already at (FG, Assembly, CPN) combo grain (confirmed: verified 320 rows
    # = 320 distinct (assembly, cpn) pairs for one FG), and its own Uncosted count (54)
    # is a plain row-level COUNTIFS over that same grain, not further deduped by CPN.
    # Is Assembly (AH) is not referenced here because no row on this sheet is ever
    # Is Assembly=TRUE in the first place -- to_cbom_tree_payload() only ever builds
    # is_data rows into items (see its own `data = cbom_df[cbom_df["is_data"]]`
    # filter); the FG's own root/self-referencing row never becomes a line item here at
    # all (same reason Total Line Items is 843, not 847 -- see that K14 comment).
    ws.cell(row=15, column=11).value = (
        f'=COUNTIFS($AO${first_data_row}:$AO${last_data_row},FALSE,'
        f'$AF${first_data_row}:$AF${last_data_row},TRUE,'
        f'$AH${first_data_row}:$AH${last_data_row},"<>TRUE")'
    )
    ws.cell(row=16, column=11).value = (
        f'=SUMPRODUCT(($AM${first_data_row}:$AM${last_data_row}=FALSE)*'
        f'($AP${first_data_row}:$AP${last_data_row}=1)*'
        f'--(($AF${first_data_row}:$AF${last_data_row}=TRUE)+'
        f'($AF${first_data_row}:$AF${last_data_row}="TRUE")+'
        f'($AF${first_data_row}:$AF${last_data_row}=1)>0))'
    )
    ws.cell(row=17, column=11).value = (
        f'=SUMPRODUCT(($AN${first_data_row}:$AN${last_data_row}=FALSE)*'
        f'($AP${first_data_row}:$AP${last_data_row}=1)*'
        f'--(($AF${first_data_row}:$AF${last_data_row}=TRUE)+'
        f'($AF${first_data_row}:$AF${last_data_row}="TRUE")+'
        f'($AF${first_data_row}:$AF${last_data_row}=1)>0))'
    )
    # ponytail: the "is a real data row" test below (AF=TRUE / ="TRUE" / =1) is the exact
    # same triple-check already used for K16/K17 above -- kept identical for consistency,
    # not reinvented.
    _is_data_test = (
        f'(($AF${first_data_row}:$AF${last_data_row}=TRUE)+'
        f'($AF${first_data_row}:$AF${last_data_row}="TRUE")+'
        f'($AF${first_data_row}:$AF${last_data_row}=1)>0)'
    )
    ws.cell(row=18, column=11).value = (
        f'=SUMPRODUCT(($AQ${first_data_row}:$AQ${last_data_row}=FALSE)*{_is_data_test})'
    )
    # MOQ Missing Count / SPQ Missing Count / PKG > MOQ: confirmed against the Lam
    # Research reference workbook (Test_fixes/validation_files) that these must read
    # the pre-computed presence/comparison FLAG columns (AR "MOQ Qty Present", AS "Pkg
    # Qty Present", AT "PKg Qty <= MOQ" -- moq_qty_present/pkg_qty_present/
    # pkg_qty_lte_moq from queries.py), not a raw blank/comparison check on Q (Pkg Qty)
    # / R (MOQ) directly. Those flags encode extra business logic a bare blank-check
    # misses: moq_qty_present is FALSE for MOQ=0 (present but non-positive), not just
    # blank MOQ, and pkg_qty_lte_moq is FALSE whenever EITHER side is missing, not only
    # when both are present and Pkg Qty > MOQ. A bare "$Q<>"" and $R<>"" and $Q>$R" (the
    # previous approach here) silently missed both of those cases, undercounting
    # relative to the reference.
    ws.cell(row=19, column=11).value = (
        f'=SUMPRODUCT(($AR${first_data_row}:$AR${last_data_row}=FALSE)*{_is_data_test})'
    )
    ws.cell(row=20, column=11).value = (
        f'=SUMPRODUCT(($AS${first_data_row}:$AS${last_data_row}=FALSE)*{_is_data_test})'
    )
    ws.cell(row=21, column=11).value = (
        f'=SUMPRODUCT(($AT${first_data_row}:$AT${last_data_row}=FALSE)*{_is_data_test})'
    )
    ws.cell(row=22, column=11).value = (
        f'=SUMPRODUCT({_is_data_test}*'
        f'(($E${first_data_row}:$E${last_data_row}="")+ISBLANK($E${first_data_row}:$E${last_data_row})>0))'
    )
    # Uncosted Line Items Count (row 15) through Commodity Missing Count (row 22): flag
    # any nonzero count in red -- these 8 rows are all "should be 0 in a clean BOM"
    # exception counts, unlike rows 10-14 above (structural CPN-sharing counts, which
    # are normal/expected to be nonzero).
    ws.conditional_formatting.add(
        "K15:K22", FormulaRule(formula=["K15>0"], fill=_ISSUE_FILL)
    )

    ws["M10"] = "MOQ Cost"
    _style_range(ws, 10, 10, 13, 13, _HEADER_FILL, _HEADER_FONT)
    ex_inv_sheet = "Ex Inv VL-proto" if volume == "proto" else f"Ex Inv VL-{volume}"
    ws.cell(row=11, column=13).value = f"=IFERROR('{ex_inv_sheet}'!$A$2, 0)"
    ws.cell(row=11, column=13).fill = _TOTAL_FILL
    ws.cell(row=9, column=13).value = f"=IFERROR($M$11/G{total_row},0)"
    ws.cell(row=9, column=13).fill = _TOTAL_FILL
    ws.cell(row=9, column=13).number_format = "0.00%"
    _apply_number_format(ws, 13, 11, 11, '"$"General')

    # Assembly block detection & styling — mirrors the PHP scan over column A,
    # done directly against `rows` since we built them ourselves. Also overlays the live
    # formulas the shipped PHP writes on every real data row, transcribed byte-for-byte
    # from a real generated workbook (not re-derived independently), per the project's
    # "prefer an existing reference formula over deriving a new one" rule.
    #
    # Three columns are a DELIBERATE EXCEPTION, not a faithful copy of the reference's own
    # formula:
    #   - Part Qty (I), FG Part Qty (AW), Ext Vol Qty (J): the reference workbook's real
    #     formulas for these recursively chain through Assembly+ParentLine/PartNum+Line
    #     matches, rooted in a dot-hierarchical "Line No." string (e.g. "2.1.3") that
    #     encodes true BOM nesting depth. Our scrub_bom_items schema has no such
    #     hierarchical line-numbering (only a flat item_number) -- copying that recursive
    #     formula verbatim would produce false/circular matches, not a working workbook.
    #     All three are LITERAL values (not live same-sheet formulas), computed directly
    #     from Scrub BOM.
    #
    #     This sheet shows one row per (Assembly, FG, Part Number): every recurring Scrub
    #     BOM line sharing that exact (Assembly, FG, Part Number) is collapsed into that one
    #     row (with a per-volume `volumes` list, not a per-occurrence row) -- confirmed
    #     against real data: one CPN recurring 54 times in Scrub BOM within a single
    #     sub-assembly still produces just one CBOM VL row. A live same-sheet
    #     COUNTIFS/SUMIFS formula was tried first but VERIFIED WRONG: it can only ever see 1
    #     matching row per (Assembly, FG, Part Number) on this sheet, not the true multi-row
    #     Scrub BOM sum, so it would silently disagree with the correct backend value.
    #
    #     - Part Qty (I): the LOCAL quantity for THIS ROW's specific (Assembly, FG, Part
    #       Number) occurrence -- excel_export_adapters.fg_assembly_part_qty_sums().
    #     - FG Part Qty (AW), Ext Vol Qty (J): each equal to Part Qty (I) x this assembly's
    #       own hierarchy_multiplier, then x this FG's own Ext Vol Qty input where
    #       applicable -- NOT a blind copy of Part Qty, and NOT (for AW) the old
    #       sum-across-every-sub-assembly-in-the-FG total. Confirmed against the Lam
    #       Research reference workbook (Test_fixes/validation_files): for
    #       FG=LM2853-A93171-002, Assembly=LM2910-A66420-001 (hierarchy_multiplier=2.0, Part
    #       Qty=1, FG demand=608), the reference shows FG Part Qty=2 and Ext Vol Qty=1216 (=
    #       1 x 2 x 608), not 1 and 608. Without the multiplier, A CLASS PARTS' own
    #       SUMIFS-over-AW/J totals (I1/K1, matched by Part Number only, across every
    #       FG/assembly) silently disagreed with this sheet's own Assembly Summary TOTAL
    #       (which already applies this same multiplier when accumulating
    #       fg_vol_ext_price_sum/fg_vol_ext_part_vol_price_sum).
    #     Both are already correct and written by _data_row() via item["part_qty"] (I),
    #     item["fg_part_qty"] (AW), v["ext_vol_qty"] (J); neither is overwritten with a
    #     formula here.
    #
    # (Ext Vol Qty/J previously WAS a live formula here -- a non-recursive reproduction of
    # the reference's "$AE=$AI always true" fallback branch, computing Part Qty x this
    # row's FG's own Assembly Summary Ext Vol Qty input with no multiplier factor, since
    # Excel had no per-row hierarchy_multiplier column to reference live. Removed once the
    # backend literal above needed the multiplier and Excel had no way to express it --
    # same treatment as the Assembly Summary block's own Ext Price/Ext Part Vol Price fix.)
    #
    # Batch Qty (AG) is DIFFERENT from the three above -- it IS a live formula (see the
    # per-row overlay below), because unlike Part Qty/FG Part Qty/Ext Vol Qty it does NOT
    # need the reference's dot-hierarchical Line No. or a per-row hierarchy_multiplier at
    # all: the business rule ("every component inherits the Batch Qty of its immediate
    # parent: Component Batch Qty = Component Qty x Parent Batch Qty, recursively") can be
    # expressed directly from columns already on this sheet -- FG (A), Assembly (B), Part
    # Number (C) -- without any dotted line numbering. A row's immediate parent is either
    # the Finished Good itself (when Assembly (B) == FG (A), the scrub_bom_processing.py
    # convention for a top-level component -- see _build_hierarchy_multipliers()'s own
    # "up to the FG root (where cpn == fg == assembly)") or another row in the same FG
    # whose own Part Number (C) equals this row's Assembly (B) (a structural sub-assembly
    # CPN's own defining row). Excel resolves cell dependencies regardless of physical row
    # order, so a child row's formula can safely reference its parent row's own AG cell
    # even when the parent's block appears later on the sheet -- no manual "calculate
    # parent first" ordering is needed, only that the BOM itself has no circular assembly
    # reference (same non-cyclic assumption _build_hierarchy_multipliers() already relies
    # on, with the identical real-data justification: no assembly-role CPN has more than
    # one distinct parent within the same FG).
    #
    # Column positions match this sheet's own _headers() layout: A=1, B=2, C=3, F=6, G=7,
    # H=8, I=9, J=10, K=11, M=13, N=14, O=15, Q=17, R=18, T=20, AE=31, AF=32, AG=33, AH=34,
    # AI=35, AK=37, AM=39, AN=40, AO=41, AP=42, AR=44, AS=45, AT=46, AU=47, AV=48, AW=49.
    r = 0
    while r < len(rows):
        label = rows[r][0] if rows[r] else ""
        if isinstance(label, str) and label.startswith("*** Assembly:"):
            header_row = r + 2
            _style_range(ws, r + 1, r + 1, 1, 1, _NO_FILL)  # title row: only column A is populated
            _style_range(ws, header_row, header_row, 1, NUM_COLS, _HEADER_FILL, _HEADER_FONT)

            data_r = header_row + 1
            empty_count = 0
            while data_r <= len(rows):
                cell_val = rows[data_r - 1][0] if rows[data_r - 1] else ""
                if cell_val is None or str(cell_val).strip() == "":
                    empty_count += 1
                    if empty_count >= 2:
                        break
                else:
                    empty_count = 0
                    _style_range(ws, data_r, data_r, 1, NUM_COLS, _NO_FILL)
                    _r = data_r
                    # Part Qty / FG Part Qty / Ext Vol Qty -- business rule: LITERAL values,
                    # not formulas -- see note above for why a live formula here would be
                    # provably wrong on this sheet's own (already-deduplicated) row layout,
                    # and why neither can be correctly reproduced as a live formula without a
                    # per-row hierarchy_multiplier column Excel has no way to reference.
                    # Columns 9 (Part Qty), 10 (Ext Vol Qty), 49 (FG Part Qty) are all
                    # literals already written by _data_row() from
                    # item["part_qty"]/v["ext_vol_qty"]/item["fg_part_qty"] -- none
                    # overwritten with a formula here.
                    # IFERROR wraps below (columns 11/21, and the multiplications in 14/15)
                    # exist because a formula's "" (blank) OUTPUT is TEXT, not a truly empty
                    # cell -- multiplying/dividing it in a downstream formula (e.g. N/O below
                    # multiplying against this row's own K) raises #VALUE!, not a graceful
                    # blank. IFERROR collapses that (and any INDEX/MATCH lookup failure, e.g.
                    # an unrecognized currency code) to blank instead, so missing/blank
                    # inputs propagate as blank output everywhere in this chain rather than
                    # surfacing an Excel error to the user.
                    # Price (Splits) (Conv.) -- 2-step conversion (source currency -> USD
                    # pivot -> configured quote currency), done live in Excel rather than
                    # Python: was a static value from _data_row()'s v.get("price_conv", "")
                    # until now. $L = Price Original, $M = Currency Original. Reduces to
                    # today's exact behavior when quote currency is USD (rate 1.0).
                    ws.cell(row=_r, column=11).value = (
                        f'=IF($AF{_r}, IFERROR(IF(OR($M{_r}="", $L{_r}=""), "", '
                        f'$L{_r}/INDEX($K$1:$K${currency_table_last_row},MATCH($M{_r},$J$1:$J${currency_table_last_row},0))'
                        f'*INDEX($K$1:$K${currency_table_last_row},MATCH($N$1,$J$1:$J${currency_table_last_row},0))), ""), "")'
                    )
                    # Ext Price / Ext Part Vol Price -- reference formula, same intent as
                    # before (Part/Ext Vol Qty x K): K (or I/J) is blank ("") whenever its own
                    # upstream row is incomplete, and blank-times-number is a #VALUE! error in
                    # Excel, not 0. Guarded with an explicit $K{_r}<>"" precondition inside
                    # AND() -- checked BEFORE the multiplication runs -- rather than an
                    # IFERROR() wrap around the multiplication itself. An IFERROR-wrapped
                    # version was tried first and looked correct in isolated testing, but did
                    # NOT fix the real #VALUE! the export was showing; only this blank-guard-
                    # first shape did. This is the established pattern for this class of bug
                    # in this file (and any sibling report builder) going forward -- guard the
                    # blank case before computing, don't compute-then-catch.
                    ws.cell(row=_r, column=14).value = f'=IF(AND($AF{_r},$K{_r}<>""),$I{_r}*$K{_r},"")'
                    ws.cell(row=_r, column=15).value = f'=IF(AND($AF{_r},$K{_r}<>""),$J{_r}*$K{_r},"")'
                    # FG Ext Price (Conv.) (AX) -- unlike Ext Price (N), which extends this
                    # row's LOCAL Part Qty (I) and therefore undercounts anything nested under
                    # a sub-assembly used more than once within the FG, this multiplies by FG
                    # Part Qty (AW) -- Part Qty x this row's cumulative hierarchy_multiplier,
                    # already correctly weighted for reuse at every ancestor level (see
                    # scrub_bom_processing.py's _build_hierarchy_multipliers()). Feeds the
                    # Assembly Summary's per-FG total below, which sums this column (not N) so
                    # a repeated sub-assembly's descendants are weighted correctly instead of
                    # relying on the sub-assembly's own row having a complete price rollup.
                    # Blank-guarded (both $K and $AW) before multiplying, same convention as
                    # the two lines above.
                    ws.cell(row=_r, column=50).value = (
                        f'=IF(AND($AF{_r},$K{_r}<>"",$AW{_r}<>""),$AW{_r}*$K{_r},"")'
                    )
                    # NRE Charge (Conv.) -- same 2-step conversion + dynamic table range as
                    # Price (Splits) (Conv.) above, for consistency (was USD-only before).
                    ws.cell(row=_r, column=21).value = (
                        f'=IF($AF{_r}, IF(OR($T{_r}="", $T{_r}=0), 0, '
                        f'IFERROR($T{_r}/INDEX($K$1:$K${currency_table_last_row},MATCH($M{_r},$J$1:$J${currency_table_last_row},0))'
                        f'*INDEX($K$1:$K${currency_table_last_row},MATCH($N$1,$J$1:$J${currency_table_last_row},0)), "")), "")'
                    )
                    # Batch Qty (AG) -- live recursive lookup, replacing _data_row()'s static
                    # v.get("batch_qty","") value (see the "DELIBERATE EXCEPTION" note above
                    # for why this one, unlike Part Qty/FG Part Qty/Ext Vol Qty, CAN be a live
                    # formula). Two cases, per the business rule ("every component inherits
                    # the Batch Qty of its immediate parent"):
                    #   - Immediate parent is the Finished Good itself ($A{_r}=$B{_r}, the
                    #     scrub_bom_processing.py top-level convention -- see
                    #     _build_hierarchy_multipliers()'s own "cpn == fg == assembly" root
                    #     check): Batch Qty = Part Qty (I) x this FG's own Batch Qty for THIS
                    #     volume, looked up from the hidden "Batch Settings" sheet (see
                    #     build_batch_settings_sheet()) via its FG|Volume helper column --
                    #     the embedded "{volume}" literal is this specific sheet's own fixed
                    #     volume (safe to bake in at generation time: one build_cbom_vl_sheet()
                    #     call always covers exactly one volume).
                    #   - Immediate parent is another row on this same sheet (a structural
                    #     sub-assembly CPN whose own Part Number (C) equals this row's
                    #     Assembly (B), within the same FG): Batch Qty = Part Qty (I) x that
                    #     parent row's OWN Batch Qty (AG) -- found via SUMPRODUCT locating the
                    #     parent's absolute sheet row (relies on the same assumption
                    #     _build_hierarchy_multipliers() already makes and confirms safe
                    #     against real data: no CPN acts as a structural parent under more
                    #     than one row within the same FG), then INDEX-ing straight into
                    #     column AG at that row -- Excel resolves this dependency regardless
                    #     of whether the parent's block is physically above or below this row.
                    #     IFERROR falls back to 0 (matching the previous Python
                    #     `(r.get("batch_qty") or 0)` fallback) if the parent row can't be
                    #     found at all (a malformed/incomplete BOM).
                    ws.cell(row=_r, column=33).value = (
                        f'=IF($AF{_r}, IF($A{_r}=$B{_r}, '
                        f'$I{_r}*IFERROR(INDEX(\'Batch Settings\'!$C$2:$C${batch_settings_last_row}, '
                        f'MATCH($A{_r}&"|"&"{volume}", \'Batch Settings\'!$D$2:$D${batch_settings_last_row}, 0)), 0), '
                        f'$I{_r}*IFERROR(INDEX($AG:$AG, IF(SUMPRODUCT(($A${first_data_row}:$A${last_data_row}=$A{_r})*'
                        f'($C${first_data_row}:$C${last_data_row}=$B{_r})*ROW($C${first_data_row}:$C${last_data_row}))>0, '
                        f'SUMPRODUCT(($A${first_data_row}:$A${last_data_row}=$A{_r})*'
                        f'($C${first_data_row}:$C${last_data_row}=$B{_r})*ROW($C${first_data_row}:$C${last_data_row})), "error")), 0)'
                        f'), "")'
                    )
                    # Is Assembly -- purely "does this row's own Part Number+Line key
                    # (AV) match some OTHER row's Assembly+Parent Line key (AU) anywhere
                    # on this sheet" -- i.e. is this CPN used as a parent/assembly value
                    # elsewhere (a structural sub-assembly identifier at any nesting
                    # level, not just the FG root). The reference formula ALSO required
                    # AND($M{_r}="", ...) -- this row's own Currency (Original) blank --
                    # under the (at the time correct) assumption that a structural CPN's
                    # own row is never priced. That assumption broke once
                    # excel_mappings.py::to_cbom_tree_payload()'s `_structural_rollup()`
                    # started giving structural CPNs a real, non-blank currency (summing
                    # their descendants' costs) -- confirmed on real data (RFQ-000042):
                    # 26 of 71 structural CPNs now carry a real currency post-rollup, and
                    # for every one of those the old $M="" clause wrongly forced Is
                    # Assembly to FALSE, letting a genuine assembly/sub-assembly row leak
                    # into every downstream consumer that filters on this column
                    # (A CLASS PARTS, Ex Inv VL, and this sheet's own Assembly Summary
                    # FG-total formula) as if it were a purchasable leaf component.
                    # Dropping the now-incorrect precondition is a strict correction, not
                    # a behavior change to the underlying MATCH mechanism -- that
                    # mechanism was already independently confirmed correct for the other
                    # 45 of 71 structural CPNs (the ones that happen to still have a
                    # blank currency), which is how this bug was isolated in the first
                    # place.
                    #
                    # SECOND correction, layered on top of the first: being structural by
                    # NAME (this MATCH mechanism) is not sufficient on its own -- a CPN can
                    # be BOTH a structural sub-assembly identifier AND independently,
                    # genuinely priced as one finished assembled unit (a "dual-role" CPN --
                    # confirmed real data, RFQ-000042: CPN "BH96568A", a "BAC TRAY" sub-
                    # assembly, has a real quoted price, while its own individual
                    # mechanical piece-parts -- cable tie mounts, screws, inserts,
                    # aluminum plate -- were never separately priced, Ext Price = 0 for
                    # every one of them). Marking such a row Is Assembly=TRUE excludes it
                    # from every downstream cost total (this sheet's own Assembly Summary
                    # FG total, A CLASS PARTS, Ex Inv VL) with NOTHING else capturing its
                    # cost -- the rollup-from-children path this codebase relies on for
                    # genuine "pure container" structural CPNs only works when the
                    # children actually carry real cost. Confirmed at scale: 17 such CPNs
                    # across 6 FGs in RFQ-000042, $681.58 silently dropped from FG totals.
                    #
                    # Second condition added: `SUMIFS($N-range, $A-range, $A{_r},
                    # $B-range, $C{_r}) <> 0` -- sums Ext Price (N) for every row in this
                    # SAME FG ($A{_r}) whose Assembly ($B) equals THIS row's own Part
                    # Number ($C{_r}), i.e. "does this CPN's own children actually carry
                    # real cost." Only TRUE (Is Assembly) when BOTH the structural-name
                    # test AND this children-cost test hold -- a genuine pure container
                    # (children carry real cost) is unaffected (unchanged from before);
                    # a dual-role CPN (children sum to zero) now correctly evaluates to
                    # Is Assembly=FALSE, so it's counted in every downstream total exactly
                    # like an ordinary purchased part, and A CLASS PARTS/Ex Inv VL's own
                    # existing `$AH<>TRUE` formulas (unchanged) correctly find and include
                    # it once this column agrees. Mirrors (must stay in lockstep with)
                    # templates/excel_mappings.py's own `_effective_structural_fg_cpns()`,
                    # the Python-side equivalent used by to_bom_matrix_payload()/
                    # to_aclass_parts_payload() (which decide row EXISTENCE up front,
                    # before this column exists to filter on).
                    ws.cell(row=_r, column=34).value = (
                        f'=IF($AF{_r}, AND(NOT(ISERROR(MATCH($AV{_r}, '
                        f'$AU${first_data_row}:$AU${last_data_row}, 0))), '
                        f'SUMIFS($N${first_data_row}:$N${last_data_row}, '
                        f'$A${first_data_row}:$A${last_data_row}, $A{_r}, '
                        f'$B${first_data_row}:$B${last_data_row}, $C{_r})<>0), "")'
                    )
                    ws.cell(row=_r, column=35).value = (
                        f'=IF($AF{_r}, IFERROR(LEFT($AE{_r}, FIND("@", SUBSTITUTE($AE{_r}, ".", "@", '
                        f'LEN($AE{_r})-LEN(SUBSTITUTE($AE{_r}, ".", ""))))-1), $AE{_r}), "")'
                    )
                    # ABC Classification (AJ) / Scrap (AK) -- live MATCH/INDEX lookups against
                    # the hidden "Scrap Factor" sheet (see build_scrap_factor_sheet()), replacing
                    # _data_row()'s static v.get("ABC_classification","")/v.get("scrap_percent","")
                    # values -- same treatment as every other formula overlay in this loop (the
                    # sheet-written static value only ever "sticks" for columns nothing here
                    # overwrites). Gated on $K{_r}<>"" (price PRESENT), not $AO (Is Costed) --
                    # deliberately NOT the same gate: Is Costed excludes a price of exactly 0
                    # (AND($K<>0, $K<>"")), but a price of 0 is real, present data that IS
                    # eligible for Scrap Class (falls into Class C, its tier's own min_price is
                    # 0.0) -- see scrap_factor.py's own docstring for why these are deliberately
                    # different concepts. Only a genuinely blank $K (no price at all) yields no
                    # class/percentage. MATCH(..., 1) on the ascending-sorted Min Price column
                    # returns the largest Min Price <= $K -- exactly "min inclusive, max
                    # exclusive" bucketing given the Scrap Factor sheet's contiguous, gap-free
                    # tiers.
                    ws.cell(row=_r, column=36).value = (
                        f'=IF($AF{_r}, IF($K{_r}<>"", IFERROR(INDEX(\'Scrap Factor\'!$C$2:$C${scrap_last_row}, '
                        f'MATCH($K{_r}, \'Scrap Factor\'!$A$2:$A${scrap_last_row}, 1)), ""), ""), "")'
                    )
                    ws.cell(row=_r, column=37).value = (
                        f'=IF($AF{_r}, IF($K{_r}<>"", IFERROR(INDEX(\'Scrap Factor\'!$D$2:$D${scrap_last_row}, '
                        f'MATCH($K{_r}, \'Scrap Factor\'!$A$2:$A${scrap_last_row}, 1)), ""), ""), "")'
                    )
                    # Is Price Same / Is MPN Same / Is Costed / Recurring Count.
                    ws.cell(row=_r, column=39).value = (
                        f'=IF($AF{_r},IF($K{_r}="",TRUE,ROUND(SUMIFS('
                        f'$K${first_data_row}:$K${last_data_row},$C${first_data_row}:$C${last_data_row},$C{_r})/'
                        f'COUNTIFS($C${first_data_row}:$C${last_data_row},$C{_r},$K${first_data_row}:$K${last_data_row},"<>"),3)=ROUND($K{_r},3)),"")'
                    )
                    # Is MPN Same: an exact compare, not COUNTIFS(G, "<>"&G): Excel reads a criterion such as "3-1953" as a DATE, so
                    # an MPN that looks like a date counted as different and Excel showed FALSE where LibreOffice and the engine
                    # showed TRUE (B17 row 30, found 2026-11-18 against a native Excel recalculation).
                    ws.cell(row=_r, column=40).value = (
                        f'=IF($AF{_r}, IF(SUMPRODUCT(($C${first_data_row}:$C${last_data_row}=$C{_r})*'
                        f'($G${first_data_row}:$G${last_data_row}<>$G{_r})) > 0, FALSE, TRUE), "")'
                    )
                    ws.cell(row=_r, column=41).value = f'=IF($AF{_r}, AND($K{_r}<>0, $K{_r}<>""), "")'
                    ws.cell(row=_r, column=42).value = f'=IF($C{_r}<>"", COUNTIF($C$1:$C{_r}, $C{_r}), "")'
                    # MOQ Qty Present (AR) / Pkg Qty Present (AS) / PKg Qty <= MOQ (AT): STATIC
                    # values from queries.py's moq_qty_present/pkg_qty_present/pkg_qty_lte_moq
                    # (already fixed to match the reference's own exemption/blank-coercion
                    # logic -- see that file's comments), left untouched here -- NOT
                    # overwritten with a live formula. A live formula previously duplicated
                    # this same exemption logic here (`OR($AH, NOT($AO))`), which made the
                    # queries.py fix a dead letter: whatever the backend computed for these
                    # three columns was immediately discarded and replaced by this formula's
                    # own (separately-derived, and for AT, NOT exemption-aware at all --
                    # `$Q<=$R` has no uncosted/assembly guard) recomputation. Same treatment
                    # as Part Qty/FG Part Qty and Ext Vol Qty/Batch Qty above.
                    # Assembly+Parent Line / Part Num+Line -- reference formula, preserved verbatim
                    # (corrects this module's earlier documentation, which had wrongly
                    # concluded -- from a shallower PHP read -- that these were always blank).
                    ws.cell(row=_r, column=47).value = f'=IF($AF{_r}, $B{_r}&"_"&$AI{_r}, "")'
                    ws.cell(row=_r, column=48).value = f'=IF($AF{_r}, $C{_r}&"_"&$AE{_r}, "")'
                data_r += 1
            r = data_r
        else:
            r += 1

    # Number formatting (Parts 2/3/4 of the formatting task): money columns get exactly
    # 4 decimal places; the Scrap percentage gets Excel percentage formatting; quantity
    # columns (Part Qty, FG Part Qty, Ext Vol Qty, Batch Qty) stay General, matching the
    # reference workbook's own formatting for those.
    _MONEY_FORMAT = '"$"#,##0.0000'
    for col_idx in (11, 12, 14, 15, 21):  # K, L, N, O, U
        _apply_number_format(ws, col_idx, 1, len(rows), _MONEY_FORMAT)
    _apply_number_format(ws, 37, 1, len(rows), "0.00%")  # AK: Scrap
    # K also holds the Validation/Status counts (K10:K17) -- General there in the
    # reference workbook, not money; reset after the blanket column-K money format above.
    _apply_number_format(ws, 11, 10, 9 + len(_VALIDATION_LABELS), "General")
    # Assembly Summary block's own Ext Price (E) / Ext Part Vol Price (G) -- same 4-decimal
    # money format, scoped to just the summary rows + TOTAL row (columns E/G hold different
    # data elsewhere on this sheet, so this must not be a whole-column apply).
    if summary_data_end >= summary_data_start:
        _apply_number_format(ws, 5, summary_data_start, total_row, _MONEY_FORMAT)
        _apply_number_format(ws, 7, summary_data_start, total_row, _MONEY_FORMAT)

    for col_idx in range(1, NUM_COLS + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 14

    return ws


def _demo():
    from openpyxl import Workbook

    payload = {
        "project_name": "Widget-X",
        "summary": [
            {
                "FG": "ASSY-01",
                "Description": "Main Assembly",
                "volumes": [
                    {"volume": 1, "ext_price_conv": 1500.00, "ext_vol_qty": 1000,
                     "ext_part_vol_price_conv": 1500.00, "batch_qty": 100},
                ],
            },
        ],
        "ASSY-01": {
            "ASSY-01": [
                {
                    "FG": "ASSY-01",
                    "CPN": "CPN-1001",
                    "part_description": "Resistor 10k",
                    "commodity": "Passive",
                    "part_qty": 10, "fg_part_qty": 10,  # single sub-assembly here, so the two are equal
                    "line_no": 1,
                    "isAssembly": False,
                    "volumes": [
                        {
                            "volume": 1, "manufacturerName": "ACME", "MPN": "MPN-ABC-123", "UOM": "EA",
                            "ext_vol_qty": 1000, "price_conv": 1.5, "price_original": 1.5, "currency": "USD",
                            "ext_price_conv": 1500.00, "ext_part_vol_price_conv": 1500.00,
                            "supplierName": "Acme Corp", "packageQty": 100, "MOQ": 500, "leadTime": 12,
                            "NCNR": "No", "price_control": "Centum", "MFRinScrubBOM": "ACME", "isData": True,
                            "batch_qty": 100, "ABC_classification": "A", "isCosted": True,
                        },
                    ],
                },
            ],
        },
    }

    rows = cbom_vl_rows(payload, 1)

    assert rows[2] == ["", "", "Project:", "", "", "Widget-X - VOL - 1"]
    assert rows[8][:4] == ["", "", "Assembly", "Description"]
    assert rows[9][2] == "ASSY-01" and rows[9][4] == 1500.00
    assert rows[10][2] == "TOTAL" and rows[10][4] == 1500.00
    print("cbom_vl_rows() top-section self-check passed")

    assembly_row = next(i for i, r in enumerate(rows) if r and isinstance(r[0], str) and r[0].startswith("*** Assembly:"))
    assert rows[assembly_row] == ["*** Assembly: ASSY-01 || FG: ASSY-01"]
    assert rows[assembly_row + 1][:7] == [
        "FG part number", "Assembly", "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number",
    ]
    data_row = rows[assembly_row + 2]
    assert data_row[2] == "CPN-1001" and data_row[6] == "MPN-ABC-123" and data_row[13] == 1500.00
    print("cbom_vl_rows() assembly-block self-check passed")

    first_data_row, last_data_row = cbom_vl_bounds(payload, 1)
    assert rows[first_data_row - 1][2] == "CPN-1001"  # first real data row, right after the header row
    assert rows[last_data_row - 1][2] == "CPN-1001"  # last row with a non-blank Part Number
    print("cbom_vl_bounds() self-check passed")

    payload_h = dict(payload)
    payload_h["hierarchical_order"] = [{"fg": "ASSY-01", "assembly": "ASSY-01", "cpn": "CPN-1001"}]
    rows_h = cbom_vl_rows(payload_h, 1)
    assembly_row_h = next(i for i, r in enumerate(rows_h) if r and isinstance(r[0], str) and r[0].startswith("*** Assembly:"))
    assert rows_h[assembly_row_h + 2][2] == "CPN-1001"
    print("cbom_vl_rows() hierarchical_order self-check passed")

    proto_rows = cbom_vl_rows(payload, "proto")
    assert proto_rows[8][4] == "Ext Price #1 (Conv.)"
    print("cbom_vl_rows() proto-volume self-check passed")

    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    ws = build_cbom_vl_sheet(wb, payload, 1)
    assert ws.title == "7.0 CBOM VL-1"
    # K2 (not a hardcoded K4) -- USD is always the first row/rate=1.0 per
    # currency.py's own pivot-currency convention; K4's identity depends on
    # how many currencies are active and in what order, which isn't fixed.
    assert ws["J1"].value == "Currency" and ws["J2"].value == "USD" and ws["K2"].value == 1
    print("build_cbom_vl_sheet() self-check passed")

    # Is Price Same / Is MPN Same / Recurring Count formula overlays -- byte-identical to
    # a real generated workbook's AM/AN/AP cells (transcribed, not re-derived), bounded to
    # this sheet's own first_data_row/last_data_row instead of full columns.
    data_row_num = assembly_row + 3  # 1-indexed sheet row for the CPN-1001 data row
    first_data_row = assembly_row + 1  # 1-indexed sheet row of "*** Assembly:" label
    last_data_row = len(rows)
    assert ws.cell(row=data_row_num, column=39).value == (
        f'=IF($AF{data_row_num},IF($K{data_row_num}="",TRUE,ROUND(SUMIFS('
        f'$K${first_data_row}:$K${last_data_row},$C${first_data_row}:$C${last_data_row},$C{data_row_num})/'
        f'COUNTIFS($C${first_data_row}:$C${last_data_row},$C{data_row_num}),3)=ROUND($K{data_row_num},3)),"")'
    )
    assert ws.cell(row=data_row_num, column=40).value == (
        f'=IF($AF{data_row_num}, IF(SUMPRODUCT(($C${first_data_row}:$C${last_data_row}=$C{data_row_num})*'
        f'($G${first_data_row}:$G${last_data_row}<>$G{data_row_num})) > 0, FALSE, TRUE), "")'
    )
    assert ws.cell(row=data_row_num, column=42).value == (
        f'=IF($C{data_row_num}<>"", COUNTIF($C$1:$C{data_row_num}, $C{data_row_num}), "")'
    )
    print("Is Price Same / Is MPN Same / Recurring Count formula overlay self-check passed")

    # Is Assembly (AH) -- deliberately NOT gated on Currency ($M) being blank anymore;
    # a structural CPN can legitimately have a real currency once its price is
    # rolled up from its own descendants (see excel_mappings.py's _structural_rollup()).
    # ALSO requires this CPN's own children to carry real cost (SUMIFS<>0) -- a
    # "dual-role" CPN (structural by name but genuinely, independently priced, with no
    # compensating children cost) must NOT be marked Is Assembly=TRUE, or its entire
    # real cost silently disappears from every downstream total.
    assert ws.cell(row=data_row_num, column=34).value == (
        f'=IF($AF{data_row_num}, AND(NOT(ISERROR(MATCH($AV{data_row_num}, '
        f'$AU${first_data_row}:$AU${last_data_row}, 0))), '
        f'SUMIFS($N${first_data_row}:$N${last_data_row}, '
        f'$A${first_data_row}:$A${last_data_row}, $A{data_row_num}, '
        f'$B${first_data_row}:$B${last_data_row}, $C{data_row_num})<>0), "")'
    )
    print("Is Assembly formula overlay self-check passed")

    # ABC Classification (AJ) / Scrap (AK) -- live MATCH/INDEX overlay against the
    # hidden Scrap Factor sheet, replacing _data_row()'s static placeholder value.
    # Gated on $K<>"" (price present), NOT $AO (Is Costed) -- a price of exactly 0 must
    # still classify (Class C), which an $AO gate would incorrectly leave blank.
    scrap_last_row = 1 + len(get_scrap_factor_table())
    assert ws.cell(row=data_row_num, column=36).value == (
        f'=IF($AF{data_row_num}, IF($K{data_row_num}<>"", INDEX(\'Scrap Factor\'!$C$2:$C${scrap_last_row}, '
        f'MATCH($K{data_row_num}, \'Scrap Factor\'!$A$2:$A${scrap_last_row}, 1)), ""), "")'
    )
    assert ws.cell(row=data_row_num, column=37).value == (
        f'=IF($AF{data_row_num}, IF($K{data_row_num}<>"", INDEX(\'Scrap Factor\'!$D$2:$D${scrap_last_row}, '
        f'MATCH($K{data_row_num}, \'Scrap Factor\'!$A$2:$A${scrap_last_row}, 1)), ""), "")'
    )
    print("ABC Classification / Scrap formula overlay self-check passed")

    # Ext Vol Qty (J) -- STATIC value (item's own v["ext_vol_qty"], already Part Qty x
    # hierarchy_multiplier x FG input from the backend), left untouched here -- same
    # treatment as Part Qty/FG Part Qty (a live formula previously overwrote this;
    # removed as broken, see comment above).
    assert ws.cell(row=data_row_num, column=10).value == 1000.00
    print("Ext Vol Qty static-value self-check passed")

    # Batch Qty (AG) -- live recursive formula overlay, replacing _data_row()'s static
    # placeholder. CPN-1001's own Assembly ("ASSY-01") equals its own FG ("ASSY-01"),
    # so this exercises the "immediate parent is the Finished Good" branch: looks up
    # FG "ASSY-01"'s own Batch Qty for volume 1 from the hidden Batch Settings sheet.
    batch_settings_last_row = 1 + len(payload["summary"][0]["volumes"])
    assert ws.cell(row=data_row_num, column=33).value == (
        f'=IF($AF{data_row_num}, IF($A{data_row_num}=$B{data_row_num}, '
        f'$I{data_row_num}*IFERROR(INDEX(\'Batch Settings\'!$C$2:$C${batch_settings_last_row}, '
        f'MATCH($A{data_row_num}&"|"&"1", \'Batch Settings\'!$D$2:$D${batch_settings_last_row}, 0)), 0), '
        f'$I{data_row_num}*IFERROR(INDEX($AG:$AG, SUMPRODUCT(($A${first_data_row}:$A${last_data_row}=$A{data_row_num})*'
        f'($C${first_data_row}:$C${last_data_row}=$B{data_row_num})*ROW($C${first_data_row}:$C${last_data_row}))), 0)'
        f'), "")'
    )
    print("Batch Qty formula overlay self-check passed")

    # FG Ext Price (Conv.) (AX) -- AW (FG Part Qty, hierarchy_multiplier-weighted) x K,
    # feeding the Assembly Summary total below instead of N (which uses LOCAL Part Qty
    # and undercounts anything nested under a sub-assembly used more than once).
    assert ws.cell(row=data_row_num, column=50).value == (
        f'=IF(AND($AF{data_row_num},$K{data_row_num}<>"",$AW{data_row_num}<>""),'
        f'$AW{data_row_num}*$K{data_row_num},"")'
    )
    print("FG Ext Price (Conv.) formula overlay self-check passed")

    # Assembly Summary Ext Price (E) -- live per-FG SUMIFS formula over column AX (FG
    # Part Qty x Price Conv, hierarchy-weighted), filtered on column A (FG part
    # number -- every row anywhere under the FG, any nesting depth) with Is Assembly
    # (AH) excluded, so a repeated sub-assembly's descendants are weighted by their
    # full cumulative hierarchy_multiplier instead of relying on either column B's
    # top-level-only cutoff or column N's un-multiplied local quantity. TOTAL row (11)
    # still a live SUM over the per-FG cells. Ext Part Vol Price (G) is UNCHANGED --
    # still the static value from cbom_vl_rows()'s own top_section (not part of this
    # specific request).
    assert ws.cell(row=10, column=5).value == (
        f'=SUMIFS($AX${first_data_row}:$AX${last_data_row}, '
        f'$A${first_data_row}:$A${last_data_row}, $C10, '
        f'$AH${first_data_row}:$AH${last_data_row}, "<>TRUE")'
    )
    assert ws.cell(row=10, column=7).value == 1500.00
    assert ws.cell(row=11, column=5).value == '=SUM(E10:E10)'
    assert ws.cell(row=11, column=7).value == '=SUM(G10:G10)'
    print("Assembly Summary Ext Price formula overlay / Ext Part Vol Price static-value self-check passed")

    # Validation/Status (K10:K17) and MOQ Cost (M9/M11) -- live formulas,
    # byte-identical to the reference workbook except for dynamic row bounds
    # (first_data_row/last_data_row) and this volume's own Ex Inv VL sheet name.
    assert ws.cell(row=10, column=11).value == (
        f'=SUMPRODUCT(($AP${first_data_row}:$AP${last_data_row}=1)*($C${first_data_row}:$C${last_data_row}<>""))'
    )
    assert ws.cell(row=11, column=11).value == "=K10-K12"
    assert ws.cell(row=13, column=11).value == "=K14-K11"
    assert ws.cell(row=15, column=11).value == (
        f'=COUNTIFS($AO${first_data_row}:$AO${last_data_row},FALSE,'
        f'$AF${first_data_row}:$AF${last_data_row},TRUE,'
        f'$AH${first_data_row}:$AH${last_data_row},"<>TRUE")'
    )
    assert ws.cell(row=11, column=13).value == "='Ex Inv VL-1'!$A$2"
    assert ws.cell(row=9, column=13).value == f"=IFERROR($M$11/G{11},0)"
    print("Validation/Status + MOQ Cost formula overlay self-check passed")

    # 5 restored validation metrics (K18:K22) -- explicit business logic, not
    # reverse-engineered from a reference file.
    is_data_test = (
        f'(($AF${first_data_row}:$AF${last_data_row}=TRUE)+'
        f'($AF${first_data_row}:$AF${last_data_row}="TRUE")+'
        f'($AF${first_data_row}:$AF${last_data_row}=1)>0)'
    )
    assert ws.cell(row=18, column=11).value == (
        f'=SUMPRODUCT(($AQ${first_data_row}:$AQ${last_data_row}=FALSE)*{is_data_test})'
    )
    assert ws.cell(row=19, column=11).value == (
        f'=SUMPRODUCT(($AR${first_data_row}:$AR${last_data_row}=FALSE)*{is_data_test})'
    )
    assert ws.cell(row=20, column=11).value == (
        f'=SUMPRODUCT(($AS${first_data_row}:$AS${last_data_row}=FALSE)*{is_data_test})'
    )
    assert ws.cell(row=21, column=11).value == (
        f'=SUMPRODUCT(($AT${first_data_row}:$AT${last_data_row}=FALSE)*{is_data_test})'
    )
    assert ws.cell(row=22, column=11).value == (
        f'=SUMPRODUCT({is_data_test}*'
        f'(($E${first_data_row}:$E${last_data_row}="")+ISBLANK($E${first_data_row}:$E${last_data_row})>0))'
    )
    print("5 restored Validation/Status metrics (K18:K22) formula overlay self-check passed")

    cf_ranges = [str(r.sqref) for r in ws.conditional_formatting]
    assert "K15:K22" in cf_ranges
    print("K15:K22 nonzero-issue-count conditional formatting self-check passed")

    scrap_ws = build_scrap_factor_sheet(wb)
    assert scrap_ws.title == "Scrap Factor"
    assert scrap_ws.sheet_state == "hidden"
    assert scrap_ws.cell(row=1, column=1).value == "Min Price"
    tiers = get_scrap_factor_table()
    assert scrap_ws.max_row == 1 + len(tiers)
    for i, tier in enumerate(tiers):
        row = 2 + i
        assert scrap_ws.cell(row=row, column=1).value == tier["min_price"]
        assert scrap_ws.cell(row=row, column=3).value == tier["scrap_class"]
        assert scrap_ws.cell(row=row, column=4).value == tier["scrap_percent"]
    print("build_scrap_factor_sheet() self-check passed")

    batch_ws = build_batch_settings_sheet(wb, payload)
    assert batch_ws.title == "Batch Settings"
    assert batch_ws.sheet_state == "hidden"
    assert batch_ws.cell(row=1, column=1).value == "FG"
    assert batch_ws.cell(row=2, column=1).value == "ASSY-01"
    assert batch_ws.cell(row=2, column=2).value == "1"
    assert batch_ws.cell(row=2, column=3).value == 100
    assert batch_ws.cell(row=2, column=4).value == "ASSY-01|1"
    print("build_batch_settings_sheet() self-check passed")

    wb.save("CBOM_VL_Output.xlsx")
    print("\nExcel generated successfully.")
    print("File : CBOM_VL_Output.xlsx")


if __name__ == "__main__":
    _demo()
