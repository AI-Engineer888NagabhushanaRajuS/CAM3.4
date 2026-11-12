"""Pre-flight for a SCRUB BOM workbook (SPEC-023): lists the cells that would turn into NaN / empty / an Excel error in the
output, BEFORE the run starts, with sheet, row, column and the fix.

It reads what `standardize_scrub_bom` reads (mcp-tools/scrub-intake/scrub_bom_processing.py): the SCRUB BOM sheet, and the
optional Settings (volumes) and Batch sheets, with the same rules:
  - header names are matched case/space/punctuation-insensitively (the real step asks an LLM for the rest; a header this
    file cannot place is reported, because the LLM could guess it wrong);
  - pandas treats a cell holding NaN / N/A / NULL / None ... as empty, and `_coerce_numeric` turns any non-number in the
    Settings/Batch sheets into NaN, so those cells are NaN in the output;
  - quantity is NOT coerced by the step: text in it breaks the hierarchy roll-up, an empty one has no quantity.
Errors stop the start (the output would be wrong or the step would fail); warnings are listed but do not stop it.
It cannot import the real step (that image has no ollama and this one has no mcp-tools): testing/test_input_check.py runs both
on the same data so the two cannot drift apart. Pure functions; nothing is written except by apply_edits to the path it is given.
"""
import datetime as dt
import re
from typing import Optional

SHEET_SCRUB_BOM, SHEET_SETTINGS, SHEET_BATCH = "SCRUB BOM", "Settings", "Batch"
MAX_ROWS = 50000          # rows read per sheet; a longer sheet is checked up to here and says so
MAX_ISSUES = 300          # issues returned; the counts stay exact
PER_CODE_CELLS = 40       # cells listed per kind of problem before "and N more" is left to the counts
MAX_EDITS = 500

# pandas.read_excel default na_values: a cell holding one of these is read as NaN
_PANDAS_NA = {"", "#n/a", "#n/a n/a", "#na", "-1.#ind", "-1.#qnan", "-nan", "1.#ind", "1.#qnan", "<na>", "n/a", "na",
              "null", "nan", "none", "-nan"}
_EXCEL_ERRORS = {"#ref!", "#n/a", "#div/0!", "#value!", "#name?", "#null!", "#num!", "#spill!", "#calc!"}

# canonical field -> normalised header names that mean it (mirrors SCRUB_BOM_TEMPLATE_HEADERS and the real file's headers)
_ALIASES = {
    "fg": {"fg", "finishedgood", "finishedgoods", "fgpartnumber"},
    "level": {"level", "bomlevel"},
    "assembly": {"assembly", "parentassembly", "parent"},
    "cpn": {"cpn", "ubrnumber", "ubr", "customerpartnumber", "customerpn", "internalpartnumber", "ipn", "partnumber", "partno", "pn"},
    "description": {"description", "descriptions", "partdescription", "desc"},
    "manufacturer": {"manufacturer", "manufacturers", "mfr", "mfg", "manufacturername", "mfrname"},
    "mpn": {"mpn", "mfrpartnumber", "mfgpartnumber", "manufacturerpartnumber", "manufacturerpn", "mfrpn", "mfgpn"},
    "commodity": {"commodity", "commodities"},
    "quantity": {"quantity", "quantities", "qty", "qtyper", "quantityper", "bomqty"},
    "unit_of_measure": {"unitofmeasure", "uom"},
    "part_status": {"partstatus", "partstatuses", "lifecycle"},
    "drawing_reference": {"drawingreference", "drawingref"},
    "designators": {"designators", "refdes", "referencedesignator", "referencedesignators"},
    "item_number": {"item", "itemno", "itemnumber", "item#"},
    "part_type": {"parttype"},
    "ltb_date": {"ltbdate", "lasttimebuydate"},
}
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d %b %Y", "%d-%b-%Y", "%Y/%m/%d")


def _norm(header) -> str:
    return re.sub(r"[^a-z0-9#]", "", str(header).lower()) if header is not None else ""


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _is_na(v) -> bool:
    return v is None or _text(v).lower() in _PANDAS_NA


