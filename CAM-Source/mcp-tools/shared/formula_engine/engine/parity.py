"""Value-parity harness: engine-computed vs Excel cached values, per cell.

Categories (mutually exclusive):
  match_exact / match_tol  - engine equals Excel cache (tolerance for floats)
  mismatch                 - both have values, differ
  engine_error             - engine produced an error value (Excel had a value)
  excel_error              - Excel cache is an error; engine value compared by type
  no_cache                 - cell has formula but no cached value (tool-written)
  parse_error              - engine could not parse the formula
"""
import sys, datetime, collections, json
sys.path.insert(0, '.')
from excel_formula_engine import Workbook
from excel_formula_engine.values import is_error, is_blank, ErrorValue

def close(a, b, tol=1e-9):
    try:
        if b == 0: return abs(a) < 1e-9
        return abs(a - b) / max(abs(a), abs(b)) < tol
    except TypeError:
        return False

def run(path, today=None, limit_mismatch_examples=25, per_sheet_sample=None):
    wb = Workbook(path, today=today or datetime.date.today())
    cat = collections.Counter()
    by_sheet = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    outputs = collections.Counter()
    for sheet_l, sd in wb.sheets.items():
        items = list(sd.formulas.items())
        if per_sheet_sample and len(items) > per_sheet_sample:
            items = [items[round(i*(len(items)-1)/(per_sheet_sample-1))] for i in range(per_sheet_sample)]
        for (r, c), f in items:
            cached = sd.cached.get((r, c))
            exception = None
            try:
                got = wb.cell_value_now(sd.title, r, c)
            except Exception as e:
                exception = type(e).__name__
                got = f"evaluation failed: {exception}: {str(e)[:120]}"
            outputs[str(got) if is_error(got) else type(got).__name__] += 1
            if exception:
                k = "engine_exception:" + exception
            elif cached is None:
                k = "no_cache"
            elif is_error(cached):
                k = "excel_error_match" if is_error(got) and str(got) == str(cached) else \
                    ("excel_error_engine_value" if not is_error(got) else "excel_error_diff")
            elif is_error(got):
                k = "engine_error"
            elif is_blank(cached) and is_blank(got):
                k = "match_exact"
            elif isinstance(cached, (int, float)) and not isinstance(cached, bool) and isinstance(got, (int, float)) and not isinstance(got, bool):
                k = "match_exact" if cached == got else ("match_tol" if close(got, cached) else "mismatch")
            else:
                k = "match_exact" if str(got) == str(cached) else "mismatch"
            cat[k] += 1
            by_sheet[sd.title][k] += 1
            if (k in ("mismatch", "engine_error", "excel_error_engine_value") or k.startswith("engine_exception:")) and len(examples[k]) < limit_mismatch_examples:
                examples[k].append({"sheet": sd.title, "cell": f"R{r}C{c}", "formula": f[:160],
                                    "excel": str(cached)[:60], "engine": str(got)[:60]})
    wb.output_categories = dict(outputs)
    wb._parity_source = path
    return wb, cat, by_sheet, examples

if __name__ == "__main__":
    path = sys.argv[1]
    today = datetime.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    sample = int(sys.argv[3]) if len(sys.argv) > 3 else None
    wb, cat, by_sheet, examples = run(path, today, per_sheet_sample=sample)
    total = sum(cat.values())
    print(f"workbook: {path}")
    print(f"formula cells evaluated: {total}; per_sheet_sample={sample}")
    for k, v in cat.most_common():
        print(f"  {k:28s} {v:8d}  {v/total*100:6.2f}%")
    print(f"engine stats: {wb.stats}")
    print(f"computed outputs (including no-cache cells): {wb.output_categories}")
    print(f"cycle diagnostics: {wb.cycle_diagnostics[:8]}")
    print("by sheet:")
    for s, cc in by_sheet.items():
        print(f"  {s}: {dict(cc)}")
    for k, exs in examples.items():
        print(f"--- {k} examples ---")
        for e in exs:
            print(f"  {e['sheet']}!{e['cell']} excel={e['excel']!r} engine={e['engine']!r}\n      {e['formula']}")
