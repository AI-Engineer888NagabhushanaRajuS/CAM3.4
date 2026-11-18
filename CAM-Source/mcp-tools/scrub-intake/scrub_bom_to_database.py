import os
import uuid
from pathlib import Path

import duckdb

# Dedicated DuckDB file for Centum SCRUB BOM data -- this file also holds
# batch, quote_win, costing_sheet, and erp tables (out of scope here).
#
# Points at this project's own database/input_db.duckdb -- the same file
# reporting_module/config.py already defaults to, with the correct/complete
# schema (costing_sheet, erp tables, rfq_id everywhere, etc.) validated this
# session -- NOT the production file at C:\SRIM-DB-SETUP\Centum_DB\, which
# holds real data under an older, incompatible schema (confirmed earlier
# this session) and stays untouched, as it has been throughout.
DB_PATH = Path(
    os.environ.get(
        "CENTUM_INPUT_DB",
        str(Path(__file__).resolve().parent / "database" / "input_db.duckdb"),
    )
)

LOCK_WAIT_SECONDS = float(os.environ.get("CAM_DUCKDB_LOCK_WAIT", "90"))


def connect_db(path=None, read_only=False):
    """duckdb.connect that waits out a file lock held by a process outside CAM's advisory lock (db.duckdb_file_lock).
    Found 2026-11-18 in a batch run: 'Could not set lock on file input_db.duckdb: Conflicting lock is held in PID 0', the
    SCRUB BOM step failed and the run lost its BOM. A reader such as a dashboard holds the file for seconds, so waiting is
    the right answer; after LOCK_WAIT_SECONDS the error is raised as before."""
    import time
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            return duckdb.connect(str(path or DB_PATH), read_only=read_only)
        except duckdb.IOException as e:
            if "lock" not in str(e).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(2)


# ==========================================================
# SCHEMA — scrub_bom_items
#
# CREATE TABLE IF NOT EXISTS is used deliberately (never DROP TABLE)
# so this module can safely self-provision the schema on every call
# without destroying previously imported rows. Mirrors the live
# production schema exactly, including display_order and bom_item_id
# having no DEFAULT — bom_item_id is generated in Python before insert.
# ==========================================================

SCRUB_BOM_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS scrub_bom_items (

    -- System Identifiers
    bom_item_id UUID PRIMARY KEY,
    rfq_id VARCHAR,

    -- SCRUB BOM Columns
    fg VARCHAR,
    level VARCHAR,
    assembly VARCHAR,
    cpn VARCHAR,
    description TEXT,
    manufacturer VARCHAR,
    mpn VARCHAR,
    commodity VARCHAR,
    quantity DOUBLE,
    unit_of_measure VARCHAR,
    part_status VARCHAR,
    ce_remarks TEXT,
    drawing_reference VARCHAR,
    designators TEXT,
    -- VARCHAR, not INTEGER: item_number is a free-form identifier in real Scrub BOM
    -- exports (confirmed: plain text, and CPN-shaped values far too large for INT32)
    -- -- see scrub_bom_processing.py's _coerce_item_number() docstring.
    item_number VARCHAR,
    part_type VARCHAR,
    ltb_date DATE,
    common_aml VARCHAR,
    change_remarks TEXT,
    inventory_stock DOUBLE,
    -- Cumulative ancestor-assembly quantity multiplier for this row's own `assembly`
    -- value, walking up to the FG root -- see scrub_bom_processing.py's
    -- _build_hierarchy_multipliers() docstring for the real-data bug this fixes
    -- (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md). Always >= 1, never NULL.
    hierarchy_multiplier DOUBLE,

    -- Tracking
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    exported_at TIMESTAMP,
    display_order INTEGER
)
"""


def _column_type(conn, table, column):
    for row in conn.execute(f"DESCRIBE {table}").fetchall():
        if row[0] == column:
            return row[1]
    return None


def _ensure_schema(conn):

    # Idempotent migration for a pre-existing table created before item_number became
    # VARCHAR (see SCRUB_BOM_ITEMS_DDL's own comment) -- CREATE TABLE IF NOT EXISTS
    # below won't retype an already-existing column. item_number itself isn't part of
    # any constraint, but a plain ALTER COLUMN TYPE still fails ("Cannot alter entry
    # ... because there are entries that depend on it") while idx_scrub_bom_items_rfq
    # exists on the table at all (confirmed: DuckDB blocks retyping ANY column on a
    # table with an index, not just an indexed one) -- drop it first, alter, then let
    # the CREATE INDEX IF NOT EXISTS below recreate it. Must run BEFORE the CREATE
    # TABLE IF NOT EXISTS, which is a no-op against an existing table.
    existing_tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    if "scrub_bom_items" in existing_tables and _column_type(conn, "scrub_bom_items", "item_number") == "INTEGER":
        conn.execute("DROP INDEX IF EXISTS idx_scrub_bom_items_rfq")
        conn.execute("ALTER TABLE scrub_bom_items ALTER COLUMN item_number TYPE VARCHAR")

    # Idempotent migration for a pre-existing table created before hierarchy_multiplier
    # existed -- a new column needs no index drop (unlike the retype above), ADD COLUMN
    # works directly even with idx_scrub_bom_items_rfq in place.
    if "scrub_bom_items" in existing_tables and _column_type(conn, "scrub_bom_items", "hierarchy_multiplier") is None:
        conn.execute("ALTER TABLE scrub_bom_items ADD COLUMN hierarchy_multiplier DOUBLE")

    conn.execute(SCRUB_BOM_ITEMS_DDL)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scrub_bom_items_rfq
        ON scrub_bom_items(rfq_id)
        """
    )


