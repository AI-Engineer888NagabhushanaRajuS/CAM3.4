import duckdb

from scrub_bom_to_database import DB_PATH, connect_db


# ==========================================================
# SCHEMA — erp
#
# CREATE TABLE IF NOT EXISTS is used deliberately (never DROP TABLE) so
# this module can safely self-provision the schema on every call without
# destroying previously imported rows. Mirrors the live production
# schema exactly.
#
# Unlike the other Centum tables, erp has no rfq_id column — it is a
# standing purchase-history reference table, not scoped to a single
# RFQ, so imports from different RFQ ERP exports simply accumulate
# rows rather than being gated by an rfq_id existence check. id and
# imported_at are left to their DEFAULTs (uuid() / CURRENT_TIMESTAMP).
# ==========================================================

ERP_DDL = """
CREATE TABLE IF NOT EXISTS erp (
    id UUID DEFAULT uuid(),
    mpn VARCHAR NOT NULL,
    mfr VARCHAR NOT NULL,
    quantity DOUBLE NOT NULL,
    uom VARCHAR NOT NULL,
    last_purchase_price DOUBLE NOT NULL,
    currency VARCHAR NOT NULL,
    supplier_name VARCHAR,
    in_stock_qty DOUBLE NOT NULL,
    reserved_qty DOUBLE NOT NULL,
    available_qty DOUBLE NOT NULL,
    last_po_number VARCHAR,
    last_po_date DATE,
    notes VARCHAR,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _ensure_schema(conn):

    conn.execute(ERP_DDL)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_erp_mpn
        ON erp(mpn)
        """
    )


def process_erp_to_database(standardized_df):

    df = standardized_df.copy()

    with connect_db(DB_PATH) as conn:

        _ensure_schema(conn)

        conn.register("temp_df", df)

        conn.execute("""
        INSERT INTO erp
        (
            mpn,
            mfr,
            quantity,
            uom,
            last_purchase_price,
            currency,
            supplier_name,
            in_stock_qty,
            reserved_qty,
            available_qty,
            last_po_number,
            last_po_date,
            notes
        )
        SELECT
            mpn,
            mfr,
            quantity,
            uom,
            last_purchase_price,
            currency,
            supplier_name,
            in_stock_qty,
            reserved_qty,
            available_qty,
            last_po_number,
            last_po_date,
            notes
        FROM temp_df
        """)

        conn.unregister("temp_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }
