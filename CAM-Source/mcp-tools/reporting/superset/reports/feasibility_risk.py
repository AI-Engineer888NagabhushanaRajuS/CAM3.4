"""Feasibility & Risk (SKILL_03, macro_category 5): one verdict per BOM line, with the reasons, from the SCRUB BOM and the QuoteWin quotes.

The manifest asks for a Can-Build / Cannot-Build verdict for every BOM line with documented risk reasons. Every rule is a SETTING, saved by an admin in
Settings > Feasibility (Postgres logic_db.feasibility_settings) and read fresh on every run, so the rules change without a code change. Until someone
saves them the documented defaults below apply and the step says so. What is evaluated:

  Cannot build   Part Status in the cannot-build list (EOL, Discontinued), or no quote with a price at all (uncosted), or a machine rule that says so.
  Risk, High     Cannot build, or a last-time-buy date, or a price but no lead time quoted, or a machine rule that says so.
  Risk, Medium   Part Status in the medium list (NRFND); best lead time over the limit (default 20 weeks); NCNR; the quote's price validity has passed;
                 or a machine rule that says so.
  Risk, Low      none of the above.

A machine rule ("constraint") is the plant's own knowledge, entered in Settings: a SCRUB BOM column, an operator and a value (for example description
contains 0201 -> Cannot build), with the effect it has. The BOM carries no machine data itself, so a rule can only test what the BOM says.

Pure functions over two frames (no database); the exporter and the pipeline tool both call them, so the tab and the step's summary cannot differ.
"""
import datetime

LEAD_TIME_LIMIT_WEEKS = 20
DEFAULT_SETTINGS = {
    "lead_time_limit_weeks": LEAD_TIME_LIMIT_WEEKS,
    "cannot_build_statuses": ["EOL", "DISCONTINUED"],
    "medium_statuses": ["NRFND"],
    "no_price_cannot_build": True,
    "no_lead_time_high": True,
    "ltb_high": True,
    "ncnr_medium": True,
    "expired_validity_medium": True,
    "constraints": [],
}
CONSTRAINT_COLUMNS = ("fg", "assembly", "cpn", "description", "manufacturer", "mpn", "commodity", "quantity", "unit_of_measure", "part_status",
                      "ce_remarks", "drawing_reference", "designators", "part_type", "ltb_date", "inventory_stock")
OPERATORS = ("contains", "not_contains", "equals", "not_equals", "gt", "gte", "lt", "lte", "empty", "not_empty")
EFFECTS = ("cannot_build", "high", "medium")
HEADERS = ["FG", "Assembly", "Part Number", "MPN", "Description", "Commodity", "Qty per", "Part Status", "Best lead time (weeks)", "Verdict", "Risk", "Reasons"]


def _text(v):
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()


