"""Smoke tests for the conftest fixtures themselves."""

from _constants import SYNTHETIC_RFQ_ID, SYNTHETIC_PARTS as _PARTS


def test_synthetic_rfq_id_fixture(synthetic_rfq_id):
    assert synthetic_rfq_id == "TEST-RFQ-001"


def test_reporting_con_has_cbom_rows(reporting_con):
    count = reporting_con.execute(
        "SELECT COUNT(*) FROM cbom_db.cbom WHERE rfq_id = ?", [SYNTHETIC_RFQ_ID]
    ).fetchone()[0]
    assert count == len(_PARTS), f"Expected {len(_PARTS)} cbom rows, got {count}"


def test_reporting_con_has_scrub_bom_rows(reporting_con):
    count = reporting_con.execute(
        "SELECT COUNT(*) FROM input_db.scrub_bom_items WHERE rfq_id = ?", [SYNTHETIC_RFQ_ID]
    ).fetchone()[0]
    assert count == len(_PARTS)


def test_reporting_con_has_volume_row(reporting_con):
    count = reporting_con.execute(
        "SELECT COUNT(*) FROM input_db.volume WHERE rfq_id = ?", [SYNTHETIC_RFQ_ID]
    ).fetchone()[0]
    assert count >= 1


def test_reporting_con_has_quote_win_rows(reporting_con):
    non_asm = sum(1 for p in _PARTS if not p[4])  # is_assembly is index 4
    count = reporting_con.execute(
        "SELECT COUNT(*) FROM input_db.quote_win WHERE rfq_id = ?", [SYNTHETIC_RFQ_ID]
    ).fetchone()[0]
    assert count == non_asm, f"Expected {non_asm} quote_win rows, got {count}"


def test_detect_volumes_returns_list(reporting_con):
    """detect_volumes() must return at least one volume from synthetic data."""
    import queries
    rfq_lit = f"'{SYNTHETIC_RFQ_ID}'"
    volumes = queries.detect_volumes(reporting_con, rfq_lit)
    assert isinstance(volumes, list) and len(volumes) >= 1
