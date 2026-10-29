# CAM 3.4 Test Suite

## Setup

```bash
pip install -r requirements-test.txt
```

## Run all tests

```bash
cd C:\CAM[3.4]-RFQ_centum\CAM-Source
pytest testing/ -v
```

## Test coverage

| Test file | What it covers |
|-----------|----------------|
| `test_reports.py` | All 16 DuckDB report tables exist, have rfq_id column, match REPORT_ORDER in constants.py |
| `test_routing.py` | DUCKDB_SCOPED_TOOLS and SCRUB_TOOLS sets in fastapi_router.py are correct and disjoint |

## Adding tests

- Add test files to `testing/` with prefix `test_`
- Use the `con` fixture from `conftest.py` for in-memory DuckDB access
- Use the `rfq_id` fixture for a consistent test RFQ ID (`TEST-CE-001`)
- Precondition checks should `raise` with a clear message, never silently no-op