def _as_number(v) -> Optional[float]:
    """The number a cell holds, or None. Booleans are not numbers; numeric text is (the fix for text quantities)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v and v not in (float("inf"), float("-inf")) else None
    s = _text(v).replace(",", "") if isinstance(v, str) else ""
    return float(s) if s and _NUMBER.match(s) else None


def _is_date(v) -> bool:
    if isinstance(v, (dt.datetime, dt.date)):
        return True
    s = _text(v)
    for f in _DATE_FORMATS:
        try:
            dt.datetime.strptime(s, f)
            return True
        except ValueError:
            pass
    return False


def _letter(i: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(i + 1)


class _Issues:
    """Collects issues with exact counts per code and a cap on what is listed."""

    def __init__(self):
        self.items, self.counts, self.errors, self.warnings, self.per_code = [], {}, 0, 0, {}

    def add(self, severity, code, sheet, row, col, header, value, message, fixable=True, suggestion=None):
        self.counts[code] = self.counts.get(code, 0) + 1
        if severity == "error":
            self.errors += 1
        else:
            self.warnings += 1
        shown = self.per_code.get(code, 0)
        self.per_code[code] = shown + 1
        if shown < PER_CODE_CELLS and len(self.items) < MAX_ISSUES:
            self.items.append({
                "severity": severity, "code": code, "sheet": sheet, "row": row, "col": col, "column": header,
                "value": None if value is None else str(value)[:120], "message": message, "fixable": fixable,
                **({"suggestion": suggestion} if suggestion else {}),
            })


def _open_pair(path: str):
    """(values workbook, formulas workbook), both streaming. Values come from the cached results Excel saved."""
    import io
    import openpyxl
    with open(path, "rb") as f:   # read from memory: a streaming reader on the path would keep the file locked on Windows
        data = f.read()
    return (openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True),
            openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False))


def _sheet(wb, wf, wanted: str):
    for name in wb.sheetnames:
        if name.strip().upper() == wanted.upper():
            return name
    return None


def _rows(wb, wf, name: str):
    """[(excel row number, values tuple, formulas tuple)] for the data rows; the header row is returned separately."""
    vals = wb[name].iter_rows(values_only=True)
    forms = wf[name].iter_rows(values_only=True)
    try:
        header = next(vals, ())
        next(forms, ())
        rows = []
        for i, (v, f) in enumerate(zip(vals, forms), start=2):
            if i - 1 > MAX_ROWS:
                break
            if all(c is None for c in v):   # a really empty row: not data
                continue
            rows.append((i, v, f))
        return header, rows
    finally:
        vals.close()    # an unfinished sheet reader keeps the file open, and on Windows that is a lock on the upload
        forms.close()


def _cell_problem(v, f):
    """'cell_error' / 'formula_unsaved' / None for a value that is an Excel error or a formula that was never calculated."""
    if isinstance(v, str) and v.strip().lower() in _EXCEL_ERRORS:
        return "cell_error"
    if v is None and isinstance(f, str) and f.startswith("="):
        return "formula_unsaved"
    return None


# Only for the columns the step cannot start without: a header that merely resembles them is accepted (the step's LLM maps it),
# so a file that used to run is not refused for an unusual spelling. Exact aliases are tried first.
_RESEMBLES = {
    "quantity": re.compile(r"quant|qty"),
    "mpn": re.compile(r"mpn|(mfr|mfg|manuf\w*).*(part|pn|number|no)|(part|pn).*(mfr|mfg|manuf)"),
    "cpn": re.compile(r"cpn|ubr|customerp|internalp|^part(no|num\w*)?$|^pn$"),
}


def _resolve(header) -> dict:
    """canonical field -> column index; the exact QUANTITY / COMMODITY ... headers win like the step's critical overrides."""
    found = {}
    for idx, h in enumerate(header):
        n = _norm(h)
        for field, names in _ALIASES.items():
            if n in names and field not in found:
                found[field] = idx
    taken = set(found.values())
    for field, pattern in _RESEMBLES.items():
        if field not in found:
            for idx, h in enumerate(header):
                if idx not in taken and h is not None and pattern.search(_norm(h)):
                    found[field] = idx
                    taken.add(idx)
                    break
    return found


