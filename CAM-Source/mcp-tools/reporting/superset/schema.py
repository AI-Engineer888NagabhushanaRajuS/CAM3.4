"""DuckDB table DDL for the two generated databases (cbom.duckdb, reports.duckdb). Both
sets of tables are created idempotently (`CREATE TABLE IF NOT EXISTS`) by database.py on
every connection -- these are OUR OWN generated artifacts, freely evolvable, unlike the
input tables in input_db.duckdb (which this module never creates or alters; see
migrations.py for the one-time setup step that prepares those).
"""

CBOM_DDL = """
CREATE TABLE IF NOT EXISTS cbom_db.cbom (
    cbom_item_id UUID,
    rfq_id VARCHAR,
    bom_item_id UUID,
    -- VARCHAR (not SMALLINT) so this column can hold "proto" alongside numbered
    -- volumes ("1", "2", ...) -- see database.py's connect() for the idempotent
    -- migration that upgrades a pre-existing SMALLINT column in place.
    volume_no VARCHAR,
    fg VARCHAR,
    assembly VARCHAR,
    cpn VARCHAR,
    description VARCHAR,
    commodity VARCHAR,
    unit_of_measure_costing VARCHAR,
    unit_of_measure_erp VARCHAR,
    unit_of_measure_qw VARCHAR,
    final_unit_of_measure VARCHAR,
    part_qty DOUBLE,
    -- Passthrough from scrub_bom_items.hierarchy_multiplier -- see
    -- scrub_bom_processing.py's _build_hierarchy_multipliers() docstring for the
    -- real-data bug this fixes (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md). Lets
    -- SQL-only consumers (e.g. queries.py's ex_inv_calc_sql()) compute an
    -- FG-wide-correct extended quantity (part_qty * hierarchy_multiplier) without
    -- needing scrub_bom_items in scope. Always >= 1, never NULL.
    hierarchy_multiplier DOUBLE,
    line_no VARCHAR,
    display_order INTEGER,
    mfr_in_customer_bom VARCHAR,
    mfg_name_costing VARCHAR,
    mfg_name_erp VARCHAR,
    mfg_name_qw VARCHAR,
    final_mfg_name VARCHAR,
    mfg_part_number VARCHAR,
    ext_vol_qty DOUBLE,
    -- Multi-source pricing/qty/lead-time (QW=QuoteWin, ERP, Costing sheet) -- see
    -- costing_sheet/erp in migrations.py. final_* columns are intentionally left
    -- unpopulated by cbom_insert_sql(): they're user-controlled, set later by a
    -- separate UI workflow, not resolved automatically here.
    price_conv_costing DOUBLE,
    price_conv_erp DOUBLE,
    price_conv_qw DOUBLE,
    final_price_conv DOUBLE,
    price_original_costing DOUBLE,
    price_original_erp DOUBLE,
    price_original_qw DOUBLE,
    final_price_original DOUBLE,
    currency_original_costing VARCHAR,
    currency_original_erp VARCHAR,
    currency_original_qw VARCHAR,
    final_currency_original VARCHAR,
    supp_name_costing VARCHAR,
    supp_name_erp VARCHAR,
    supp_name_qw VARCHAR,
    final_supp_name VARCHAR,
    pkg_qty_costing DOUBLE,
    pkg_qty_erp DOUBLE,
    pkg_qty_qw DOUBLE,
    final_pkg_qty DOUBLE,
    moq_costing DOUBLE,
    moq_erp DOUBLE,
    moq_qw DOUBLE,
    final_moq DOUBLE,
    lead_time_costing INTEGER,
    lead_time_erp INTEGER,
    lead_time_qw INTEGER,
    final_lead_time INTEGER,
    ncnr VARCHAR,
    long_comment VARCHAR,
    price_type VARCHAR,
    exp_date DATE,
    corrected_mpn VARCHAR,
    supplier_type VARCHAR,
    batch_qty DOUBLE,
    volume_qty DOUBLE,
    nre_charge DOUBLE,
    end_use_statement VARCHAR,
    scrap_percent DOUBLE,
    ext_price_conv DOUBLE,
    ext_part_vol_price_conv DOUBLE,
    price_control VARCHAR,
    is_costed BOOLEAN,
    moq_qty_present BOOLEAN,
    pkg_qty_present BOOLEAN,
    pkg_qty_lte_moq BOOLEAN,
    is_data BOOLEAN,
    is_assembly BOOLEAN,
    parent_line_no INTEGER,
    abc_classification VARCHAR,
    recurring_count INTEGER,
    mfg_part_num_in_scrub_bom VARCHAR,
    new_supplier VARCHAR,
    is_price_same BOOLEAN,
    is_mpn_same BOOLEAN,
    UNIQUE (rfq_id, bom_item_id, volume_no)
);
"""

