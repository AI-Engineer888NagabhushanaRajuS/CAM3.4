"""The numbers of one finished RFQ for the Reports & Analytics screen, read from its newest exported workbook.

The workbook is the single source of truth: the screen can never show a figure the delivered report does not hold (and after the
engine check, mcp-tools/shared/formula_verify.py, those stored values are the engine-verified ones). The tabs and their layout are the
fixed ones the exporter writes (mcp-tools/reporting/superset/reports/*). A block that cannot be read is None, never guessed.
"""
import os

import openpyxl


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _rows(wb, name, max_col):
    return list(wb[name].iter_rows(max_col=max_col, values_only=True)) if name in wb.sheetnames else []


def _summary(wb):
    rows = _rows(wb, "Summary", 9)
    head = next((i for i, r in enumerate(rows) if r[2] == "Assembly"), None)
    if head is None:
        return None
    labels = [(i, str(rows[head][i]).replace("CBOM Cost ", "")) for i in range(3, 9) if str(rows[head][i] or "").startswith("CBOM Cost")]
    fgs, totals = [], {}
    for r in rows[head + 1:]:
        if r[2]:
            if str(r[2]) in ("Ext Vol Conv Price", "MOQ Cost", "In %") or str(r[2]).startswith(("Ext Vol", "MOQ", "In %")):
                break
            fgs.append({"assembly": str(r[2]), **{lab: _num(r[i]) for i, lab in labels}})
        elif any(_num(r[i]) is not None for i, _ in labels):
            totals = {lab: _num(r[i]) for i, lab in labels}
    extra = {}
    for r in rows[head + 1:]:
        key = str(r[2] or "")
        if key.startswith("Ext Vol"):
            extra["ext_vol_conv_price"] = {lab: _num(r[i]) for i, lab in labels}
        elif key.startswith("MOQ"):
            extra["moq_cost"] = {lab: _num(r[i]) for i, lab in labels}
        elif key.startswith("In %"):
            extra["moq_pct"] = {lab: _num(r[i]) for i, lab in labels}
    return {"volumes": [lab for _, lab in labels], "fgs": fgs, "totals": totals, **extra}


def _price_control(wb):
    rows = _rows(wb, "Price Control", 4)
    out = [{"label": str(r[0]), "ext_price": _num(r[1]), "ext_vol_cost": _num(r[2]), "pct": _num(r[3])}
           for r in rows[1:] if r[0] and str(r[0]) != "Grand Total"]
    return out or None


def _lead_time(wb):
    rows = _rows(wb, "Lead Time Consolidated", 3)
    out = [{"weeks": None if r[0] in (None, "") else str(r[0]), "count": _num(r[1]), "pct": _num(r[2])}
           for r in rows[1:] if r[1] is not None and str(r[0]) != "Grand Total"]
    return out or None


def _cashflow(wb):
    blocks, current = [], None
    for r in _rows(wb, "Batchwise Cashflow", 5):
        first = str(r[0] or "")
        if first.startswith("Payment term"):
            current = []
            blocks.append(current)
        elif current is not None and first and first not in ("Supplier Type", "Grand Total"):
            current.append({"type": first, "buy": _num(r[1]), "final_buy": _num(r[2])})
    return [b for b in blocks if b] or None


def _excess(wb):
    out = {}
    for name in wb.sheetnames:
        if name.startswith("Ex Inv VL-"):
            rows = list(wb[name].iter_rows(min_row=2, max_row=2, max_col=1, values_only=True))
            out["VL-" + name.rsplit("-", 1)[1]] = _num(rows[0][0]) if rows else None
    return out or None