def _num(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _status(v):
    return _text(v).upper().replace("-", " ")


def _is_true(v):
    return _text(v).upper() in ("Y", "YES", "TRUE", "1", "NCNR")


def normalize(raw):
    """Saved settings (or None) -> a complete, checked settings dict. Raises ValueError on a rule that cannot work (an unknown column, operator or effect)."""
    out = {**DEFAULT_SETTINGS, **(raw or {})}
    limit = float(out["lead_time_limit_weeks"])
    if limit <= 0:
        raise ValueError("lead_time_limit_weeks must be above 0")
    out["lead_time_limit_weeks"] = int(limit) if limit.is_integer() else limit
    for key in ("cannot_build_statuses", "medium_statuses"):
        out[key] = [_status(x) for x in out[key] if _text(x)]
    for key in ("no_price_cannot_build", "no_lead_time_high", "ltb_high", "ncnr_medium", "expired_validity_medium"):
        out[key] = bool(out[key])
    rules = []
    for c in out["constraints"] or []:
        name, col, op, eff = _text(c.get("name")), _text(c.get("column")), _text(c.get("operator")), _text(c.get("effect"))
        if not name or col not in CONSTRAINT_COLUMNS or op not in OPERATORS or eff not in EFFECTS:
            raise ValueError(f"machine rule {name or c!r}: needs a name, a known column, operator and effect")
        if op not in ("empty", "not_empty") and not _text(c.get("value")):
            raise ValueError(f"machine rule {name!r}: needs a value")
        rules.append({"name": name, "column": col, "operator": op, "value": _text(c.get("value")), "effect": eff})
    out["constraints"] = rules
    return out


def _hit(cell, op, value):
    text, want = _text(cell).lower(), value.lower()
    if op == "empty":
        return text == ""
    if op == "not_empty":
        return text != ""
    if op == "contains":
        return want in text
    if op == "not_contains":
        return want not in text
    if op == "equals":
        return text == want
    if op == "not_equals":
        return text != want
    a, b = _num(cell), _num(value)
    if a is None or b is None:
        return False
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def _rule_text(c):
    value = "" if c["operator"] in ("empty", "not_empty") else " " + c["value"]
    return f"{c['name']} ({c['column']} {c['operator'].replace('_', ' ')}{value})"


def feasibility_rows(scrub_df, quote_df, as_of=None, settings=None):
    """[{fg, assembly, cpn, mpn, description, commodity, quantity, part_status, lead_time, verdict, risk, reasons}], one per leaf line of the SCRUB BOM."""
    st = normalize(settings)
    limit = st["lead_time_limit_weeks"]
    as_of = as_of or datetime.date.today()
    by_part = {}
    for q in quote_df.to_dict("records") if quote_df is not None and len(quote_df) else []:
        for key in (_text(q.get("part_number")).upper(), _text(q.get("mfg_part_number")).upper()):
            if key:
                by_part.setdefault(key, []).append(q)
    scrub = scrub_df.to_dict("records") if scrub_df is not None and len(scrub_df) else []
    assemblies = {_text(r.get("assembly")).upper() for r in scrub if _text(r.get("assembly"))}
    out = []
    for r in scrub:
        cpn = _text(r.get("cpn"))
        if not cpn or cpn.upper() in assemblies:          # a sub-assembly is built from its own parts, which have their own lines
            continue
        quotes = by_part.get(cpn.upper(), []) + by_part.get(_text(r.get("mpn")).upper(), [])
        priced = [q for q in quotes if (_num(q.get("cost_1_conv")) or 0) > 0 or (_num(q.get("cost_2_conv")) or 0) > 0]
        leads = [x for x in (_num(q.get("lead_time")) for q in priced) if x is not None and x > 0]
        best_lead = min(leads) if leads else None
        statuses = {_status(r.get("part_status"))} | {_status(q.get("part_status")) for q in quotes}
        cannot, risks_high, risks_medium = [], [], []
        bad = statuses & set(st["cannot_build_statuses"])
        if bad:
            cannot.append(f"Part Status {'/'.join(sorted(bad))}")
        if not priced and st["no_price_cannot_build"]:
            cannot.append("no quote with a price (uncosted)")
        soft = statuses & set(st["medium_statuses"])
        if soft:
            risks_medium.append(f"Part Status {'/'.join(sorted(soft))}")
        if priced and best_lead is None and st["no_lead_time_high"]:
            risks_high.append("no lead time quoted")
        if best_lead is not None and best_lead > limit:
            risks_medium.append(f"lead time {best_lead:g} weeks is over {limit:g}")
        ltb = r.get("ltb_date")
        if st["ltb_high"] and _text(ltb) and _text(ltb).lower() not in ("nat", "none"):
            risks_high.append(f"last-time-buy date {_text(ltb)[:10]}")
        if st["ncnr_medium"] and any(_is_true(q.get("ncnr")) for q in priced):
            risks_medium.append("NCNR (non-cancellable, non-returnable)")
        validity = [d for d in (_exp(q) for q in priced) if d]
        if st["expired_validity_medium"] and validity and len(validity) == len(priced) and max(validity) < as_of:
            risks_medium.append(f"every quote's price validity has passed (latest {max(validity)})")
        for c in st["constraints"]:
            if _hit(r.get(c["column"]), c["operator"], c["value"]):
                {"cannot_build": cannot, "high": risks_high, "medium": risks_medium}[c["effect"]].append(f"machine rule: {_rule_text(c)}")
        verdict = "Cannot build" if cannot else "Can build"
        risk = "High" if (cannot or risks_high) else "Medium" if risks_medium else "Low"
        out.append({
            "fg": _text(r.get("fg")), "assembly": _text(r.get("assembly")), "cpn": cpn, "mpn": _text(r.get("mpn")), "description": _text(r.get("description")),
            "commodity": _text(r.get("commodity")), "quantity": _num(r.get("quantity")), "part_status": _text(r.get("part_status")),
            "lead_time": best_lead, "verdict": verdict, "risk": risk, "reasons": "; ".join(cannot + risks_high + risks_medium),
        })
    return out


def _exp(q):
    e = q.get("exp_date")
    if e is None or e != e:                            # None, NaN and pandas NaT (the only value not equal to itself)
        return None
    if hasattr(e, "date"):
        try:
            return e.date()
        except Exception:
            return None
    return e if isinstance(e, datetime.date) else None


def summary(rows, settings=None):
    st = normalize(settings)
    return {
        "lines": len(rows), "can_build": sum(1 for r in rows if r["verdict"] == "Can build"), "cannot_build": sum(1 for r in rows if r["verdict"] == "Cannot build"),
        "high": sum(1 for r in rows if r["risk"] == "High"), "medium": sum(1 for r in rows if r["risk"] == "Medium"), "low": sum(1 for r in rows if r["risk"] == "Low"),
        "lead_time_limit_weeks": st["lead_time_limit_weeks"], "machine_rules": len(st["constraints"]),
    }


def rule_set_text(settings=None):
    st = normalize(settings)
    cannot = " or ".join(x for x in (f"Part Status {'/'.join(st['cannot_build_statuses'])}" if st["cannot_build_statuses"] else None,
                                     "no quote with a price" if st["no_price_cannot_build"] else None) if x) or "nothing but a machine rule"
    high = ", ".join(x for x in ("cannot build", "last-time-buy date" if st["ltb_high"] else None, "no lead time quoted" if st["no_lead_time_high"] else None) if x)
    medium = ", ".join(x for x in (f"Part Status {'/'.join(st['medium_statuses'])}" if st["medium_statuses"] else None, f"best lead time over {st['lead_time_limit_weeks']:g} weeks",
                                   "NCNR" if st["ncnr_medium"] else None, "price validity passed" if st["expired_validity_medium"] else None) if x)
    return f"Rule set (Settings > Feasibility): Cannot build = {cannot}. High = {high}. Medium = {medium}."


def machine_note(settings=None):
    rules = normalize(settings)["constraints"]
    if not rules:
        return "Machine rules: none are saved in Settings > Feasibility, so no machine constraint was checked."
    return "Machine rules checked (Settings > Feasibility): " + "; ".join(f"{_rule_text(c)} -> {c['effect'].replace('_', ' ')}" for c in rules) + "."


def build_feasibility_sheet(wb, rows, settings=None, title="Feasibility & Risk"):
    """Plain values, no formulas: the verdicts are decided here, not by Excel, so every viewer shows the same."""
    from openpyxl.styles import Alignment, Font, PatternFill
    ws = wb.create_sheet(title=title)
    s = summary(rows, settings)
    ws.append([f"Feasibility & Risk: {s['lines']} lines, {s['can_build']} can build, {s['cannot_build']} cannot build, risk High {s['high']} / Medium {s['medium']} / Low {s['low']}"])
    ws.append([rule_set_text(settings)])
    ws.append([machine_note(settings)])
    ws.append([])
    ws.append(HEADERS)
    head = ws.max_row
    for c in ws[head]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9E1F2")
    colour = {"High": "F8CBAD", "Medium": "FFE699", "Low": "C6E0B4"}
    for r in rows:
        ws.append([r["fg"], r["assembly"], r["cpn"], r["mpn"], r["description"], r["commodity"], r["quantity"], r["part_status"], r["lead_time"], r["verdict"], r["risk"], r["reasons"]])
        ws.cell(row=ws.max_row, column=11).fill = PatternFill("solid", fgColor=colour[r["risk"]])
        ws.cell(row=ws.max_row, column=12).alignment = Alignment(wrap_text=True, vertical="top")
    for letter, width in zip("ABCDEFGHIJKL", (14, 14, 22, 22, 36, 14, 8, 14, 12, 14, 8, 70)):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = ws.cell(row=head + 1, column=1)
    return ws