def process_scrub_bom_to_database(rfq_id, standardized_df):

    df = standardized_df.copy()

    # bom_item_id has no DEFAULT in the live schema — generate explicitly.
    df["bom_item_id"] = [str(uuid.uuid4()) for _ in range(len(df))]

    # Preserve the standardized output's original row order.
    df["display_order"] = range(1, len(df) + 1)

    with connect_db(DB_PATH) as conn:

        _ensure_schema(conn)

        existing_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM scrub_bom_items
            WHERE rfq_id = ?
            """,
            [rfq_id]
        ).fetchone()[0]

        if existing_count > 0:

            # Idempotent no-op, not a failure: (rfq_id, version) already has its
            # rows -- the ONLY way a caller ever wants genuinely fresh data for
            # the same rfq_id is via upload_server.py's versioning (a new,
            # distinct versioned key), which never reaches this branch in the
            # first place. This branch instead fires when the SAME already-
            # ingested (rfq_id, version) gets processed again -- in practice,
            # Dify's own workflow unconditionally re-calls standardize_scrub_bom
            # on every resume trigger (e.g. after a QuoteWin upload), regardless
            # of whether it already succeeded once. Reporting that as "failed"
            # made a perfectly healthy intake look broken in the UI (see
            # fastapi_router.py's /tool/execute status="failed" handling).
            return {
                "status": "success",
                "rows_inserted": 0,
                "already_processed": True,
                "existing_rows": existing_count
            }

        conn.register("temp_df", df)

        conn.execute("""
        INSERT INTO scrub_bom_items
        (
            bom_item_id,
            rfq_id,

            fg,
            level,
            assembly,

            cpn,
            description,
            manufacturer,
            mpn,

            commodity,

            quantity,
            unit_of_measure,

            part_status,
            ce_remarks,
            drawing_reference,
            designators,
            item_number,
            part_type,
            ltb_date,
            common_aml,
            change_remarks,
            inventory_stock,
            hierarchy_multiplier,

            exported_at,
            display_order
        )
        SELECT
            bom_item_id,
            ?,

            fg,
            level,
            assembly,

            cpn,
            description,
            manufacturer,
            mpn,

            commodity,

            quantity,
            unit_of_measure,

            part_status,
            ce_remarks,
            drawing_reference,
            designators,
            item_number,
            part_type,
            ltb_date,
            common_aml,
            change_remarks,
            inventory_stock,
            hierarchy_multiplier,

            exported_at,
            display_order
        FROM temp_df
        """, [rfq_id])

        conn.unregister("temp_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }


# ==========================================================
# SCHEMA — volume (Settings sheet)
# ==========================================================

VOLUME_DDL = """
CREATE TABLE IF NOT EXISTS volume (
    fg VARCHAR,
    volume_name VARCHAR,
    batch_qty DOUBLE,
    rfq_id VARCHAR
)
"""


def _ensure_volume_schema(conn):

    conn.execute(VOLUME_DDL)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_volume_rfq
        ON volume(rfq_id)
        """
    )


