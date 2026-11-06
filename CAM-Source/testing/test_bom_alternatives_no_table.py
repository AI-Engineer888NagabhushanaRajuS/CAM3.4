"""GET /api/bom/alternatives/{rfq} must answer "no alternates" when the distributor's
detect_alternates step never ran.

Found by the first UI take (RFQ-CENTUM-PROOF-02, Standard_BOM_Flow): that profile never creates
update_alternatives, so the endpoint raised CatalogException -> 500 with no CORS headers (the browser
reported it as a CORS block), and the UI stayed on "continuing automatically" forever.
"""
import os
import sys

import duckdb
import pytest
from fastapi.testclient import TestClient

FR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fastapi-router"))


@pytest.fixture
def api(monkeypatch):
    sys.path.insert(0, FR_DIR)
    try:
        import duck_db_api
    finally:
        sys.path.remove(FR_DIR)
    yield duck_db_api
    duck_db_api.app.dependency_overrides.clear()


def test_alternatives_is_empty_when_no_alternates_table(api, tmp_path, monkeypatch):
    db = tmp_path / "bom_storage.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE processed_bom_items (rfq_id VARCHAR, cpn VARCHAR, mpn VARCHAR)")
    con.execute("INSERT INTO processed_bom_items VALUES ('RFQ-X', 'C1', 'M1')")
    con.close()
    monkeypatch.setattr(api, "BOM_STORAGE_DB_PATH", str(db))
    api.app.dependency_overrides[api.auth.verify_token] = lambda: {}

    resp = TestClient(api.app).get("/api/bom/alternatives/RFQ-X")

    assert resp.status_code == 200
    assert resp.json() == {"success": True, "rfq_id": "RFQ-X", "data": []}
