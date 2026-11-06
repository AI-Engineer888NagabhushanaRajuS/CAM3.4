"""Shared fixtures for CAM 3.4 test suite.

Sets up an in-memory DuckDB that mirrors the 3-database structure of database.connect():
  - main connection  = reports database (16 report tables)
  - cbom_db attached = cbom table
  - input_db attached = scrub_bom_items, quote_win, volume, batch

Mocks Postgres-backed currency and scrap_factor caches so tests run without a live
Postgres instance.
"""

import os
import sys
import types
import pytest
import duckdb

# Inject stub modules so importing currency/scrap_factor doesn't require psycopg2.
# db.py does `import psycopg2` at module level; stub it before any source import.
def _stub_psycopg2():
    """Inject minimal psycopg2 stub + required env vars so db.py imports cleanly."""
    if "psycopg2" not in sys.modules:
        stub = types.ModuleType("psycopg2")
        stub.connect = lambda *a, **kw: None
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = object
        stub.extras = extras
        sys.modules["psycopg2"] = stub
        sys.modules["psycopg2.extras"] = extras
    # db.py reads these at module level; dummy values are fine — we never connect
    for var in ("LOGIC_DB_URL", "FILE_METADATA_DB_URL", "JWT_SECRET", "DATABASE_URL"):
        if var not in os.environ:
            os.environ[var] = f"postgresql://test:test@localhost/test_stub"

_stub_psycopg2()

# ── Path setup ────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_REPORTING_DIR = os.path.join(_REPO_ROOT, "mcp-tools", "reporting", "superset")
_FASTMCP_DIR = os.path.join(_REPO_ROOT, "fastmcp-router")

