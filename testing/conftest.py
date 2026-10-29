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
