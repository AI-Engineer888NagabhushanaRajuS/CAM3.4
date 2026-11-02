"""DuckDB connection management. `connect()` is the one place that opens all three
databases -- it is the load-bearing guarantee that `input_db.duckdb` is NEVER opened for
writing by this module: every other file that needs a connection goes through here.
"""

import duckdb

import config
import schema


def _column_type(con, table, column):
    try:
        rows = con.execute(f"DESCRIBE {table}").fetchall()
    except duckdb.CatalogException:
        return None  # table not created yet (fresh database): no column type to read
    for row in rows:
        if row[0] == column:
            return row[1]
    return None


def _rebuild_table_with_new_ddl(con, table, create_ddl):
    """DuckDB (as of 1.5.3) refuses ALTER TABLE ... ALTER COLUMN TYPE on a column that's
    part of a UNIQUE/PRIMARY KEY constraint ("Cannot change the type of a column that
    has a UNIQUE or PRIMARY KEY constraint specified") -- cbom.volume_no and
    summary_report.volume_no are both part of such a constraint, so the simple
    ALTER-in-place idiom used elsewhere in this function (line_no, and every other
    report table's volume_no) doesn't work for these two. Instead: rename the old table
    aside, recreate it fresh via its own up-to-date CREATE TABLE DDL (already declaring
    volume_no VARCHAR, including the constraint), copy every row across (DuckDB
    implicitly widens SMALLINT/INTEGER -> VARCHAR on INSERT ... SELECT), then drop the
    renamed-aside original. Only called when the existing column is confirmed to still
    be the old type, so this never runs against an already-migrated table.
    """
    # RENAME TO only accepts a bare (unqualified) target name -- it stays in the same
    # schema as the source implicitly -- but every other reference to the renamed-aside
    # table below must stay schema-qualified (multiple databases are attached).
    if "." in table:
        schema_name, bare_name = table.split(".", 1)
        old_bare = f"{bare_name}__pre_proto_migration"
        old_qualified = f"{schema_name}.{old_bare}"
    else:
        old_bare = f"{table}__pre_proto_migration"
        old_qualified = old_bare
    # One transaction: a failure part-way must roll the rename back, never strand the rows in
    # the renamed-aside table (the next connect() would no longer see the old type to recover).
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DROP TABLE IF EXISTS {old_qualified}")
        con.execute(f"ALTER TABLE {table} RENAME TO {old_bare}")
        con.execute(create_ddl)
        con.execute(f"INSERT INTO {table} SELECT * FROM {old_qualified}")
        con.execute(f"DROP TABLE {old_qualified}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def connect():
    """One connection: reports.duckdb as the main catalog, cbom.duckdb attached
    read-write (it's our own generated artifact), input_db.duckdb attached STRICTLY
    READ-ONLY (the four input tables are prepared once by migrations.py / an external
    loader, never by this module).
    """
    con = duckdb.connect(config.REPORTS_DB_PATH)
    con.execute(f"ATTACH '{config.CBOM_DB_PATH}' AS cbom_db")
    con.execute(f"ATTACH '{config.INPUT_DB_PATH}' AS input_db (READ_ONLY)")
    # cbom.volume_no's SMALLINT -> VARCHAR migration (now holding "proto" alongside
    # numbered volumes "1"/"2"/... -- see queries.py's PROTO support) must happen BEFORE
    # the CREATE TABLE IF NOT EXISTS below (a no-op against an already-existing table) --
    # and needs the rebuild path, not a plain ALTER, because volume_no is part of
    # cbom's UNIQUE (rfq_id, bom_item_id, volume_no) constraint.
    if _column_type(con, "cbom_db.cbom", "volume_no") == "SMALLINT":
        _rebuild_table_with_new_ddl(con, "cbom_db.cbom", schema.CBOM_DDL)
    con.execute(schema.CBOM_DDL)
    # ponytail: cbom is our own generated artifact (freely evolvable, no migration
    # ceremony) -- CREATE TABLE IF NOT EXISTS won't retype an already-existing table, so
    # line_no's INTEGER -> VARCHAR change (now holding "Line_{n}") needs one idempotent
    # ALTER on top of it. (Not part of any constraint, so the simple in-place ALTER
    # works here, unlike volume_no above.)
    if _column_type(con, "cbom_db.cbom", "line_no") == "INTEGER":
        con.execute("ALTER TABLE cbom_db.cbom ALTER COLUMN line_no TYPE VARCHAR")
    # New column (not a retype) -- ADD COLUMN needs no index/constraint workaround.
    if _column_type(con, "cbom_db.cbom", "hierarchy_multiplier") is None:
        con.execute("ALTER TABLE cbom_db.cbom ADD COLUMN hierarchy_multiplier DOUBLE")
    # summary_report.volume_no has the same UNIQUE-constraint-blocks-ALTER problem as
    # cbom.volume_no above (UNIQUE (rfq_id, fg, volume_no)) -- same rebuild path, run
    # before its own CREATE TABLE IF NOT EXISTS in the loop below.
    if _column_type(con, "summary_report", "volume_no") == "INTEGER":
        _rebuild_table_with_new_ddl(con, "summary_report", schema.REPORT_DDLS["summary_report"])
    for ddl in schema.REPORT_DDLS.values():
        con.execute(ddl)
    # cbom_vl_report was created via "AS SELECT * FROM cbom_db.cbom WHERE FALSE" (a
    # structural schema copy, which does NOT carry over cbom's own constraints -- so no
    # rebuild-path needed here, a plain ALTER works) the first time this ran, back when
    # line_no was still INTEGER -- CREATE TABLE IF NOT EXISTS doesn't retype it, so it
    # needs the same idempotent ALTER as cbom.line_no itself.
    if _column_type(con, "cbom_vl_report", "line_no") == "INTEGER":
        con.execute("ALTER TABLE cbom_vl_report ALTER COLUMN line_no TYPE VARCHAR")
    if _column_type(con, "cbom_vl_report", "volume_no") == "SMALLINT":
        con.execute("ALTER TABLE cbom_vl_report ALTER COLUMN volume_no TYPE VARCHAR")
    # Same reasoning as cbom_db.cbom's own hierarchy_multiplier migration above --
    # queries.py's report_insert_sqls()["cbom_vl_report"] does a bare positional
    # `INSERT INTO cbom_vl_report SELECT * FROM cbom_db.cbom`, which requires both
    # tables to have the same column COUNT (confirmed real failure: "table
    # cbom_vl_report has 78 columns but 79 values were supplied") -- this ADD COLUMN
    # appends at cbom_vl_report's own end, same relative position ADD COLUMN already
    # gave cbom_db.cbom's own copy above, keeping the two positionally aligned.
    if _column_type(con, "cbom_vl_report", "hierarchy_multiplier") is None:
        con.execute("ALTER TABLE cbom_vl_report ADD COLUMN hierarchy_multiplier DOUBLE")
    # The remaining REPORT_DDLS tables that declare their own volume_no INTEGER column
    # (rather than copying cbom's schema) and carry no constraint on it -- plain ALTER
    # works directly, no rebuild needed.
    for report_table in ("bom_matrix_report", "revision_history_report", "batchwise_cashflow_report", "ex_inv_vl_report"):
        if _column_type(con, report_table, "volume_no") == "INTEGER":
            con.execute(f"ALTER TABLE {report_table} ALTER COLUMN volume_no TYPE VARCHAR")
    return con