REPORT_DDLS = {
    "bom_matrix_report": """
        CREATE TABLE IF NOT EXISTS bom_matrix_report (
            rfq_id VARCHAR, cpn VARCHAR, fg VARCHAR, volume_no VARCHAR,
            fg_count BIGINT, grand_total BIGINT, volume_qty DOUBLE,
            description VARCHAR, commodity VARCHAR, mfg_name VARCHAR, mfg_part_number VARCHAR,
            price_conv DOUBLE, fg_total_cost DOUBLE, fg_grand_total DOUBLE,
            pkg_qty DOUBLE, moq DOUBLE, lead_time DOUBLE, long_comment VARCHAR,
            price_control VARCHAR, ncnr VARCHAR, supp_name VARCHAR, corrected_mpn VARCHAR,
            net_excess_cost DOUBLE, price_validity VARCHAR, effective_date DATE
        );
    """,
    "part_num_vs_mfg_num_report": """
        CREATE TABLE IF NOT EXISTS part_num_vs_mfg_num_report (
            rfq_id VARCHAR, part_number VARCHAR, mpn VARCHAR, in_scrub_bom BOOLEAN,
            UNIQUE (rfq_id, part_number, mpn)
        );
    """,
    "pcb_nre_fai_charge_report": """
        CREATE TABLE IF NOT EXISTS pcb_nre_fai_charge_report (
            rfq_id VARCHAR, cpn VARCHAR, description VARCHAR, commodity VARCHAR,
            mfg_name VARCHAR, mfg_part_number VARCHAR, nre_charge DOUBLE,
            UNIQUE (rfq_id, cpn)
        );
    """,
    "mech_em_nre_report": """
        CREATE TABLE IF NOT EXISTS mech_em_nre_report (
            rfq_id VARCHAR, cpn VARCHAR, description VARCHAR, commodity VARCHAR,
            mfg_name VARCHAR, mfg_part_number VARCHAR, nre_charge DOUBLE,
            UNIQUE (rfq_id, cpn)
        );
    """,
    "missing_notes_report": """
        CREATE TABLE IF NOT EXISTS missing_notes_report (
            rfq_id VARCHAR, cpn VARCHAR, mpn VARCHAR, description VARCHAR, commodity VARCHAR,
            manufacturer VARCHAR, part_status VARCHAR, mfg_part_number VARCHAR,
            quoted_commodity VARCHAR, quoted_manufacturer VARCHAR, price_type VARCHAR,
            ncnr VARCHAR, corrected_mpn VARCHAR, no_bid_reason VARCHAR, exp_date DATE,
            quoted_part_status VARCHAR, mpn_mismatch BOOLEAN, commodity_mismatch BOOLEAN,
            quote_expiring_soon BOOLEAN
        );
    """,
    "lead_time_fg_report": """
        CREATE TABLE IF NOT EXISTS lead_time_fg_report (
            rfq_id VARCHAR, fg VARCHAR, lead_time DOUBLE, cpn_count BIGINT
        );
    """,
    "lead_time_consolidated_report": """
        CREATE TABLE IF NOT EXISTS lead_time_consolidated_report (
            rfq_id VARCHAR, lead_time DOUBLE, cpn_count BIGINT, percentage DOUBLE
        );
    """,
    "sum_and_count_report": """
        CREATE TABLE IF NOT EXISTS sum_and_count_report (
            rfq_id VARCHAR, assembly VARCHAR, scrub_bom_sum DOUBLE, scrub_bom_count BIGINT,
            v1_sum DOUBLE, v1_count BIGINT
        );
    """,
    "sum_and_count_detailed_report": """
        CREATE TABLE IF NOT EXISTS sum_and_count_detailed_report (
            rfq_id VARCHAR, assembly VARCHAR, cpn VARCHAR, scrub_bom_sum DOUBLE,
            scrub_bom_count BIGINT, v1_sum DOUBLE, v1_count BIGINT
        );
    """,
    "revision_history_report": """
        CREATE TABLE IF NOT EXISTS revision_history_report (
            rfq_id VARCHAR, cpn VARCHAR, volume_no VARCHAR, assembly VARCHAR,
            description VARCHAR, mpn VARCHAR, new_system_qty DOUBLE, new_unit_price DOUBLE,
            new_system_price DOUBLE, old_system_qty DOUBLE, old_unit_price DOUBLE,
            old_system_price DOUBLE
        );
    """,
    "aclass_parts_report": """
        CREATE TABLE IF NOT EXISTS aclass_parts_report (
            rfq_id VARCHAR, cpn VARCHAR, fg VARCHAR, description VARCHAR, commodity VARCHAR,
            mfg_name VARCHAR, mfg_part_number VARCHAR, unit_cost DOUBLE, awarded_volume DOUBLE,
            ext_price_conv DOUBLE, abc_classification VARCHAR, pct_of_total DOUBLE,
            UNIQUE (rfq_id, cpn)
        );
    """,
    "price_control_report": """
        CREATE TABLE IF NOT EXISTS price_control_report (
            rfq_id VARCHAR, price_control VARCHAR, bucket_total DOUBLE,
            UNIQUE (rfq_id, price_control)
        );
    """,
    "summary_report": """
        CREATE TABLE IF NOT EXISTS summary_report (
            rfq_id VARCHAR, fg VARCHAR, volume_no VARCHAR, bom_qty DOUBLE,
            inventory_stock DOUBLE, ext_vol_conv_price DOUBLE, volume_qty DOUBLE,
            moq_cost DOUBLE, pct_moq_of_cost DOUBLE,
            UNIQUE (rfq_id, fg, volume_no)
        );
    """,
    "batchwise_cashflow_report": """
        CREATE TABLE IF NOT EXISTS batchwise_cashflow_report (
            rfq_id VARCHAR, supplier_type VARCHAR, volume_no VARCHAR,
            sum_final_buy_value DOUBLE, sum_buy_value_after DOUBLE
        );
    """,
    "cbom_vl_report": """
        CREATE TABLE IF NOT EXISTS cbom_vl_report AS SELECT * FROM cbom_db.cbom WHERE FALSE;
    """,
    "ex_inv_vl_report": """
        CREATE TABLE IF NOT EXISTS ex_inv_vl_report (
            rfq_id VARCHAR, cpn VARCHAR, volume_no VARCHAR, description VARCHAR,
            commodity VARCHAR, mfg_name VARCHAR, mfg_part_number VARCHAR, part_qty DOUBLE,
            ext_vol_qty_sum DOUBLE, excess_in_stk DOUBLE, scrap_percent DOUBLE,
            batch_qty DOUBLE, cost DOUBLE, supp_name VARCHAR, pkg_qty DOUBLE, moq DOUBLE,
            lead_time DOUBLE, supplier_type VARCHAR, part_qty_is_whole BOOLEAN,
            excess_after_demand DOUBLE, shortage_qty DOUBLE, scrap_factor DOUBLE,
            batch_scrap_factor DOUBLE, ext_vol_cost DOUBLE, partial_qty DOUBLE,
            ordering_qty DOUBLE, excess_qty DOUBLE, excess_cost DOUBLE,
            buy_value_after DOUBLE, net_ordering_qty DOUBLE, net_excess_qty DOUBLE,
            net_excess_cost DOUBLE, final_buy_value DOUBLE, price_delta_vs_prior DOUBLE,
            moq_delta_vs_prior DOUBLE
        );
    """,
}
