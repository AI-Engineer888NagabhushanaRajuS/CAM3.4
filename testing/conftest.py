"""
Shared test fixtures for CAM 3.4 test suite.
Creates an in-memory DuckDB with all 16 report tables pre-seeded.
"""
import pytest
import duckdb

REPORT_TABLES = [
    "bom_matrix_report",
    "part_num_vs_mfg_num_report",
    "pcb_nre_fai_charge_report",
    "mech_em_nre_report",
    "missing_notes_report",
    "lead_time_fg_report",
    "lead_time_consolidated_report",
    "sum_and_count_report",
    "sum_and_count_detailed_report",
    "revision_history_report",
    "aclass_parts_report",
    "price_control_report",
    "summary_report",
    "batchwise_cashflow_report",
    "cbom_vl_report",
    "ex_inv_vl_report",
]

TEST_RFQ_ID = "TEST-CE-001"
TEST_RFQ_ID_V2 = "TEST-CE-001__v2"


@pytest.fixture(scope="session")
def con():
    """In-memory DuckDB pre-populated with all report table stubs and one test RFQ."""
    db = duckdb.connect(":memory:")

    # Core CBOM table (simplified for testing)
    db.execute("""
        CREATE TABLE cbom (
            rfq_id VARCHAR,
            volume_no INTEGER,
            fg VARCHAR,
            cpn VARCHAR,
            mfg_part_number VARCHAR,
            description VARCHAR,
            qty_per_assy DOUBLE,
            final_price_conv DOUBLE,
            final_currency_original VARCHAR,
            final_moq INTEGER,
            final_pkg_qty INTEGER,
            is_costed BOOLEAN,
            abc_classification VARCHAR,
            price_control VARCHAR
        )
    """)
    db.execute(
        "INSERT INTO cbom VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [TEST_RFQ_ID, 1, "FG-001", "CPN-001", "MPN-ABC123", "Resistor 10K", 2.0, 0.05, "USD", 100, 10, True, "C", "OK"],
    )

    # Create each report table with minimal schema (rfq_id + row_num are always present)
    for table in REPORT_TABLES:
        db.execute(f"CREATE TABLE {table} (rfq_id VARCHAR, row_num INTEGER, data VARCHAR)")

    yield db
    db.close()


@pytest.fixture
def rfq_id():
    return TEST_RFQ_ID


@pytest.fixture
def rfq_id_v2():
    return TEST_RFQ_ID_V2


# --- per-module source dir isolation -------------------------------------------------
# temporal_worker/, fastapi-router/ and the reporting package each ship a flat
# `config.py` (plus client/workflow/...). In one pytest process the first import wins
# in sys.modules, so later test modules got the wrong `config`. Give every test module
# its own dir first on sys.path and a clean module cache.
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DIRS = {
    "temporal_worker": os.path.join(_ROOT, "temporal_worker"),
    "fastapi-router": os.path.join(_ROOT, "fastapi-router"),
    "reporting": os.path.join(_ROOT, "mcp-tools", "reporting", "superset"),
}
_MODULE_DIR = {
    "test_hitl_signals": "temporal_worker",
    "test_temporal_workflow": "temporal_worker",
    "test_shadow_run_parity": "fastapi-router",
    "test_routing": "fastapi-router",
    "test_rfq_chat": "fastapi-router",
    "test_security_fixes": "fastapi-router",
    "test_posthog_events": "reporting",
    "test_report_validators": "reporting",
    "test_reports": "reporting",
}


@pytest.fixture(autouse=True)
def _isolate_source_dir(request):
    key = _MODULE_DIR.get(request.module.__name__.rsplit(".", 1)[-1])
    if key is None:
        return
    base = tuple(p + os.sep for p in _DIRS.values())
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and os.path.abspath(f).startswith(base):
            del sys.modules[name]
    for p in _DIRS.values():
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, _DIRS[key])