def _commodity_excess(wb):
    """Net Excess Cost #n summed per commodity, for each volume's Ex Inv tab: the same column that the tab's own Excess Cost total adds up
    (its total cell = SUM of that column). A line with no part number ends the table; a line with no commodity counts as 'Unassigned'."""
    out = {}
    for name in wb.sheetnames:
        if not name.startswith("Ex Inv VL-"):
            continue
        rows = list(wb[name].iter_rows(min_row=4, max_col=30, values_only=True))
        if not rows:
            continue
        head = list(rows[0])
        number = name.rsplit("-", 1)[1]
        value_name = f"Net Excess Cost #{number}"
        if "Commodity" not in head or value_name not in head:
            continue
        c_col, v_col = head.index("Commodity"), head.index(value_name)
        totals = {}
        for r in rows[1:]:
            if r[0] in (None, ""):
                break
            value = _num(r[v_col])
            if value is None:
                continue
            key = str(r[c_col]).strip() if r[c_col] not in (None, "") else "Unassigned"
            totals[key] = totals.get(key, 0.0) + value
        out["VL-" + name.rsplit("-", 1)[1]] = totals
    return out or None


SECTIONS = {"1": "uncosted", "2": "mpn_mismatch", "3": "not_in_bom_subset", "4": "nrfnd", "5": "eol"}


def _exceptions(wb):
    """Rows in each numbered section of Missing Notes (1 Uncosted Parts ... 5 EOL). A section is a title row, a header row, then data rows up to a blank row."""
    rows = _rows(wb, "Missing Notes", 2)
    out, i = {}, 0
    while i < len(rows):
        title = str(rows[i][0] or "")
        if title[:3] in tuple(f"{n}. " for n in SECTIONS):
            n, j = 0, i + 2                          # the line after the title is the header row
            while j < len(rows) and rows[j][0] not in (None, "") and str(rows[j][0])[:3] not in tuple(f"{k}. " for k in SECTIONS):
                n += 1
                j += 1
            out[SECTIONS[title[0]]] = n
            i = j
        else:
            i += 1
    return out or None


def _uncosted(wb):
    ex = _exceptions(wb)
    return None if ex is None else ex.get("uncosted")


def _currency(wb):
    """The quote currency of the 7.0 CBOM tabs ("Quote Currency" | "USD" in their header block)."""
    for name in wb.sheetnames:
        if name.startswith("7.0 CBOM VL-"):
            for r in wb[name].iter_rows(min_row=1, max_row=3, max_col=20, values_only=True):
                for k, cell in enumerate(r):
                    if str(cell or "").strip() == "Quote Currency" and k + 1 < len(r) and r[k + 1]:
                        return str(r[k + 1])
    return None


def _cashflow_totals(wb):
    """Grand Total row of each Batchwise Cashflow block: [{"buy": Sum of Buy value, "final_buy": Sum of Final buy value}] per volume."""
    out, in_block = [], False
    for r in _rows(wb, "Batchwise Cashflow", 5):
        first = str(r[0] or "")
        if first.startswith("Payment term"):
            in_block = True
        elif in_block and first == "Grand Total":
            out.append({"buy": _num(r[1]), "final_buy": _num(r[2])})
            in_block = False
    return out or None


def _cbom(wb):
    if "CBOM" not in wb.sheetnames:
        return None
    rows = _rows(wb, "CBOM", 80)
    if not rows:
        return None
    head = list(rows[0])
    price = head.index("final_price_conv") if "final_price_conv" in head else None
    data = rows[1:]
    return {"rows": len(data), "priced": sum(1 for r in data if price is not None and _num(r[price]) not in (None, 0.0))}


def _manifest(wb):
    out = {}
    for r in _rows(wb, "Manifest", 2):
        if r[0] == "Error cells (all tabs)":
            out["error_cells"] = _num(r[1])
        elif r[0] == "Go / no-go":
            out["go_no_go"] = r[1] if isinstance(r[1], str) else None
    return out or None