def _check_scrub(wb, wf, name, issues: _Issues, out: dict):
    header, rows = _rows(wb, wf, name)
    cols = _resolve(header)
    out["rows"] = len(rows)
    shown_headers = ", ".join(str(h) for h in header if h is not None)[:160]
    if not rows:
        issues.add("error", "sheet_empty", name, None, None, None, None, f"The {name} sheet has no data rows, so there is nothing to price.", fixable=False)
        return set()
    for field, word, header_name in (("cpn", "CPN (the part's own number)", "CPN"), ("mpn", "MPN (manufacturer part number)", "MPN"),
                                     ("quantity", "Quantity", "Quantity"), ("fg", "FG (the finished good each part belongs to)", "FG")):
        if field not in cols:
            issues.add("error", "column_missing", name, 1, None, None, None,
                       f"No column for {word} (headers found: {shown_headers}). The step would stop or guess. Rename the header in Excel to '{header_name}'.",
                       fixable=False)
    fgs = set()

    def at(row_idx, field, v, f, severity_blank=None, code_blank=None, label=None):
        """Common checks for one cell; returns True when the cell is usable."""
        col = cols[field]
        letter, head = _letter(col), str(header[col])
        problem = _cell_problem(v, f)
        if problem == "cell_error":
            issues.add("error", problem, name, row_idx, letter, head, v, f"{head} holds the Excel error {v}; it would reach the output as an error or NaN.")
            return False
        if problem == "formula_unsaved":
            issues.add("error", problem, name, row_idx, letter, head, f, f"{head} is a formula with no saved result; open the file in Excel, let it calculate and save, or type the value.")
            return False
        if _is_na(v):
            if severity_blank:
                shown = "" if v is None else _text(v)
                how = "empty" if not shown else '"' + shown + '", which is read as empty'
                issues.add(severity_blank, code_blank, name, row_idx, letter, head, shown, f"{label or head} is {how}.")
            return False
        return True

    for i, v, f in rows:
        def g(field):
            c = cols.get(field)
            return (v[c] if c is not None and c < len(v) else None, f[c] if c is not None and c < len(f) else None)

        if "fg" in cols:
            fv, ff = g("fg")
            if at(i, "fg", fv, ff, "error", "fg_blank", "FG"):
                fgs.add(_text(fv))
        if "cpn" in cols:
            cv, cf = g("cpn")
            at(i, "cpn", cv, cf, "error", "cpn_blank", "CPN")
        if "mpn" in cols:
            mv, mf = g("mpn")
            at(i, "mpn", mv, mf, "warning", "mpn_blank", "MPN")
        if "quantity" in cols:
            qv, qf = g("quantity")
            if at(i, "quantity", qv, qf, "error", "quantity_blank", "Quantity"):
                n = _as_number(qv)
                head, letter = str(header[cols["quantity"]]), _letter(cols["quantity"])
                if n is None:
                    issues.add("error", "quantity_text", name, i, letter, head, qv, f"Quantity \"{_text(qv)}\" is not a number; the quantity roll-up would break on it.")
                elif isinstance(qv, str):
                    issues.add("error", "quantity_text", name, i, letter, head, qv, f"Quantity \"{_text(qv)}\" is stored as text, not as a number.", suggestion=str(int(n) if n == int(n) else n))
                elif n < 0:
                    issues.add("error", "quantity_negative", name, i, letter, head, qv, "Quantity is negative.")
                elif n == 0:
                    issues.add("warning", "quantity_zero", name, i, letter, head, qv, "Quantity is 0, so this line costs nothing.")
        for field, code, label in (("description", "description_blank", "Description"), ("manufacturer", "manufacturer_blank", "Manufacturer"),
                                   ("commodity", "commodity_blank", "Commodity"), ("part_status", "part_status_blank", "Part status")):
            if field in cols:
                xv, xf = g(field)
                at(i, field, xv, xf, "warning", code, label)
        if "ltb_date" in cols:
            lv, lf = g("ltb_date")
            if at(i, "ltb_date", lv, lf) and not _is_date(lv):
                issues.add("warning", "ltb_date_unreadable", name, i, _letter(cols["ltb_date"]), str(header[cols["ltb_date"]]), lv,
                           f"LTB date \"{_text(lv)}\" is not a date the step can read (DD-MM-YYYY is expected), so it would be empty.")
    return fgs


