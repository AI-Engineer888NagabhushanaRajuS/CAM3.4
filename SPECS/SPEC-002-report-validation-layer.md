# SPEC-002: Fix 16 Reports + Add Per-Tab Validation Layer

**Status:** COMPLETED  
**Branch:** `feat/spec-002-report-validation`  
**Commit target:** `feat: add per-tab report validation with business-rule assertions`  
**Depends on:** SPEC-001 (test infrastructure)

## Context

The 16 reports in `mcp-tools/reporting/superset/reports/` are implemented in Python but have
known failures. The tracker shows 43 issues, 13 fixed. The `report_generator.py` already returns
`{"counts": {...}, "issues": [...]}` — errors are caught but not validated against business rules.

Known failures from production (from Domain 4 knowledge):
1. `price_control_report`: Uses GETPIVOTDATA logic that generates `#REF!` errors in Excel output
2. `bom_matrix_report`: Cross-check failures between CBOM Summary vs BOM Matrix Summary
3. `sum_and_count_report` + `sum_and_count_detailed_report`: `Is Sum Same` / `Is Count Same` flags

The reporting module has `batch_validate_all_tests.py` and `validator.py` — use these as a base.

## What to Build

### 1. Per-tab validation functions in `mcp-tools/reporting/superset/validator.py`

Add or extend a `validate_report_tab(con, rfq_id, table_name)` function that checks
business-rule assertions per report. Each validator returns:
```python
{"table": str, "passed": bool, "checks": [{"name": str, "passed": bool, "detail": str}]}
```

Required checks per key report:

#### `bom_matrix_report`
- Row count > 0
- All `part_number` values non-null
- Grand total column sums match CBOM Summary total (within 0.01 USD tolerance)
- No duplicate `(part_number, assembly)` pairs

#### `summary_report`
- Row count > 0
- All volume columns (proto, vl1..vl4) have non-null values for at least proto
- CBOM Ref No. column is populated

#### `price_control_report`
- Row count > 0
- Sum of CNP + TNP costs == Grand Total (within 1% tolerance)
- No `#REF!` strings in any text column

#### `ex_inv_vl_report` (excess inventory)
- `net_ordering_qty >= 0` for all rows
- `excess_qty = MAX(inventory_stock - required_qty, 0)` validated on a sample row

#### `revision_history_report`
- Delta columns are numeric (not null, not text)
- OLD unit price != 0 for at least 50% of rows (indicates real data, not empty)

#### `aclass_parts_report`
- A-class parts account for >= 70% of total extended cost (80/20 rule, allow 70% floor)
- `abc_classification` column only contains 'A' values

#### All reports
- `rfq_id` column matches the requested `rfq_id` for all rows
- No rows with NULL in primary key column

### 2. Wire validation into `report_generator.py`

Extend `generate_reports()` to call `validate_report_tab()` after each successful INSERT:

```python
# In report_generator.py, after the existing try/except per table:
validation = validate_report_tab(con, rfq_id, table)
if not validation["passed"]:
    issues.append({
        "table": table, 
        "error": f"Validation failed: {[c for c in validation['checks'] if not c['passed']]}"
    })
counts[f"{table}_validation"] = validation
```

### 3. Fix known report bugs

#### Fix `price_control_report` (reports/price_control.py)
- Find the GETPIVOTDATA equivalent SQL and replace with a direct aggregate
- The price_control breakdown is: group by price_control_type (CNP/TNP/Centum), sum ext_vol_cost
- Check `reports/price_control.py` for the current SQL and fix any division-by-zero or NULL refs

#### Fix `bom_matrix_report` cross-check (reports/bom_matrix.py)
- Add a reconciliation check: `SELECT SUM(grand_total) FROM bom_matrix_report WHERE rfq_id = ?`
  must equal `SELECT SUM(ext_vol_cost) FROM cbom WHERE rfq_id = ? AND is_assembly = FALSE`
- If mismatch > 1%: add a warning row at the bottom of bom_matrix_report with the delta

#### Fix `sum_and_count_report` (reports/sum_and_count.py)
- Ensure `is_sum_same` and `is_count_same` are boolean columns, not text 'TRUE'/'FALSE'
- The Scrub BOM quantity should equal CBOM quantity for each (assembly, cpn) pair

### 4. Add a `validate_all_reports(con, rfq_id)` entry point

```python
# In validator.py
def validate_all_reports(con, rfq_id):
    """Run all per-tab validators for one rfq_id. Returns a summary."""
    results = []
    for table in constants.REPORT_ORDER:
        results.append(validate_report_tab(con, rfq_id, table))
    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    return {
        "rfq_id": rfq_id,
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "details": results
    }
```

Expose this as an MCP tool endpoint in `mcp-tools/reporting/superset/mcp_server.py`:
Add `centum_reporting__validate_reports` tool that takes `rfq_id` and returns the validation summary.

## Files to Create/Modify

- `mcp-tools/reporting/superset/validator.py` (extend with per-tab checks)
- `mcp-tools/reporting/superset/report_generator.py` (wire in validation)
- `mcp-tools/reporting/superset/reports/price_control.py` (fix GETPIVOTDATA equivalent)
- `mcp-tools/reporting/superset/reports/bom_matrix.py` (fix cross-check)
- `mcp-tools/reporting/superset/reports/sum_and_count.py` (fix boolean columns)
- `mcp-tools/reporting/superset/mcp_server.py` (add validate tool)
- `tests/test_report_validators.py` (extend from SPEC-001 with business rule tests)

## Acceptance Criteria

1. `validate_all_reports(con, "TEST-RFQ-001")` runs with synthetic data and returns results for all 16 tables
2. `price_control_report` no longer raises an exception (even if data is incomplete)
3. `bom_matrix_report` cross-check delta is computable (not necessarily zero with synthetic data)
4. `centum_reporting__validate_reports` tool is registered in mcp_server.py
5. All changes committed to `feat/spec-002-report-validation` branch
6. `python -m pytest tests/ -v -k "report"` passes for at least 12/16 tables

## Domain Context

The 12 formula families from the Excel engine must be replicated in DuckDB SQL:
- F1: Currency conversion (lookup against currency rate table)
- F4: Shared-CPN guard: `WHERE is_assembly = FALSE AND part_num_line = assembly_parent_line`  
- F6: Excess inventory: `net_ordering_qty = MAX(required_qty - inventory_stock, 0)`

The known production failure (3.45× wrong total) was caused by:
- Wrong FX rate date
- MOQ rounding: `buy_qty = MAX(MOQ, CEIL(required_qty / pack_size) * pack_size)`
- MPN normalization: `UPPER(TRIM(REGEXP_REPLACE(mpn, '[^A-Z0-9]', '', 'g')))`

If you find these bugs in `queries.py`, fix them. The acceptance criteria for correctness:
`grand_total = sum(unit_price * buy_qty * fx_rate * (1 + scrap_pct))`