def process_volume_to_database(rfq_id, volume_df):

    df = volume_df.copy()

    with connect_db(DB_PATH) as conn:

        _ensure_volume_schema(conn)

        existing_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM volume
            WHERE rfq_id = ?
            """,
            [rfq_id]
        ).fetchone()[0]

        # `or len(df) == 0` -- a Scrub BOM workbook with no Volume sheet data at all
        # (the normal case for CAM: only a BOM + QuoteWin are ever uploaded, no
        # separate Volume/Batch file) means existing_count stays 0 forever, on the
        # first run AND every re-run alike -- there is never anything to find as
        # "already existing". Without this, already_processed never becomes True
        # for this table, fastapi_router.py's /tool/execute's already_processed
        # check (see process_scrub_bom_to_database()'s docstring) is a strict all(),
        # and centum_intake__standardize_scrub_bom's own hitl flag (scrub_mcp_server.py)
        # re-fires forever on every resume attempt -- the intake HITL gate can never
        # clear. Confirmed against RFQ-000118: an empty-volume/batch BOM stuck at
        # rfq_process_stage=0 even after QuoteWin upload + /api/dify/start resume.
        # Safe on the FIRST run too: an empty-Volume workbook's already_processed=True
        # here doesn't skip the intake pause on its own -- scrub_bom_items (a real
        # BOM always has line items) still correctly reports already_processed=False
        # on that first call, which is what the overall all()-check actually keys on.
        if existing_count > 0 or len(df) == 0:

            # Idempotent no-op, not a failure -- see process_scrub_bom_to_database()'s
            # matching comment for the full reasoning (same Dify re-trigger cause).
            return {
                "status": "success",
                "rows_inserted": 0,
                "already_processed": True,
                "existing_rows": existing_count
            }

        conn.register("temp_volume_df", df)

        conn.execute("""
        INSERT INTO volume
        (
            fg,
            volume_name,
            batch_qty,
            rfq_id
        )
        SELECT
            fg,
            volume_name,
            batch_qty,
            ?
        FROM temp_volume_df
        """, [rfq_id])

        conn.unregister("temp_volume_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }


# ==========================================================
# SCHEMA — batch (Batch sheet)
# ==========================================================

BATCH_DDL = """
CREATE TABLE IF NOT EXISTS batch (
    fg VARCHAR,
    volume VARCHAR,
    batch_qty DOUBLE,
    rfq_id VARCHAR
)
"""


def _ensure_batch_schema(conn):

    conn.execute(BATCH_DDL)

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_batch_rfq
        ON batch(rfq_id)
        """
    )


def process_batch_to_database(rfq_id, batch_df):

    df = batch_df.copy()

    with connect_db(DB_PATH) as conn:

        _ensure_batch_schema(conn)

        existing_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM batch
            WHERE rfq_id = ?
            """,
            [rfq_id]
        ).fetchone()[0]

        # `or len(df) == 0` -- same reasoning as process_volume_to_database()'s
        # matching guard: a Batch-less Scrub BOM workbook (the normal CAM case)
        # never accumulates existing_count > 0, so already_processed would never
        # become True and the intake HITL gate would never clear. See that
        # function's own comment for the full explanation and the RFQ-000118
        # real-world confirmation.
        if existing_count > 0 or len(df) == 0:

            # Idempotent no-op, not a failure -- see process_scrub_bom_to_database()'s
            # matching comment for the full reasoning (same Dify re-trigger cause).
            return {
                "status": "success",
                "rows_inserted": 0,
                "already_processed": True,
                "existing_rows": existing_count
            }

        conn.register("temp_batch_df", df)

        conn.execute("""
        INSERT INTO batch
        (
            fg,
            volume,
            batch_qty,
            rfq_id
        )
        SELECT
            fg,
            volume,
            batch_qty,
            ?
        FROM temp_batch_df
        """, [rfq_id])

        conn.unregister("temp_batch_df")

    return {
        "status": "success",
        "rows_inserted": len(df)
    }
