"""Read-only local audit. Diagnostics remain blockers even if IFERROR hides them."""
import argparse
import collections
import datetime
import hashlib
import json
import time
from pathlib import Path

from excel_formula_engine import Workbook, is_error
from excel_formula_engine.workbook import CalculationBudgetExceeded


def audit(path, as_of, budget_seconds=120):
    start = time.monotonic()
    w = Workbook(str(path), today=as_of)
    outputs = collections.Counter()
    errors = []
    exceptions = []
    absent_caches = 0
    anchors = sum(len(s.formulas) for s in w.sheets.values())
    evaluated = 0
    complete = True
    for sl, sd in w.sheets.items():
        for r, c in sd.formulas:
            remaining = budget_seconds - (time.monotonic() - start)
            if remaining <= 0:
                complete = False
                break
            try:
                value = w.cell_value_now(sl, r, c, budget_seconds=remaining)
            except CalculationBudgetExceeded:
                complete = False
                break
            except Exception as exc:
                exceptions.append({'sheet': sd.title, 'row': r, 'col': c,
                                   'exception_type': type(exc).__name__})
                evaluated += 1
                continue
            evaluated += 1
            absent_caches += sd.cached.get((r, c)) is None
            outputs[str(value) if is_error(value) else type(value).__name__] += 1
            if is_error(value):
                errors.append({'sheet': sd.title, 'row': r, 'col': c, 'error': str(value)})
        if not complete:
            break
    notes = list(dict.fromkeys(w.notes))
    # Diagnostic gates deliberately ignore whether an outer IFERROR returned a value.
    blockers = []
    if not complete: blockers.append('evaluation_incomplete_or_budget_exhausted')
    if errors: blockers.append('error_valued_outputs')
    if exceptions: blockers.append('evaluation_exceptions')
    if notes: blockers.append('diagnostics_require_review_including_masked_failures')
    if absent_caches: blockers.append('missing_historical_oracle_values')
    return {
        'schema_version': 1,
        'source_name': Path(path).name,
        'source_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        'as_of': as_of.isoformat(),
        'anchors': anchors,
        'evaluated': evaluated,
        'complete': complete,
        'elapsed_seconds': round(time.monotonic()-start, 3),
        'outputs': dict(outputs),
        'absent_caches_among_evaluated': absent_caches,
        'error_outputs': errors,
        'exceptions': exceptions,
        'diagnostics': notes,
        'calculation_gate_blockers': blockers,
        'release_ready': False,
        'release_boundary': [
            'Local research prototype, not approved for production.',
            'Client expected values, financial policies and runtime bindings remain unapproved.',
            'Historical compatibility and a clean diagnostic scan are not Excel certification.',
            'Only evaluated paths are observed; edits can expose additional unsupported paths.'
        ],
        'mutation': 'none; workbook source is read only and no formula caches are written'
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workbook')
    p.add_argument('--as-of', required=True, type=datetime.date.fromisoformat,
                   help='Explicit date used for TODAY; YYYY-MM-DD')
    p.add_argument('--budget-seconds', type=float, default=120)
    args = p.parse_args()
    if args.budget_seconds <= 0: p.error('budget must be positive')
    print(json.dumps(audit(args.workbook, args.as_of, args.budget_seconds), indent=2))


if __name__ == '__main__':
    main()