# tests/ first so _constants is importable; fastmcp-router before reporting for db.py
for d in (_TESTS_DIR, _FASTMCP_DIR, _REPORTING_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

from _constants import SYNTHETIC_RFQ_ID, SYNTHETIC_PARTS as _PARTS


@pytest.fixture(scope="session")
def synthetic_rfq_id():
    return SYNTHETIC_RFQ_ID


@pytest.fixture(scope="session", autouse=True)
def mock_postgres_caches():
    """Pre-populate Postgres-backed caches so tests run without a live Postgres.

    currency._rates_cache: {"USD": 1.0, "INR": 83.5, "EUR": 0.93}
    scrap_factor._table_cache: standard 3-tier A/B/C config
    """
    import currency
    import scrap_factor

    currency._rates_cache = {"USD": 1.0, "INR": 83.5, "EUR": 0.93}
    currency._default_currency_cache = "USD"
    scrap_factor._table_cache = [
        {"min_price": 1.25, "max_price": float("inf"), "abc_class": "A", "scrap_pct": 0.01},
        {"min_price": 0.25, "max_price": 1.25,         "abc_class": "B", "scrap_pct": 0.02},
        {"min_price": 0.0,  "max_price": 0.25,         "abc_class": "C", "scrap_pct": 0.05},
    ]
    yield
    currency.clear_cache()
    scrap_factor.clear_cache()


def _build_reporting_con(rfq_id: str) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB mirroring database.connect()'s 3-database structure."""
    import schema

    con = duckdb.connect()  # in-memory main (reports)
    con.execute("ATTACH ':memory:' AS cbom_db")
    con.execute("ATTACH ':memory:' AS input_db")

    # cbom table (in cbom_db)
    con.execute(schema.CBOM_DDL)

    # minimal input_db tables (schema inferred from queries.py JOIN columns)
    con.execute("""
        CREATE TABLE input_db.scrub_bom_items (
            bom_item_id     VARCHAR,
            rfq_id          VARCHAR,
            fg              VARCHAR,
            assembly        VARCHAR,
            cpn             VARCHAR,
            description     VARCHAR,
            mfr             VARCHAR,
            manufacturer    VARCHAR,
            mpn             VARCHAR,
            commodity       VARCHAR,
            quantity        DOUBLE,
            uom             VARCHAR,
            inventory_stock DOUBLE,
            part_status     VARCHAR,
            display_order   INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE input_db.quote_win (
            project          VARCHAR,
            part_number      VARCHAR,
            part_description VARCHAR,
            commodity        VARCHAR,
            mfg_name         VARCHAR,
            mfg_part_number  VARCHAR,
            cost_1_conv      DOUBLE,
            price_original_1 DOUBLE,
            cost_2_conv      DOUBLE,
            price_original_2 DOUBLE,
            currency_original VARCHAR,
            supp_name        VARCHAR,
            supplier_type    VARCHAR,
            pkg_qty          DOUBLE,
            moq              DOUBLE,
            lead_time        DOUBLE,
            awarded_volume_1 DOUBLE,
            award_1          DOUBLE,
            awarded_volume_2 DOUBLE,
            award_2          DOUBLE,
            part_qty         DOUBLE,
            corrected_mpn    VARCHAR,
            long_comment     VARCHAR,
            source_1         VARCHAR,
            source_2         VARCHAR,
            price_type       VARCHAR,
            no_bid_reason    VARCHAR,
            short_comment    VARCHAR,
            ncnr             VARCHAR,
            rfq_number       VARCHAR,
            eff_date         DATE,
            exp_date         DATE,
            quote_validity   VARCHAR,
            part_status      VARCHAR,
            rfq_id           VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE input_db.volume (
            rfq_id      VARCHAR,
            fg          VARCHAR,
            volume_name VARCHAR,
            batch_qty   DOUBLE
        )
    """)
    con.execute("""
        CREATE TABLE input_db.batch (
            rfq_id  VARCHAR,
            volume  VARCHAR
        )
    """)

    # report tables (in main / reports db)
    for ddl in schema.REPORT_DDLS.values():
        con.execute(ddl)

    _insert_synthetic_data(con, rfq_id)
    return con


def _insert_synthetic_data(con, rfq_id: str):
    # Volume/batch rows so detect_volumes() returns ["1"]
    con.execute("INSERT INTO input_db.volume VALUES (?, 'TEST-FG-001', 'V1', 1000.0)", [rfq_id])
    con.execute("INSERT INTO input_db.batch VALUES (?, 'V1')", [rfq_id])

    for i, (bom_id, cpn, fg, asm, is_asm, commodity) in enumerate(_PARTS):
        price = 1.5 + i * 0.5   # ensures A/B/C class spread
        ext_qty = 10.0 if not is_asm else 1.0

        con.execute("""
            INSERT INTO input_db.scrub_bom_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [bom_id, rfq_id, fg, asm, cpn,
              f"Test Part {i+1}", "ACME", "ACME Corp", f"MPN-{i+1:03d}",
              commodity, 10.0, "Number", 5.0, "Active", i + 1])

        con.execute("""
            INSERT INTO cbom_db.cbom (
                cbom_item_id, rfq_id, bom_item_id, volume_no,
                fg, assembly, cpn, description, commodity,
                unit_of_measure_costing, final_unit_of_measure,
                part_qty, hierarchy_multiplier, line_no, display_order,
                final_mfg_name, mfg_part_number, ext_vol_qty,
                final_price_conv, final_price_original, final_currency_original,
                final_supp_name, final_pkg_qty, final_moq, final_lead_time,
                batch_qty, volume_qty, nre_charge, scrap_percent,
                ext_price_conv, ext_part_vol_price_conv, price_control,
                is_costed, is_assembly, parent_line_no, abc_classification,
                recurring_count, is_price_same, is_mpn_same
            ) VALUES (
                gen_random_uuid(), ?,?,?,
                ?,?,?,?,?,
                'Number','Number',
                10.0, 1.0, ?, ?,
                'ACME Corp', ?, ?,
                ?, ?, 'USD',
                'ACME', 10.0, 100.0, 8,
                1000.0, 1000.0, 0.0, 0.02,
                ?, ?, 'Centum',
                TRUE, ?, 0, 'A',
                1, TRUE, TRUE
            )
        """, [rfq_id, bom_id, "1",
              fg, asm, cpn, f"Test Part {i+1}", commodity,
              f"Line_{i+1}", i + 1,
              f"MPN-{i+1:03d}", ext_qty,
              price, price,
              price * ext_qty, price * ext_qty,
              is_asm])

        if not is_asm:
            con.execute("""
                INSERT INTO input_db.quote_win (
                    project, part_number, part_description, commodity,
                    mfg_name, mfg_part_number,
                    cost_1_conv, price_original_1, cost_2_conv, price_original_2,
                    currency_original, supp_name, supplier_type,
                    pkg_qty, moq, lead_time,
                    awarded_volume_1, award_1, awarded_volume_2, award_2,
                    part_qty, corrected_mpn, price_type, ncnr,
                    eff_date, exp_date, quote_validity, part_status, rfq_id
                ) VALUES (
                    'TEST', ?, ?, ?,
                    'ACME Corp', ?,
                    ?, ?, ?, ?,
                    'USD', 'ACME Dist', 'Distributor',
                    10.0, 100.0, 8.0,
                    1000.0, 1000.0, NULL, NULL,
                    10.0, NULL, 'Standard', 'NO',
                    '2026-01-01', '2027-12-31', '90 days', 'Active', ?
                )
            """, [cpn, f"Test Part {i+1}", commodity,
                  f"MPN-{i+1:03d}",
                  price, price, price, price,
                  rfq_id])


@pytest.fixture
def reporting_con():
    """In-memory DuckDB with cbom_db + input_db + 16 report tables + synthetic data."""
    con = _build_reporting_con(SYNTHETIC_RFQ_ID)
    yield con
    con.close()
