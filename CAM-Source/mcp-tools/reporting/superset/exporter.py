"""Excel export stage: reads the already-generated cbom + 16 report tables for one
rfq_id and writes one consolidated, production-formatted workbook. Read-only -- never
regenerates data (that's cbom_generator.py/report_generator.py's job, orchestrated by
reporting_pipeline.run_pipeline()).

Reuses the 16 already-existing, production-reverse-engineered build_*_sheet() functions
in reports/*.py (each independently verified byte-for-byte against a real reference
production workbook for styling AND, where production itself is formula-driven, live
Excel formulas). This module's own job is purely: (1) load the RFQ-scoped DuckDB rows,
(2) reshape them into each report's expected payload via templates/excel_mappings.py,
(3) dispatch into the sheet builders in the right order, (4) save the workbook. No
styling or formula logic is duplicated here.
"""

import os
import time
import uuid
from datetime import datetime
from openpyxl.utils import get_column_letter

from openpyxl import Workbook

import config
import constants
import database
import excel_formatter
import excel_formulas
import helpers
import queries
from logging_utils import logger
from templates import excel_mappings as mappings

from reports.bom_matrix import build_bom_matrix_sheet
from reports.part_num_vs_mfg_num import part_num_vs_mfg_num, build_part_num_vs_mfg_num_sheet
from reports.pcb_nre_fai_charge import fai_charge_rows, build_fai_charge_sheet
from reports.mech_em_nre import mech_em_nre_rows, build_mech_em_nre_sheet
from reports.new_suppliers import new_supplier_rows, build_new_suppliers_sheet, load_supplier_master
from reports.missing_notes import missing_notes, flatten_missing_notes, build_missing_notes_sheet
from reports.lead_time_fg import lead_time_fg_blocks, flatten_lead_time_fg, build_lead_time_fg_sheet
from reports.lead_time_consolidated import lead_time_consolidated_rows, build_lead_time_consolidated_sheet
from reports.sum_and_count import sum_and_count, build_sum_and_count_sheet
from reports.sum_and_count_detailed import sum_and_count_detail, build_sum_and_count_detailed_sheet
from reports.revision_history import revision_history_rows, build_revision_history_sheet
from reports.aclass_parts import aclass_parts, build_aclass_parts_sheet
from reports.price_control import price_control as price_control_compute, build_price_control_sheet
from reports.summary import summary as summary_compute, build_summary_sheet
from reports.batchwise_cashflow import build_batchwise_cashflow_sheet
from reports.cbom_vl import (
    build_batch_settings_sheet, build_cbom_vl_sheet, build_scrap_factor_sheet, cbom_vl_bounds, cbom_vl_rows,
)
from reports.ex_inv_vl import build_ex_inv_vl_sheet, ex_inv_vl_rows


def _build_cbom_raw_sheet(wb, cbom_df):
    """The one sheet the reference production workbook doesn't have (production's
    equivalent is just the per-volume 7.0 CBOM VL-{n} sheets) -- our own raw,
    combined-across-volumes addition. Styled with the same navy/light-blue palette as
    every other sheet for consistency; a plain literal-value dump is correct here since
    no cross-sheet formula makes sense for a table that spans every volume at once.
    """
    ws = wb.create_sheet(title=constants.SHEET_NAMES["cbom"])
    df = cbom_df.drop(columns=["cbom_item_id", "rfq_id"], errors="ignore")
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append([helpers.excel_safe(v) for v in row])
    excel_formatter.autosize_and_freeze(ws, df)
    excel_formatter.fill_data_rows(ws)

    excel_formulas.apply_money_format(ws, df, [
        "price_conv_costing", "price_conv_erp", "price_conv_qw", "final_price_conv",
        "price_original_costing", "price_original_erp", "price_original_qw", "final_price_original",
        "ext_price_conv", "ext_part_vol_price_conv",
    ])
    excel_formulas.apply_percent_format(ws, df, ["scrap_percent"])

    return ws


def _reference_cbom_sheet(bounds_by_sheet):
    """The CBOM VL sheet whose data bounds the Sum & Count Detailed, A CLASS PARTS sheets
    reference. Prefers VL-1; otherwise the lowest numbered volume; otherwise Proto (an RFQ
    with prototype-only volumes). Hard-coding VL-1 raised KeyError for those RFQs."""
    if "7.0 CBOM VL-1" in bounds_by_sheet:
        return "7.0 CBOM VL-1"
    numbered = sorted(
        (name for name in bounds_by_sheet if name.startswith("7.0 CBOM VL-")),
        key=lambda name: int(name.rsplit("-", 1)[1]),
    )
    return numbered[0] if numbered else "7.0 CBOM Proto"


def export_excel(rfq_id):
    """Reads only -- never writes to any persisted cbom/report table (per the "export
    must not regenerate data" requirement; TEMP VIEWs computed fresh in-session, e.g. for
    Batchwise Cashflow below, don't count -- nothing persisted is touched). If cbom for
    this rfq_id doesn't exist yet, call the `cbom` MCP tool first. The separate
    `generate_reports` MCP tool is no longer a prerequisite for this export -- every sheet
    is computed live from cbom/scrub/quote_win at export time.
    """
    start = time.time()
    con = database.connect()
    rfq_lit = helpers.sql_quote(rfq_id)

    cbom_df = mappings.load_cbom_df(con, rfq_id)
    # The declared rules of every CBOM line (reports/report_model.py, Pydantic strict mode), checked before anything is written.
    from reports.report_model import violations as cbom_violations
    data_violations = cbom_violations(cbom_df)
    if cbom_df.empty:
        con.close()
        raise ValueError(f"No cbom rows found for rfq_id={rfq_id!r} -- call the cbom tool first")
    scrub_df = mappings.load_scrub_df(con, rfq_id)
    quote_df = mappings.load_quote_win_df(con, rfq_id)
    selected_quote_df = mappings.load_selected_quote_df(con, rfq_id)
    selected_quote_all_df = mappings.load_selected_quote_all_volumes_df(con, rfq_id)
    volume_rows = mappings._sanitize(con.execute(f"SELECT * FROM input_db.volume WHERE rfq_id = {rfq_lit}").df()).to_dict("records")
    # Computed live against the CURRENT cbom_db.cbom (a CREATE OR REPLACE TEMP VIEW, so no
    # persisted table is written -- doesn't violate this module's "read-only" contract),
    # instead of reading the separately-generated `ex_inv_vl_report` table. That table is
    # only ever populated by the distinct `generate_reports` MCP tool
    # (reporting_pipeline.run_pipeline()) and was confirmed empty for several real RFQs
    # that already have valid CBOM data -- Batchwise Cashflow was the one sheet in this
    # export that could silently render blank (if generate_reports never ran for this
    # rfq_id) or stale (if CBOM was regenerated/corrected after generate_reports last
    # ran) while every other sheet, computed live here, stayed correct.
    con.execute(queries.ex_inv_calc_sql(rfq_lit))
    ex_inv_report_df = mappings._sanitize(con.execute(f"SELECT {rfq_lit} AS rfq_id, * FROM ex_inv_calc").df())
    # Sourced from queries.detect_volumes() itself (already proto-first ordered), NOT
    # re-derived from cbom_df["volume_no"].unique(): once that column can hold "proto"
    # alongside numbered volumes, a plain sorted() over its raw values would do
    # lexicographic string ordering ("1" < "2" < "proto"), silently losing the
    # "proto always first" guarantee every downstream consumer here (payload builders,
    # the CBOM VL/Ex Inv VL sheet loops below) depends on.
    detected_volumes = queries.detect_volumes(con, rfq_lit)
    has_proto = "proto" in detected_volumes

    # cbom_tree/excess_inventory moved here (were previously computed just before
    # Price Control, well after BOM MATRIX/Sum & Count/Revision History/A CLASS
    # PARTS were already built) so cbom_vl_rows()/cbom_vl_bounds()/ex_inv_vl_rows()
    # -- pure functions of (data, volume) -- can be called here purely to get their
    # row counts/bounds, before those sheets actually exist in the workbook. Every
    # sheet built below that cross-references '7.0 CBOM VL-{n}'/'7.0 CBOM Proto' or
    # 'Ex Inv VL-{n}'/'Ex Inv VL-proto' needs this to bind its formulas to a real
    # range instead of a full column (see Test_fixes/EXCEL_LOAD_PERFORMANCE.md) --
    # the sheets themselves are still built in the exact same place/order as before,
    # so tab order is unaffected.
    cbom_tree = mappings.to_cbom_tree_payload(cbom_df, scrub_df, project_name=rfq_id)
    excess_inventory = mappings.to_excess_inventory_payload(cbom_df, scrub_df)

    cbom_row_counts = {}       # {"7.0 CBOM VL-{n}"/"7.0 CBOM Proto": last_row}
    cbom_bounds_by_sheet = {}  # {same keys: (first_data_row, last_data_row)}
    cbom_bounds_by_volume = {}  # {numeric volume: (first_data_row, last_data_row)} -- no "proto" key
    ex_inv_row_counts = {}     # {"Ex Inv VL-{n}"/"Ex Inv VL-proto": last_row}
    for v in detected_volumes:
        v_typed = "proto" if str(v).lower() == "proto" else int(v)
        cbom_sheet_name = "7.0 CBOM Proto" if v_typed == "proto" else f"7.0 CBOM VL-{v_typed}"
        ex_inv_sheet_name = "Ex Inv VL-proto" if v_typed == "proto" else f"Ex Inv VL-{v_typed}"
        cbom_row_counts[cbom_sheet_name] = len(cbom_vl_rows(cbom_tree, v_typed))
        bounds = cbom_vl_bounds(cbom_tree, v_typed)
        cbom_bounds_by_sheet[cbom_sheet_name] = bounds
        if v_typed != "proto":
            cbom_bounds_by_volume[v_typed] = bounds
        ex_inv_row_counts[ex_inv_sheet_name] = len(ex_inv_vl_rows(excess_inventory, v_typed))

    wb = Workbook()
    wb.remove(wb.active)
    worksheet_names = []

    # Hidden Scrap Factor / Batch Settings config sheets -- both built once, before any
    # per-volume CBOM VL sheet below (each one's own AJ/AK/AG columns reference these
    # same sheets by name via a live MATCH/INDEX formula; see build_cbom_vl_sheet()).
    # Batch Settings is sourced from cbom_tree (already computed above, covers every
    # detected volume in one pass -- see build_batch_settings_sheet()'s own docstring).
    # Neither is appended to worksheet_names: that list tracks the workbook's visible
    # tab order, and both sheets are deliberately hidden, not tabs a user would ever see.
    build_scrap_factor_sheet(wb)
    build_batch_settings_sheet(wb, cbom_tree)

    # "CBOM" tab first, per the required tab order -- our own addition, not a production sheet.
    _build_cbom_raw_sheet(wb, cbom_df)
    worksheet_names.append(constants.SHEET_NAMES["cbom"])

    build_bom_matrix_sheet(
        wb, mappings.to_bom_matrix_payload(cbom_df, scrub_df)["rows"], cbom_row_counts, ex_inv_row_counts,
    )
    worksheet_names.append("BOM MATRIX")

    build_part_num_vs_mfg_num_sheet(wb, part_num_vs_mfg_num(mappings.to_part_num_vs_mfg_num_payload(scrub_df, quote_df)))
    worksheet_names.append("Part Num Vs Mfg Num")

    build_fai_charge_sheet(wb, fai_charge_rows(mappings.to_nre_payload(scrub_df[scrub_df["commodity"] == "PCB"])),
                           cbom_bounds=cbom_bounds_by_sheet.get("7.0 CBOM VL-1"))
    worksheet_names.append("PCB NRE & FAI Charge")

    build_mech_em_nre_sheet(wb, mech_em_nre_rows(
        mappings.to_nre_payload(scrub_df[scrub_df["commodity"].str.upper().isin(["MECHANICAL", "ELECTROMECHANICAL"])])
    ), cbom_bounds=cbom_bounds_by_sheet.get("7.0 CBOM VL-1"))
    worksheet_names.append("Mech & EM NRE")

    mn_sections = missing_notes(mappings.to_missing_notes_payload(cbom_df, scrub_df, selected_quote_df, has_proto=has_proto))
    build_missing_notes_sheet(wb, flatten_missing_notes(mn_sections))
    worksheet_names.append("Missing Notes")

    # SKILL_03: only for an RFQ that ran the Feasibility & Risk step (its row in feasibility_risk_run); values, no formulas.
    ran_feasibility = con.execute(f"SELECT settings_json FROM feasibility_risk_run WHERE rfq_id = {rfq_lit}").fetchone()
    if ran_feasibility:
        import json
        from reports.feasibility_risk import feasibility_rows, build_feasibility_sheet
        used = json.loads(ran_feasibility[0])["settings"] if ran_feasibility[0] else None   # the rules of the run (a run before they were stored used the defaults)
        build_feasibility_sheet(wb, feasibility_rows(scrub_df, quote_df, settings=used), settings=used)
        worksheet_names.append("Feasibility & Risk")

    lt_blocks = lead_time_fg_blocks(mappings.to_lead_time_fg_payload(cbom_df))
    build_lead_time_fg_sheet(wb, flatten_lead_time_fg(lt_blocks), cbom_bounds=cbom_bounds_by_sheet.get("7.0 CBOM VL-1"))
    worksheet_names.append("Lead Time (FG Wise)")

    build_lead_time_consolidated_sheet(wb, lead_time_consolidated_rows(mappings.to_lead_time_consolidated_payload(cbom_df)))
    worksheet_names.append("Lead Time Consolidated")

    sc_payload = mappings.to_sum_and_count_payload(scrub_df, selected_quote_all_df, detected_volumes)
    # Computed once, reused for both the row-count threaded into Sum & Count's own
    # SUMIFS bounds below and the actual Sum & Count Detailed sheet build further
    # down -- same list object, so there is no risk of the two ever diverging.
    sum_and_count_detail_rows = sum_and_count_detail(sc_payload)
    build_sum_and_count_sheet(
        wb, sum_and_count(sc_payload), detailed_last_row=len(sum_and_count_detail_rows) + 1, include_proto=has_proto,
    )
    worksheet_names.append("Sum & Count")

    reference_sheet = _reference_cbom_sheet(cbom_bounds_by_sheet)
    build_sum_and_count_detailed_sheet(
        wb, sum_and_count_detail_rows, cbom_bounds=cbom_bounds_by_sheet[reference_sheet], include_proto=has_proto,
    )
    worksheet_names.append("Sum & Count Detailed")

    build_revision_history_sheet(
        wb, revision_history_rows(mappings.to_revision_history_payload(rfq_id, scrub_df, quote_df)),
        cbom_bounds_by_volume, ex_inv_row_counts,
    )
    worksheet_names.append("Revision History")

    build_aclass_parts_sheet(
        wb, aclass_parts(mappings.to_aclass_parts_payload(scrub_df, quote_df, cbom_df)),
        cbom_bounds=cbom_bounds_by_sheet[reference_sheet],
    )
    worksheet_names.append("A CLASS PARTS")

    pc_payload = mappings.to_price_control_payload(scrub_df, selected_quote_all_df, volume_rows, detected_volumes)
    last_volume = mappings.resolve_last_volume(pc_payload["rfqs"])
    contract_names = mappings.extract_contract_names(cbom_tree, last_volume)
    pc_sheet_name = f"7.0 CBOM VL-{last_volume}"
    build_price_control_sheet(
        wb, price_control_compute(pc_payload), cbom_bounds_by_sheet[pc_sheet_name][1],
        last_volume=last_volume, contract_names=contract_names,
    )
    worksheet_names.append("Price Control")

    build_summary_sheet(
        wb, summary_compute(mappings.to_summary_payload(rfq_id, scrub_df, selected_quote_all_df, volume_rows, detected_volumes)),
        cbom_row_counts, include_proto=has_proto,
    )
    worksheet_names.append("Summary")

    build_batchwise_cashflow_sheet(
        wb, mappings.to_batchwise_cashflow_payload(ex_inv_report_df), ex_inv_row_counts, include_proto=has_proto,
    )
    worksheet_names.append("Batchwise Cashflow")

    # detected_volumes is a List[str] ("proto", "1", "2", ...); the tree/payload builders
    # above (to_cbom_tree_payload/to_excess_inventory_payload) key their "volume" field on
    # "proto" (string) or a real Python int for numbered volumes (see their _norm_vol()) --
    # comparing against a bare string "1" here would never match (1 == "1" is False in
    # Python), silently rendering every non-proto VL sheet empty. Convert each volume to
    # that same type right at this boundary.
    for v in detected_volumes:
        v_typed = "proto" if str(v).lower() == "proto" else int(v)
        cbom_sheet_name = "7.0 CBOM Proto" if v_typed == "proto" else f"7.0 CBOM VL-{v_typed}"
        build_cbom_vl_sheet(wb, cbom_tree, v_typed, expected_row_count=cbom_row_counts[cbom_sheet_name])
        worksheet_names.append(cbom_sheet_name)

    # Price Control's SUMPRODUCT ranges were bound (above) to cbom_bounds_by_sheet's
    # pre-computed last_data_row, before this sheet actually existed to check against --
    # under-bounding a live formula range silently truncates results instead of
    # erroring (see Test_fixes/EXCEL_LOAD_PERFORMANCE.md §5.7), so verify now that no
    # row beyond that bound holds real data in any of the 4 columns Price Control's
    # formulas actually reference (W/AF/N/O). Deliberately NOT a blanket comparison
    # against this sheet's overall max_row: build_cbom_vl_sheet() leaves trailing
    # rows with only border/formatting applied (no value) past the last real data
    # row in *other* columns, which would otherwise make this assertion fire on a
    # bound that is, in fact, correct for Price Control's purposes.
    if pc_sheet_name in wb.sheetnames:
        pc_ws = wb[pc_sheet_name]
        pc_bound_used = cbom_bounds_by_sheet[pc_sheet_name][1]
        from openpyxl.utils import column_index_from_string as _col_idx
        _pc_cols = [_col_idx(c) for c in ("W", "AF", "N", "O")]
        for _r in range(pc_bound_used + 1, pc_ws.max_row + 1):
            _row_has_data = any(pc_ws.cell(row=_r, column=_c).value not in (None, "") for _c in _pc_cols)
            assert not _row_has_data, (
                f"Price Control sheet bound ({pc_bound_used}) excludes row {_r} of "
                f"'{pc_sheet_name}', which has real data in a column Price Control "
                "references -- this would have silently truncated its SUMPRODUCT ranges."
            )

    numbered_volumes = {int(v) for v in detected_volumes if str(v).lower() != "proto"}
    for v in detected_volumes:
        v_typed = "proto" if str(v).lower() == "proto" else int(v)
        cbom_sheet_name = "7.0 CBOM Proto" if v_typed == "proto" else f"7.0 CBOM VL-{v_typed}"
        ex_inv_sheet_name = "Ex Inv VL-proto" if v_typed == "proto" else f"Ex Inv VL-{v_typed}"
        # Volume 1's previous sheet is PROTO; volume n's is n-1. Only exists if it was detected.
        if v_typed == "proto":
            previous_exists = False
        elif v_typed == 1:
            previous_exists = has_proto
        else:
            previous_exists = (v_typed - 1) in numbered_volumes
        build_ex_inv_vl_sheet(
            wb, excess_inventory, v_typed, cbom_bounds=cbom_bounds_by_sheet[cbom_sheet_name],
            has_proto=has_proto, expected_row_count=ex_inv_row_counts[ex_inv_sheet_name],
            previous_sheet_exists=previous_exists,
        )
        worksheet_names.append(ex_inv_sheet_name)

    con.close()

    # Second-granularity timestamp alone can collide: two export_reports calls
    # for the same rfq_id within the same second (e.g. 2 concurrent users, or
    # a fast retry) would silently overwrite each other's workbook with no
    # warning. The short uuid suffix makes every export's filename unique
    # regardless of timing -- duck_db_api.py's _find_latest_export() globs on
    # `CBOM_Report_{cbom_key}_*.xlsx` (wildcard already covers everything
    # after that prefix) and picks the newest by mtime, not by parsing the
    # filename, so this is safe to add without touching that lookup.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_suffix = uuid.uuid4().hex[:8]
    filename = f"CBOM_Report_{helpers.slugify(rfq_id)}_{timestamp}_{unique_suffix}.xlsx"
    path = os.path.join(config.EXPORTS_DIR, filename)
    # RE 2 / C1: a manifest tab says which run made this file and what each tab holds, so a
    # reviewer can tell a workbook's origin without the pipeline logs. Last tab keeps sheet order.
    supplier_master = load_supplier_master()
    build_new_suppliers_sheet(
        wb, new_supplier_rows(cbom_df.to_dict("records"), detected_volumes, supplier_master), detected_volumes,
        master_provided=supplier_master is not None,
    )
    worksheet_names.append("New Suppliers")
    manifest = wb.create_sheet(title="Manifest")
    manifest.append(["Field", "Value"])
    manifest.append(["RFQ ID", rfq_id])
    manifest.append(["Workbook", filename])
    manifest.append(["Generated (UTC)", datetime.utcnow().isoformat(timespec="seconds")])
    manifest.append(["Generator", "CAM 3.4 reporting export"])
    manifest.append([])
    manifest.append(["Sheet", "Rows", "Columns"])
    for sheet in wb.worksheets[:-1]:
        manifest.append([sheet.title, sheet.max_row, sheet.max_column])
    # RE 2 A3: one GO / NO-GO cell. Counts Excel error values in every tab, within each tab's own bounds.
    error_terms = [
        f"SUMPRODUCT(--ISERROR('{sheet.title}'!A1:{get_column_letter(sheet.max_column)}{sheet.max_row}))"
        for sheet in wb.worksheets[:-1]
    ]
    manifest.append([])
    manifest.append(["Error cells (all tabs)", "=" + "+".join(error_terms)])
    error_row = manifest.max_row
    manifest.append(["Go / no-go", f'=IF(B{error_row}=0,"GO","NO-GO")'])
    # Excel shows "########" for a number wider than its column. The tabs at the default width (8.4) hold currency and totals: give every column
    # that carries numbers or formulas at least 15 characters (only widens; a column the tab set itself stays as it is).
    for sheet in wb.worksheets:
        for col in range(1, sheet.max_column + 1):
            letter = get_column_letter(col)
            dim = sheet.column_dimensions[letter]
            if dim.width and dim.width >= 15:
                continue
            has_number = any(
                isinstance(c.value, (int, float)) or (isinstance(c.value, str) and c.value.startswith("="))
                for c in sheet[letter][1:]
            )
            if has_number:
                dim.width = 15
    # The Run Inputs tab: which inputs this report was built from. A missing required input (run allowed to proceed with missing values)
    # is shown red here, so the workbook never reads as complete when it is not.
    from reports.run_inputs import build_run_inputs_sheet, run_input_rows, has_missing_required
    run_inputs = run_input_rows(bom_rows=len(scrub_df), quotewin_rows=len(quote_df))
    build_run_inputs_sheet(wb, run_inputs)
    worksheet_names.append("Run Inputs")
    from reports.presentation import style_workbook
    style_workbook(wb)   # every tab: centred headers, aligned numbers and text (values and formulas unchanged)
    wb.save(path)

    duration = time.time() - start
    logger.info(f"export_excel rfq_id={rfq_id!r} path={path} sheets={len(worksheet_names)} duration={duration:.3f}s")
    return {
        "status": "success",
        "data_violations": data_violations,
        "rfq_id": rfq_id,
        "workbook_name": filename,
        "workbook_path": path,
        "worksheet_count": len(worksheet_names),
        "worksheet_names": worksheet_names,
        "missing_required_inputs": has_missing_required(run_inputs),
        # What the workbook is made of, so the UI can say "0 of 502 rows priced" instead of a green tick (RFQ-000024).
        "cbom_row_count": int(len(cbom_df)),
        "priced_row_count": int(cbom_df["final_price_conv"].notna().sum()) if "final_price_conv" in cbom_df.columns else 0,
        "execution_time_seconds": round(duration, 3),
    }