def analytics(path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        out = {"workbook": os.path.basename(path)}
        for key, fn in (("summary", _summary), ("price_control", _price_control), ("lead_time", _lead_time), ("cashflow", _cashflow),
                        ("cashflow_totals", _cashflow_totals), ("excess_cost", _excess), ("commodity_excess", _commodity_excess), ("bom_matrix", _bom_matrix), ("uncosted_parts", _uncosted),
                        ("exceptions", _exceptions), ("currency", _currency), ("cbom", _cbom), ("manifest", _manifest)):
            try:
                out[key] = fn(wb)
            except Exception:
                out[key] = None
        return out
    finally:
        wb.close()


# ---- all RFQs: the portfolio screen (what 3.3's "Executive Sourcing Overview" showed, with every figure defined) ---------------------------

LEAD_BUCKETS = (("up to 8 weeks", 0, 8), ("9 to 16 weeks", 9, 16), ("17 to 26 weeks", 17, 26), ("over 26 weeks", 27, 10 ** 6))
DEFINITIONS = {
    "total_rfqs": "RFQs that have an exported report workbook (the newest export of each).",
    "costing_pct": "Priced CBOM rows (final price present) divided by all CBOM rows, over all RFQs.",
    "final_buy": "Sum of Final buy value in each RFQ's Batchwise Cashflow Grand Total, for the RFQ's last volume, in the quote currency.",
    "buy_variance": "(Sum of Final buy value minus Sum of Buy value) divided by Sum of Buy value, same tab and volume: what MOQ, packs and scrap add to the plain need.",
    "excess_cost": "The Excess Cost figure at the top of each RFQ's Ex Inv tab for its last volume.",
    "critical_exceptions": "Rows in Missing Notes sections 1 to 5: uncosted parts, MPN mismatch, MPN not in the BOM subset, NRFND, EOL.",
    "lead_time": "Parts per lead-time bucket from each RFQ's Lead Time Consolidated tab; parts with no lead time are counted apart.",
    "commodity_excess": "Net Excess Cost summed per commodity over each RFQ's Ex Inv tab for its last volume: the same column whose total is that tab's Excess Cost. Commodities at zero are left out of the chart.",
    "volume_rule": "Every figure uses the RFQ's last volume (VL-n); the screen says which.",
}
_CACHE = {}


def _read(path):
    key = (path, os.path.getmtime(path))
    if key not in _CACHE:
        _CACHE.clear() if len(_CACHE) > 300 else None
        _CACHE[key] = analytics(path)
    return _CACHE[key]


def _bucket_counts(lead_time):
    out = {name: 0 for name, _, _ in LEAD_BUCKETS}
    out["no lead time"] = 0
    for b in lead_time or []:
        n = b.get("count") or 0
        try:
            weeks = int(float(b["weeks"])) if b.get("weeks") not in (None, "") else None
        except (TypeError, ValueError):
            weeks = None
        if weeks is None:
            out["no lead time"] += n
            continue
        for name, lo, hi in LEAD_BUCKETS:
            if lo <= weeks <= hi:
                out[name] += n
                break
    return out


def _portfolio_row(item, a):
    s = a.get("summary") or {}
    last = (s.get("volumes") or [None])[-1]
    cf = (a.get("cashflow_totals") or [None])[-1] or {}
    buy, final = cf.get("buy"), cf.get("final_buy")
    cbom = a.get("cbom") or {}
    ex = a.get("exceptions") or {}
    return {
        "rfq_id": item["rfq_id"], "customer": item.get("customer"), "project": item.get("project"), "workbook": a["workbook"], "generated": item.get("generated"),
        "volume": last, "currency": a.get("currency"),
        "cost_per_set": (s.get("totals") or {}).get(last), "ext_vol_cost": (s.get("ext_vol_conv_price") or {}).get(last),
        "buy": buy, "final_buy": final, "buy_variance": ((final - buy) / buy) if buy and final is not None else None,
        "excess_cost": (a.get("excess_cost") or {}).get(last),
        "commodity_excess": (a.get("commodity_excess") or {}).get(last),
        "rows": cbom.get("rows"), "priced": cbom.get("priced"), "critical": sum(ex.values()) if ex else None, "exceptions": ex or None,
        "lead_time": _bucket_counts(a.get("lead_time")), "go_no_go": (a.get("manifest") or {}).get("go_no_go"),
        # An older export, made before the engine step stored the formulas' values: its cash-flow cells read as empty, not as zero.
        # (Not the Go / no-go cell: exports before 5 Nov have no such row in their Manifest tab, so no stored value could ever fill it.)
        "needs_values": bool(cbom.get("rows")) and final is None,
    }


def portfolio(items):
    """items: [{"rfq_id", "customer", "project", "path", "generated"}] (newest export of each RFQ). Totals are summed only over RFQs in the most
    common currency (the others are listed and counted apart): adding USD to EUR would be a wrong number."""
    rows = []
    for item in items:
        try:
            rows.append(_portfolio_row(item, _read(item["path"])))
        except Exception as e:
            rows.append({"rfq_id": item["rfq_id"], "customer": item.get("customer"), "project": item.get("project"), "error": f"{type(e).__name__}: {str(e)[:120]}"})
    ok = [r for r in rows if "error" not in r]
    currencies = [r["currency"] for r in ok if r.get("currency")]
    main = max(set(currencies), key=currencies.count) if currencies else None
    same = [r for r in ok if r.get("currency") == main]
    total = lambda key: sum((r.get(key) or 0) for r in same)   # noqa: E731
    buy, final = total("buy"), total("final_buy")
    rows_all, priced_all = total("rows"), total("priced")
    lead = {name: sum(r["lead_time"].get(name, 0) for r in same) for name in [n for n, _, _ in LEAD_BUCKETS] + ["no lead time"]}
    commodities = {}
    for r in same:
        for name, value in (r.get("commodity_excess") or {}).items():
            commodities[name] = commodities.get(name, 0.0) + value
    return {
        "rfqs": sorted(rows, key=lambda r: r["rfq_id"], reverse=True),
        "totals": {"total_rfqs": len(ok), "currency": main, "counted_rfqs": len(same), "other_currency_rfqs": len(ok) - len(same),
                   "cash_rfqs": sum(1 for r in same if r.get("final_buy") is not None),
                   "costing_pct": (priced_all / rows_all) if rows_all else None, "final_buy": final, "buy": buy,
                   "buy_variance": ((final - buy) / buy) if buy else None, "excess_cost": total("excess_cost"),
                   "critical_exceptions": total("critical"), "lead_time": lead, "commodity_excess": commodities, "errors": len(rows) - len(ok),
                   "without_stored_values": sum(1 for r in ok if r.get("needs_values"))},
        "definitions": DEFINITIONS,
    }


def _bom_matrix(wb):
    """The BOM MATRIX tab: each part's quantity in each assembly (the header row names the assemblies, the Part Number column names the
    parts). A '-' or a blank is no quantity, read as 0. Returns the assemblies and the parts, in the tab's own order."""
    if "BOM MATRIX" not in wb.sheetnames:
        return None
    rows = list(wb["BOM MATRIX"].iter_rows(max_col=12, values_only=True))
    head = next((i for i, r in enumerate(rows) if r and str(r[0] or "").strip() == "Part Number"), None)
    if head is None:
        return None
    header = list(rows[head])
    total_col = header.index("Grand Total") if "Grand Total" in header else None
    commodity_col = header.index("Commodity") if "Commodity" in header else None
    stop = header.index("Grand Total") if total_col is not None else None
    # Assemblies are the header cells between the Part Number and the first summary column (Grand Total or EAU)
    assemblies = []
    for i in range(1, stop if stop is not None else len(header)):
        name = str(header[i] or "").strip()
        if not name or name.startswith("EAU"):
            break
        assemblies.append((i, name))
    parts = []
    for r in rows[head + 1:]:
        part = str(r[0] or "").strip() if r else ""
        if not part:
            continue
        qty = {name: (_num(r[i]) or 0.0) for i, name in assemblies}
        parts.append({
            "part": part,
            "quantities": qty,
            "grand_total": _num(r[total_col]) if total_col is not None else None,
            "commodity": str(r[commodity_col]).strip() if commodity_col is not None and r[commodity_col] else None,
        })
    return {"assemblies": [name for _, name in assemblies], "parts": parts}
