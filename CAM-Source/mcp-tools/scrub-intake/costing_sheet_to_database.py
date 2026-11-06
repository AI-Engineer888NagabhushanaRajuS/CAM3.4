import duckdb

from scrub_bom_to_database import DB_PATH


# ==========================================================
# SCHEMA — costing_sheet
#
# CREATE TABLE IF NOT EXISTS is used deliberately (never DROP TABLE) so
# this module can safely self-provision the schema on every call without
# destroying previously imported rows. Mirrors the live production
# schema exactly (no primary key on this table).
# ==========================================================

COSTING_SHEET_DDL = """
CREATE TABLE IF NOT EXISTS costing_sheet (
    rfq_id VARCHAR,
    assembly VARCHAR,
    part_number VARCHAR,
    description VARCHAR,
    commodity VARCHAR,
    mfg_name VARCHAR,
    mfg_part_number VARCHAR,
    unit VARCHAR,
    part_qty DOUBLE,
    price_original DOUBLE,
    currency_original VARCHAR,
    supp_name VARCHAR,
    pkg_qty DOUBLE,
    moq DOUBLE,
    lead_time INTEGER,
    nre_charge DOUBLE,
    nre_charge_conv DOUBLE,
    ncnr VARCHAR,
    price_control VARCHAR,
    price_type VARCHAR,
    exp_date DATE,
    long_comment VARCHAR
)
"""


def _ensure_schema(conn):

    conn.execute(COSTING_SHEET_DDL)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_costing_sheet_rfq
        ON costing_sheet(rfq_id)
        """
    )


def process_costing_sheet_to_database(rfq_id, standardized_df):

    df = standardized_df.copy()

    with duckdb.connect(DB_PATH) as conn:

        _ensure_schema(conn)

        existing_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM costing_sheet
            WHERE rfq_id = ?
            """,
            [rfq_id]
        ).fetchone()[0]

        if existing_count > 0:

            return {
                "status": "failed",
                "error": f"RFQ ID {rfq_id} already exists in costing_sheet",
                "existing_rows": existing_count
            }

        conn.register("temp_df", df)

        conn.execute("""
        INSERT INTO costing_sheet
        (
            assembly,
            part_number,
            description,
            commodity,
            mfg_name,
            mfg_part_number,
            unit,
            part_qty,
            price_original,
            currency_original,
            supp_name,
            pkg_qty,
            moq,
            lead_time,
            nre_charge,
            nre_charge_conv,
            ncnr,
            price_control,
            price_type,
            exp_date,
            long_comment,

            rfq_id
        )
        SELECT
            assembly,
            part_number,
            description,
            commodity,
            mfg_name,
            mfg_part_number,
            unit,
            part_qty,
            price_original,
            currency_original,
            supp_name,
            pkg_qty,
            moq,
            lead_time,
            nre_charge,
            nre_charge_conv,
            ncnr,
            price_control,
            price_type,
            exp_date,
            long_comment,

            ?
        FROM temp_df
        """, [rfq_id])

        conn.unregister("temp_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }
