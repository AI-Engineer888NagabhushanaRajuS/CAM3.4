# SPEC-001: Baseline Pin + Test Infrastructure

**Status:** COMPLETED  
**Branch:** `feat/spec-001-baseline-infra`  
**Commit target:** `feat: add CAM 3.4 test infrastructure and spec tracking`

## Context

CAM 3.3 baseline was just committed and tagged `v3.3-baseline` at:
`C:\CAM[3.4]-RFQ_centum\Reference[KT]\BuLLMQuote-SRIM-containerization-delivery\BuLLMQuote-SRIM\`

The reporting module (`mcp-tools/reporting/superset/`) already has a `batch_validate_all_tests.py`
but there is no structured test harness for CAM 3.4 development. The `report_generator.py`
returns `{"counts": {...}, "issues": [...]}` but there is no automated check per-report
that asserts correctness of the output.

## What to Build

### 1. Create `tests/` directory structure

```
tests/
  __init__.py
  conftest.py           # shared fixtures: in-memory DuckDB, synthetic BOM data
  test_report_validators.py  # per-tab assertions (16 tests, one per REPORT_ORDER entry)
  fixtures/
    synthetic_scrub_bom.csv   # 50-row synthetic BOM (no real client data)
    synthetic_qw_awards.csv   # synthetic QuoteWin awards
    expected_counts.json      # expected row counts per report per rfq_id
```

### 2. `conftest.py` — shared DuckDB fixture

```python
import pytest, duckdb, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp-tools', 'reporting', 'superset'))

@pytest.fixture
def reporting_db():
    """In-memory DuckDB with reporting schema applied."""
    con = duckdb.connect(':memory:')
    import migrations
    migrations.run_all(con)
    return con

@pytest.fixture  
def synthetic_rfq_id():
    return "TEST-RFQ-001"
```

### 3. `test_report_validators.py` — one test per report table

For each table in `constants.REPORT_ORDER`, assert:
- `COUNT(*) > 0` after `generate_reports()` with synthetic data
- No entry in `issues` list for that table
- Key business columns are non-null (e.g., `bom_matrix_report` must have `part_number`, `unit_price`)

```python
import pytest
from report_generator import generate_reports, clear_reports_rfq
from constants import REPORT_ORDER

@pytest.mark.parametrize("table", REPORT_ORDER)
def test_report_generates_without_error(reporting_db, synthetic_rfq_id, table):
    # load synthetic data first
    _load_synthetic_data(reporting_db, synthetic_rfq_id)
    result = generate_reports(reporting_db, synthetic_rfq_id)
    
    # No error for this table
    errors = [i for i in result["issues"] if i["table"] == table]
    assert errors == [], f"{table} failed: {errors}"
    
    # Has rows
    assert result["counts"].get(table, 0) > 0, f"{table} returned 0 rows"
```

### 4. `SPECS/progress.json` — spec tracker

Create a JSON file tracking which spec is current:

```json
{
  "current_spec": "SPEC-001",
  "specs": {
    "SPEC-001": {"status": "in_progress", "branch": "feat/spec-001-baseline-infra"},
    "SPEC-002": {"status": "pending"},
    "SPEC-003": {"status": "pending"},
    "SPEC-004": {"status": "pending"},
    "SPEC-005": {"status": "pending"},
    "SPEC-006": {"status": "pending"}
  }
}
```

### 5. Add `pytest` and `duckdb` to `requirements.txt`

Check existing `requirements.txt` at repo root and in `mcp-tools/reporting/superset/requirements.txt`.
Add `pytest>=8.0` if not present.

## Files to Create/Modify

- `tests/__init__.py` (new, empty)
- `tests/conftest.py` (new)
- `tests/test_report_validators.py` (new)
- `tests/fixtures/synthetic_scrub_bom.csv` (new, 50 synthetic rows matching Scrub BOM format)
- `tests/fixtures/synthetic_qw_awards.csv` (new, synthetic QuoteWin awards)
- `SPECS/progress.json` (new)
- `requirements.txt` (add pytest if missing)

## Acceptance Criteria

1. `python -m pytest tests/test_report_validators.py -v` runs without import errors
2. At minimum, `summary_report` and `bom_matrix_report` tests pass (these are the most critical)
3. Any test failures list the specific report table and error message (not a cryptic traceback)
4. `SPECS/progress.json` exists and has correct structure
5. All new files committed to branch `feat/spec-001-baseline-infra`

## Synthetic Data Format

Synthetic Scrub BOM CSV header (matches `mcp-tools/scrub-intake/scrub_bom_processing.py`):
```
FG,Level,Assembly,CPN,Description,MFR,MPN,Commodity,Quantity,UOM,Inventory Stock
TEST-FG-001,0,TEST-FG-001,CPN-001,Test Part 1,ACME,MPN-001,Active,10,Number,0
TEST-FG-001,1,SUB-ASM-001,CPN-002,Test Resistor,VISHAY,RC0402,Passive,100,Number,0
```

Synthetic QuoteWin CSV: must match Awards Part Number Listing format.
```
Part Number,Part Description,Commodity,Mfg Name,Mfg Part Number,Cost #1,Award #1
CPN-002,Test Resistor,Passive,VISHAY,RC0402,0.01,100
```

## Domain Context for the Implementing Model

The 16 report tables are defined in `constants.REPORT_ORDER`. Each has a corresponding
Python file in `mcp-tools/reporting/superset/reports/`. The `generate_reports()` function
in `report_generator.py` iterates REPORT_ORDER, calls `queries.report_insert_sqls()` for
each table, and catches exceptions per-table (never stops on failure).

The test must load data into DuckDB first via the scrub BOM processing pipeline
OR directly insert synthetic rows into the `cbom` table (the easier path for a test fixture).

Key table: `cbom` is what all 16 reports read from. If `cbom` has data for `synthetic_rfq_id`,
the reports will generate. The `cbom` schema is in `schema.py`.