def _check_volumes(wb, wf, name, issues: _Issues, fgs: set, blank_severity: str, numeric_code: str, blank_code: str, what: str):
    header, rows = _rows(wb, wf, name)
    fg_idx = next((i for i, h in enumerate(header) if _text(h).upper() == "FG"), None)
    if fg_idx is None:
        issues.add("error", "column_missing", name, 1, None, None, None,
                   f"The {name} sheet has no 'FG' column (columns: {', '.join(str(h) for h in header if h is not None)[:120]}); the step stops with 'Could not find an FG column'.", fixable=False)
        return
    value_cols = [i for i, h in enumerate(header) if i != fg_idx and h is not None]
    if not value_cols:
        issues.add("error", "column_missing", name, 1, None, None, None, f"The {name} sheet has no {what} columns besides FG.", fixable=False)
        return
    have = set()
    for i, v, f in rows:
        fg = v[fg_idx] if fg_idx < len(v) else None
        if _is_na(fg):
            issues.add("error", "fg_blank", name, i, _letter(fg_idx), str(header[fg_idx]), "", "FG is empty on this row.")
            continue
        have.add(_text(fg))
        for c in value_cols:
            cv = v[c] if c < len(v) else None
            cf = f[c] if c < len(f) else None
            letter, head = _letter(c), str(header[c])
            problem = _cell_problem(cv, cf)
            if problem:
                issues.add("error", problem, name, i, letter, head, cv if problem == "cell_error" else cf,
                           f"{head} for {_text(fg)} is {'the Excel error ' + _text(cv) if problem == 'cell_error' else 'a formula with no saved result'}; the {what} would be NaN.")
            elif _is_na(cv):
                issues.add(blank_severity, blank_code, name, i, letter, head, "" if cv is None else _text(cv), f"{head} for {_text(fg)} is empty; the {what} would be NaN.")
            elif _as_number(cv) is None:
                issues.add("error", numeric_code, name, i, letter, head, cv, f"{head} for {_text(fg)} is \"{_text(cv)}\", not a number; the {what} would be NaN.")
            elif _as_number(cv) < 0:
                issues.add("error", numeric_code, name, i, letter, head, cv, f"{head} for {_text(fg)} is negative.")
    if name.upper() == SHEET_SETTINGS.upper():
        for fg in sorted(fgs - have):
            issues.add("error", "fg_not_in_settings", name, None, None, None, fg,
                       f"FG {fg} is in the SCRUB BOM but has no row in {name}, so it has no volume. Add a row for it in Excel.", fixable=False)


