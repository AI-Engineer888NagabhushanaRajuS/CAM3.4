import re

import duckdb

from scrub_bom_to_database import DB_PATH, connect_db


# ==========================================================
# SCHEMA — quote_win
#
# CREATE TABLE IF NOT EXISTS is used deliberately (never DROP TABLE) so
# this module can safely self-provision the schema on every call without
# destroying previously imported rows. Mirrors the live production
# schema exactly (no primary key on this table).
# ==========================================================

QUOTE_WIN_DDL = """
CREATE TABLE IF NOT EXISTS quote_win (
    project VARCHAR,
    part_number VARCHAR,
    part_description VARCHAR,
    commodity VARCHAR,
    mfg_name VARCHAR,
    mfg_part_number VARCHAR,

    cost_1_conv DOUBLE,
    price_original_1 DOUBLE,
    cost_2_conv DOUBLE,
    price_original_2 DOUBLE,
    currency_original VARCHAR,

    supp_name VARCHAR,
    supplier_type VARCHAR,

    pkg_qty DOUBLE,
    moq DOUBLE,
    lead_time DOUBLE,

    awarded_volume_1 DOUBLE,
    award_1 DOUBLE,
    awarded_volume_2 DOUBLE,
    award_2 DOUBLE,
    part_qty DOUBLE,

    corrected_mpn VARCHAR,
    long_comment VARCHAR,
    source_1 VARCHAR,
    source_2 VARCHAR,
    price_type VARCHAR,
    no_bid_reason VARCHAR,
    short_comment VARCHAR,
    ncnr VARCHAR,
    rfq_number VARCHAR,

    eff_date DATE,
    exp_date DATE,
    quote_validity VARCHAR,
    part_status VARCHAR,

    rfq_id VARCHAR
)
"""


def _ensure_schema(conn):

    conn.execute(QUOTE_WIN_DDL)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_quote_win_rfq
        ON quote_win(rfq_id)
        """
    )


# Matches any volume-slot column quote_win_processing.py's
# build_quote_win_template_headers()/build_numeric_headers() can produce for
# N > 2 -- the base DDL above only ever defines slots 1-2 up front.
_VOLUME_SLOT_COL_PATTERNS = [
    (re.compile(r"^cost_\d+_conv$"), "DOUBLE"),
    (re.compile(r"^price_original_\d+$"), "DOUBLE"),
    (re.compile(r"^awarded_volume_\d+$"), "DOUBLE"),
    (re.compile(r"^award_\d+$"), "DOUBLE"),
    (re.compile(r"^source_\d+$"), "VARCHAR"),
]


def _ensure_volume_slot_columns(conn, df_columns):
    """Self-extends `quote_win` for RFQs with more volume slots than the base
    DDL's 2 -- confirmed real (RFQ-000125): a QuoteWin file whose own
    metadata declares "Volume: 1-3" carries a 3rd slot's worth of pricing
    (cost_3_conv/price_original_3/etc.), which quote_win_processing.py now
    detects and standardizes (see build_quote_win_template_headers()), but
    the live table still needs those columns to exist before the INSERT
    below can reference them.

    Mirrors the same introspect-then-ALTER self-migration idiom
    reporting_module/database.py's connect() already uses for
    hierarchy_multiplier -- a no-op once a given slot's columns already
    exist, so safe to call on every write.
    """
    existing = {row[0] for row in conn.execute("DESCRIBE quote_win").fetchall()}
    for col in df_columns:
        if col in existing:
            continue
        for pattern, sql_type in _VOLUME_SLOT_COL_PATTERNS:
            if pattern.match(col):
                conn.execute(f"ALTER TABLE quote_win ADD COLUMN {col} {sql_type}")
                existing.add(col)
                break


def process_quote_win_to_database(rfq_id, standardized_df):

    df = standardized_df.copy()

    with connect_db(DB_PATH) as conn:

        _ensure_schema(conn)
        _ensure_volume_slot_columns(conn, df.columns)

        existing_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM quote_win
            WHERE rfq_id = ?
            """,
            [rfq_id]
        ).fetchone()[0]

        if existing_count > 0:

            return {
                "status": "failed",
                "error": f"RFQ ID {rfq_id} already exists in quote_win",
                "existing_rows": existing_count
            }

        conn.register("temp_df", df)

        # Column list built from the standardized DataFrame's own columns
        # (not a hardcoded 2-slot literal) -- df.columns already reflects
        # however many volume slots quote_win_processing.py detected for
        # this specific file, and _ensure_volume_slot_columns() above just
        # guaranteed the live table has a matching column for every one of
        # them.
        columns_sql = ",\n            ".join(df.columns)
        conn.execute(f"""
        INSERT INTO quote_win
        (
            {columns_sql},
            rfq_id
        )
        SELECT
            {columns_sql},
            ?
        FROM temp_df
        """, [rfq_id])

        conn.unregister("temp_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }
