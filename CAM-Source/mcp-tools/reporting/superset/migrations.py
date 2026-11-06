"""One-time, additive schema migrations for `input_db.duckdb` -- NOT part of the
generate_reports()/export_reports() call path, and never invoked automatically by them.
This is the ONLY file in this module that ever opens input_db.duckdb for writing;
everywhere else (database.py) attaches it strictly READ-ONLY.

Run these once against a freshly-loaded input_db.duckdb (one that has scrub_bom_items,
quote_win, batch, volume populated from a Scrub BOM/QuoteWin export, but doesn't yet have
the two extra columns this reporting engine requires):

    python migrations.py

Both migrations are idempotent (safe to re-run; they only touch NULL values) and
additive-only (they never delete or overwrite existing data, only add a column and
backfill it once). Both assert row counts are unchanged before/after as a hard safety
check, and raise SystemExit if that invariant is ever violated.

Why these two columns are required, not optional:
  - rfq_id (all 4 input tables): the whole reporting engine is RFQ-scoped -- every query
    filters WHERE rfq_id = ?. Without it, generate_reports()/export_reports() have
    nothing to scope by.
  - display_order (scrub_bom_items only): CBOM VL's "Recurring Count" column needs a
    genuine, stable row-sequence per volume to reproduce the real production Excel
    formula (`=COUNTIF($C$1:$C{r}, $C{r})`, which relies on physical row order).
    scrub_bom_items.item_number is not usable for this (it can repeat non-monotonically
    within an assembly and is sometimes NULL).
"""

import duckdb

import config


def _column_exists(con, table, column):
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    return column in cols


def _column_type(con, table, column):
    for row in con.execute(f"DESCRIBE {table}").fetchall():
        if row[0] == column:
            return row[1]
    return None


def ensure_rfq_id(con):
    """Backfills `rfq_id` (VARCHAR) across scrub_bom_items/quote_win/batch/volume, using
    quote_win.project as the source value (the only real identifier commonly present in
    these exports). Refuses to guess if more than one distinct project value is found --
    that scenario needs a real per-row RFQ mapping, not a single backfilled constant.
    """
    before_counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("scrub_bom_items", "quote_win", "batch", "volume")
    }

    projects = con.execute("SELECT DISTINCT project FROM quote_win WHERE project IS NOT NULL").fetchall()
    if len(projects) != 1:
        raise SystemExit(
            f"Expected exactly one distinct quote_win.project value to use as rfq_id, found {len(projects)}: {projects}. "
            "Refusing to guess which one to backfill with -- resolve manually before running this migration."
        )
    rfq_id = projects[0][0]
    print(f"Using rfq_id = {rfq_id!r}")

    if not _column_exists(con, "quote_win", "rfq_id"):
        con.execute("ALTER TABLE quote_win ADD COLUMN rfq_id VARCHAR")
        print("  quote_win: added rfq_id column")
    con.execute("UPDATE quote_win SET rfq_id = ? WHERE rfq_id IS NULL", [rfq_id])
    print("  quote_win: backfilled rfq_id on rows where it was NULL")

    current_type = _column_type(con, "scrub_bom_items", "rfq_id")
    if current_type and current_type.upper() != "VARCHAR":
        con.execute("ALTER TABLE scrub_bom_items ALTER COLUMN rfq_id TYPE VARCHAR")
        print(f"  scrub_bom_items: rfq_id type changed {current_type} -> VARCHAR")
    elif not _column_exists(con, "scrub_bom_items", "rfq_id"):
        con.execute("ALTER TABLE scrub_bom_items ADD COLUMN rfq_id VARCHAR")
        print("  scrub_bom_items: added rfq_id column")
    con.execute("UPDATE scrub_bom_items SET rfq_id = ? WHERE rfq_id IS NULL", [rfq_id])
    print("  scrub_bom_items: backfilled rfq_id on rows where it was NULL")

    for t in ("batch", "volume"):
        if not _column_exists(con, t, "rfq_id"):
            con.execute(f"ALTER TABLE {t} ADD COLUMN rfq_id VARCHAR")
            print(f"  {t}: added rfq_id column")
        con.execute(f"UPDATE {t} SET rfq_id = ? WHERE rfq_id IS NULL", [rfq_id])
        print(f"  {t}: backfilled rfq_id on rows where it was NULL")

    after_counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("scrub_bom_items", "quote_win", "batch", "volume")
    }
    for t in before_counts:
        if before_counts[t] != after_counts[t]:
            raise SystemExit(f"Row count changed for {t} during rfq_id backfill -- this must never happen in an additive migration")
    return rfq_id


def ensure_display_order(con):
    """Backfills `display_order` (INTEGER, 1..N) on scrub_bom_items, using the table's
    own current physical row-scan order. Only meaningful/correct if scrub_bom_items has
    never been reordered or partially modified since its original bulk load -- if you've
    since deleted/reordered rows, re-derive display_order from your original source data
    instead of trusting the current scan order.
    """
    before_count = con.execute("SELECT COUNT(*) FROM scrub_bom_items").fetchone()[0]

    if not _column_exists(con, "scrub_bom_items", "display_order"):
        con.execute("ALTER TABLE scrub_bom_items ADD COLUMN display_order INTEGER")
        print("scrub_bom_items: added display_order column")

    con.execute("""
        CREATE OR REPLACE TEMP VIEW ordered AS
        SELECT bom_item_id, ROW_NUMBER() OVER () AS rn FROM scrub_bom_items
    """)
    con.execute("""
        UPDATE scrub_bom_items
        SET display_order = ordered.rn
        FROM ordered
        WHERE scrub_bom_items.bom_item_id = ordered.bom_item_id
          AND scrub_bom_items.display_order IS NULL
    """)
    print("scrub_bom_items: backfilled display_order on rows where it was NULL")

    after_count = con.execute("SELECT COUNT(*) FROM scrub_bom_items").fetchone()[0]
    null_count = con.execute("SELECT COUNT(*) FROM scrub_bom_items WHERE display_order IS NULL").fetchone()[0]
    dup_count = con.execute("SELECT COUNT(*) - COUNT(DISTINCT display_order) FROM scrub_bom_items").fetchone()[0]

    if before_count != after_count:
        raise SystemExit("Row count changed during display_order backfill -- this must never happen in an additive migration")
    if null_count != 0 or dup_count != 0:
        raise SystemExit("display_order backfill did not produce a clean 1..N sequence")
    return {"before_count": before_count, "after_count": after_count}


def ensure_costing_and_erp_tables(con):
    """Adds the two new multi-source input tables (both start empty -- no data to load
    yet). `costing_sheet` is RFQ+assembly+part-number-scoped, matching cbom's own join
    keys; `erp` is a global procurement/inventory extract keyed by mpn+mfr only (no
    rfq_id) -- see cbom_insert_sql()'s `resolved` CTE for how each is joined in.
    """
    con.execute("""
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
    """)
    con.execute("""
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
    """)
    print("costing_sheet: table ready")
    print("erp: table ready")


def main():
    con = duckdb.connect(config.INPUT_DB_PATH)
    try:
        rfq_id = ensure_rfq_id(con)
        result = ensure_display_order(con)
        ensure_costing_and_erp_tables(con)
        print(f"\nMigrations complete. rfq_id={rfq_id!r}, scrub_bom_items rows={result['after_count']}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
