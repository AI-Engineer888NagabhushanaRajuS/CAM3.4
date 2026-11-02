import duckdb
import pandas as pd
from pathlib import Path
from config import DB_PATH


def _ensure_structure_table(conn):
    # Mirrors detect_alternates.py's _ensure_alternatives_table() pattern --
    # idempotent, no separate migration tooling. Intentionally per-occurrence
    # (no primary/unique key on cpn/mpn): the same MPN can legitimately appear
    # here more than once, under different parents with different local
    # quantities -- that's the whole point of this table versus
    # processed_bom_items' MPN-consolidated rows.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bom_structure_items (
            id UUID DEFAULT gen_random_uuid(),
            rfq_id VARCHAR(100),
            file_name VARCHAR,
            occurrence_order INTEGER,
            fg VARCHAR,
            bom_level DOUBLE,
            item_num VARCHAR,
            cpn VARCHAR,
            description VARCHAR,
            mfr VARCHAR,
            mpn VARCHAR,
            commodity VARCHAR,
            bom_qty DOUBLE,
            hierarchy_multiplier DOUBLE,
            uom VARCHAR,
            volume DOUBLE
        )
    """)

    # volume was added after this table's first release (see
    # quote_summary.py's _fetch_quote_rows() docstring for why it's needed) --
    # CREATE TABLE IF NOT EXISTS above is a no-op against an already-created
    # table, so a table created before this column existed would otherwise be
    # silently missing it. Same idempotent ALTER pattern as enrichment.py's
    # ensure_columns().
    existing = {
        row[0].lower()
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'bom_structure_items'"
        ).fetchall()
    }
    if "volume" not in existing:
        conn.execute("ALTER TABLE bom_structure_items ADD COLUMN volume DOUBLE")


def process_bom_structure_to_database(rfq_id, bom_file, expanded_df):

    df = expanded_df.copy()

    df["file_name"] = Path(
        bom_file
    ).name

    df["occurrence_order"] = range(
        len(df)
    )

    with duckdb.connect(DB_PATH) as conn:

        _ensure_structure_table(
            conn
        )

        existing_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM bom_structure_items
            WHERE rfq_id = ?
            """,
            [rfq_id]
        ).fetchone()[0]

        if existing_count > 0:

            return {
                "status": "failed",
                "error": f"RFQ ID {rfq_id} already exists in bom_structure_items",
                "existing_rows": existing_count
            }

        conn.register("temp_structure_df", df)

        conn.execute("""
        INSERT INTO bom_structure_items
        (
            rfq_id,
            file_name,
            occurrence_order,
            fg,
            bom_level,
            item_num,
            cpn,
            description,
            mfr,
            mpn,
            commodity,
            bom_qty,
            hierarchy_multiplier,
            uom,
            volume
        )
        SELECT
            ?,
            file_name,
            occurrence_order,
            fg,
            bom_level,
            item_num,
            cpn,
            description,
            mfr,
            mpn,
            commodity,
            bom_qty,
            hierarchy_multiplier,
            uom,
            volume
        FROM temp_structure_df
        """, [rfq_id])

        conn.unregister("temp_structure_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }


def process_bom_to_database(rfq_id, bom_file, consolidated_df):

    df = consolidated_df.copy()

    df["file_name"] = Path(
        bom_file
    ).name

    df["parent_fg"] = None

    for col in [
    "ce_remarks",
    "item_num",
    "part_type",
    "ltb_date",
    "common_aml",
    "change_remarks",
    "exported_at"
    ]:
        if col not in df.columns:
            df[col] = None

    with duckdb.connect(DB_PATH) as conn:
        existing_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM processed_bom_items
            WHERE rfq_id = ?
            """,
            [rfq_id]
        ).fetchone()[0]

        if existing_count > 0:

            return {
                "status": "failed",
                "error": f"RFQ ID {rfq_id} already exists in database",
                "existing_rows": existing_count
            }

        conn.register("temp_df", df)

        conn.execute("""
        INSERT INTO processed_bom_items
        (
            rfq_id,
            file_name,
            parent_fg,
            fg,

            cpn,
            description,
            mfr,
            mpn,

            commodity,

            bom_qty,
            volume,
            required_qty,

            uom,

            ce_remarks,
            item_num,
            part_type,
            ltb_date,
            common_aml,
            change_remarks,

            exported_at
        )
        SELECT
            ?,
            file_name,
            parent_fg,
            fg,

            cpn,
            description,
            mfr,
            mpn,

            commodity,

            bom_qty,
            volume,
            required_qty,

            uom,

            ce_remarks,
            item_num,
            part_type,
            ltb_date,
            common_aml,
            change_remarks,

            exported_at
        FROM temp_df
        """, [rfq_id])

        conn.unregister("temp_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }
