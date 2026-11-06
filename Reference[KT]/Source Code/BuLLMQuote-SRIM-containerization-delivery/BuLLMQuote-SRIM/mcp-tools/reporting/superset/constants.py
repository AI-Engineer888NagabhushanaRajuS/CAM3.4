"""Pure data constants: the fixed 16-report processing order and the DuckDB-table-name ->
Excel-sheet-name mapping used by exporter.py (also defines the workbook's tab order, per
the reference production workbook -- CBOM tab first, our own addition, then the 16
reports in production's own tab order, then one 7.0 CBOM VL-{n}/Ex Inv VL-{n} pair per
detected volume).
"""

REPORT_ORDER = [
    "bom_matrix_report", "part_num_vs_mfg_num_report", "pcb_nre_fai_charge_report",
    "mech_em_nre_report", "missing_notes_report", "lead_time_fg_report",
    "lead_time_consolidated_report", "sum_and_count_report", "sum_and_count_detailed_report",
    "revision_history_report", "aclass_parts_report", "price_control_report",
    "summary_report", "batchwise_cashflow_report", "cbom_vl_report", "ex_inv_vl_report",
]

SHEET_NAMES = {
    "cbom": "CBOM",
    "bom_matrix_report": "BOM Matrix",
    "part_num_vs_mfg_num_report": "Part Number vs MFG Number",
    "pcb_nre_fai_charge_report": "PCB NRE & FAI Charge",
    "mech_em_nre_report": "Mechanical EM NRE",
    "missing_notes_report": "Missing Notes",
    "lead_time_fg_report": "Lead Time FG",
    "lead_time_consolidated_report": "Lead Time Consolidated",
    "sum_and_count_report": "Sum & Count",
    "sum_and_count_detailed_report": "Sum & Count Detailed",
    "revision_history_report": "Revision History",
    "aclass_parts_report": "A-Class Parts",
    "price_control_report": "Price Control",
    "summary_report": "Summary",
    "batchwise_cashflow_report": "Batchwise Cashflow",
    "cbom_vl_report": "CBOM VL",
    "ex_inv_vl_report": "Ex Inv VL",
}