def check(path: str) -> dict:
    """The pre-flight report for a workbook path. Never raises."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    issues = _Issues()
    out = {"checked": False, "ok": False, "errors": 0, "warnings": 0, "rows": 0, "issues": [], "truncated": False, "counts": {}, "sheets": []}
    if ext not in ("xlsx", "xlsm"):
        out["message"] = f".{ext} files are not pre-checked; save the workbook as .xlsx for the check."
        out["ok"] = True
        return out
    wb = wf = None
    try:
        wb, wf = _open_pair(path)
        out["sheets"] = list(wb.sheetnames)
        scrub = _sheet(wb, wf, SHEET_SCRUB_BOM)
        if scrub is None:
            issues.add("error", "sheet_missing", None, None, None, None, None,
                       f"No sheet named '{SHEET_SCRUB_BOM}' (sheets: {', '.join(wb.sheetnames)}). The first pipeline step reads only that sheet and would reject the file as invalid input.", fixable=False)
        else:
            fgs = _check_scrub(wb, wf, scrub, issues, out)
            settings = _sheet(wb, wf, SHEET_SETTINGS)
            batch = _sheet(wb, wf, SHEET_BATCH)
            if settings:
                _check_volumes(wb, wf, settings, issues, fgs, "error", "volume_not_number", "volume_blank", "volume")
            else:
                issues.add("warning", "settings_missing", None, None, None, None, None, "There is no Settings sheet, so the run uses one implicit volume.", fixable=False)
            if batch:
                _check_volumes(wb, wf, batch, issues, set(), "warning", "batch_not_number", "batch_blank", "batch quantity")
        out["checked"] = True
    except Exception as e:  # an unreadable workbook is itself the finding
        issues.add("error", "unreadable", None, None, None, None, None, f"The workbook could not be read ({type(e).__name__}); it may be damaged or password-protected.", fixable=False)
    finally:
        for w in (wb, wf):
            if w is not None:
                w.close()
    out.update(ok=issues.errors == 0, errors=issues.errors, warnings=issues.warnings, issues=issues.items, counts=issues.counts,
               truncated=sum(issues.counts.values()) > len(issues.items))
    return out


def _part_ids(path: str, sheet_wanted, header_ok, columns) -> set:
    """Upper-cased, trimmed values of the wanted columns of the first sheet (or the named one) whose header row passes `header_ok`."""
    wb, wf = _open_pair(path)
    try:
        names = [n for n in wb.sheetnames if sheet_wanted is None or n.strip().upper() == sheet_wanted.upper()]
        for name in names:
            vals = wb[name].iter_rows(values_only=True)
            try:
                for i, row in enumerate(vals):
                    if i > 2000:
                        break
                    header = [_norm(c) for c in row]
                    if header_ok(header):
                        idx = [j for j, h in enumerate(header) if h in columns]
                        return {str(r[j]).strip().upper() for r in vals for j in idx if j < len(r) and r[j] not in (None, "")}
            finally:
                vals.close()
        return set()
    finally:
        for w in (wb, wf):
            w.close()


def quotewin_match(bom_path: str, quotewin_path: str) -> dict:
    """How many of the BOM's part numbers (CPN) the QuoteWin file knows (by its Part Number or Mfg Part Number). Prices and awards come from
    QuoteWin by part number, so a file with none of the BOM's parts prices nothing and every cost in the report is 0 (RFQ-000024).
    Never raises: when either file cannot be read the answer is `known: False` and the caller lets the upload through."""
    try:
        bom = _part_ids(bom_path, SHEET_SCRUB_BOM, lambda h: any(x in _ALIASES["cpn"] for x in h), _ALIASES["cpn"])
        signature = lambda h: {"partnumber", "mfgpartnumber", "commodity"} <= set(h)  # noqa: E731
        qw = _part_ids(quotewin_path, None, signature, {"partnumber", "mfgpartnumber"})
        listed = _part_ids(quotewin_path, None, signature, {"partnumber"})   # what the message counts: the file's part numbers, not its MPNs too
    except Exception:
        return {"known": False}
    if not bom or not qw:
        return {"known": False}
    return {"known": True, "bom_parts": len(bom), "quotewin_parts": len(listed), "shared": len(bom & qw)}


def summary(report: dict) -> dict:
    """The few fields a file list needs."""
    return {k: report.get(k) for k in ("checked", "ok", "errors", "warnings")}


# ---- fixing: the user's corrections written into a copy -------------------------------------------------------------------

_COL = re.compile(r"^[A-Z]{1,3}$")


def _typed(value):
    """A typed edit value: numbers become numbers, empty becomes empty, anything starting like a formula is refused."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("a value must be text or a number")
    if isinstance(value, (int, float)):
        return value
    s = value.strip()
    if s == "":
        return None
    n = _as_number(s)
    if n is not None:
        return int(n) if n == int(n) and "." not in s and "e" not in s.lower() else n
    if s[0] in "=+-@\t\r":
        raise ValueError(f"\"{s[:20]}\" starts like a formula; type the value, not a formula")
    if len(s) > 500:
        raise ValueError("a value is limited to 500 characters")
    return s


def apply_edits(src: str, dst: str, edits: list) -> int:
    """Writes `edits` ([{sheet, row, col, value}]) into a copy of `src` at `dst`; returns how many cells changed. Raises ValueError
    with a plain sentence for anything it will not do (unknown sheet, bad cell, formula-looking text, too many edits).
    Formulas become their last calculated values in the copy (see below); the original file is never changed."""
    import openpyxl
    if not isinstance(edits, list) or not edits:
        raise ValueError("no corrections were sent")
    if len(edits) > MAX_EDITS:
        raise ValueError(f"at most {MAX_EDITS} cells can be corrected at once")
    # data_only: openpyxl cannot write a formula together with its saved result, and a formula saved without one reads as NaN in
    # the pipeline (pandas reads saved results only). So the corrected copy keeps each formula's last calculated VALUE, not the formula.
    wb = openpyxl.load_workbook(src, data_only=True)
    try:
        for e in edits:
            sheet, row, col = e.get("sheet"), e.get("row"), e.get("col")
            if sheet not in wb.sheetnames:
                raise ValueError(f"there is no sheet named {sheet!r}")
            if not isinstance(row, int) or isinstance(row, bool) or not 1 <= row <= 1048576 or not isinstance(col, str) or not _COL.match(col):
                raise ValueError(f"{sheet}!{col}{row} is not a cell")
            wb[sheet][f"{col}{row}"].value = _typed(e.get("value"))
        wb.save(dst)
    finally:
        wb.close()
    return len(edits)
