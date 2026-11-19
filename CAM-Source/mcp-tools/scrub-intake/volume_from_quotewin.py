"""FG volumes for a SCRUB BOM workbook that has no Settings / Batch sheet, taken from the QuoteWin awards.

Found 2026-11-18: 7 of the 25 Centum batch workbooks (05, 06, 11, 17, 20, 22, 23) carry no Settings or Batch sheet. The volume table
stayed empty, every FG volume read as 0, and every volume-dependent figure of the report (extended cost, Ex Inv, A CLASS turns, batchwise
cashflow) came out 0.

The QuoteWin "Awarded Volume #n" of a part is the part's total demand for volume n. For a part used under ONE FG only, demand divided by the
BOM line's quantity (x hierarchy multiplier) is that FG's volume: the awards are per line, so the ratio is taken per
scrub row (batch-06: 540 of 568 rows give 30; summing a part's rows first would divide by the wrong quantity). Across a BOM those ratios agree (batch-05: 3700,
the figure its own Sheet1 states). A volume is taken only when one value is clearly dominant (at least MIN_PARTS parts and MIN_SHARE of
them); otherwise nothing is invented and the FG stays without that volume, as before. With no batch plan in the workbook, each volume is
one batch. Every derived value is recorded in input_notes, so the report's Run Inputs tab says where it came from.
"""
import collections
import re

from scrub_bom_to_database import DB_PATH, _ensure_batch_schema, _ensure_volume_schema, connect_db

MIN_PARTS = 3
MIN_SHARE = 0.5

NOTES_DDL = """
CREATE TABLE IF NOT EXISTS input_notes (
    rfq_id VARCHAR,
    item VARCHAR,
    status VARCHAR,
    detail VARCHAR
)
"""


def _slots(con):
    cols = [r[0] for r in con.execute("DESCRIBE quote_win").fetchall()]
    return sorted(int(m.group(1)) for c in cols for m in [re.fullmatch(r"awarded_volume_(\d+)", c)] if m)


def dominant(ratios):
    """(value, support, share) of the most common ratio, or None when it is not clearly dominant."""
    if not ratios:
        return None
    value, support = collections.Counter(ratios).most_common(1)[0]
    share = support / len(ratios)
    if support < MIN_PARTS and share < 1.0:
        return None
    if share < MIN_SHARE:
        return None
    return value, support, share


def derive(key, db_path=None):
    """Fills volume and batch for this RFQ version when the workbook gave none. Returns what it did (never raises on data)."""
    with connect_db(db_path or DB_PATH) as con:
        _ensure_volume_schema(con)
        _ensure_batch_schema(con)
        con.execute(NOTES_DDL)
        if con.execute("SELECT count(*) FROM volume WHERE rfq_id = ?", [key]).fetchone()[0]:
            return {"derived": False, "reason": "the BOM workbook gives the volumes"}
        if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'quote_win'").fetchone()[0]:
            return {"derived": False, "reason": "no QuoteWin table"}
        rows = con.execute(
            """
            SELECT fg, upper(trim(cpn)) AS cpn, quantity * coalesce(hierarchy_multiplier, 1) AS qty
            FROM scrub_bom_items
            WHERE rfq_id = ? AND quantity > 0 AND cpn IS NOT NULL AND upper(trim(cpn)) <> upper(trim(fg))
              AND coalesce(trim(level), '') NOT IN ('0', '0.0')
            """, [key]).fetchall()
        slots = _slots(con)
        if not rows or not slots:
            return {"derived": False, "reason": "no BOM parts or no awarded volumes"}
        awarded = {}
        for n in slots:
            for pn, value in con.execute(
                f"SELECT upper(trim(part_number)), mode(awarded_volume_{n}) FROM quote_win "
                f"WHERE rfq_id = ? AND awarded_volume_{n} > 0 GROUP BY 1", [key]).fetchall():
                awarded[(pn, n)] = value
        fgs = sorted({fg for fg, _, _ in rows})
        by_cpn = {}                                   # cpn -> {fg: quantity of its first line under that FG}
        for fg, cpn, qty in rows:
            by_cpn.setdefault(cpn, {}).setdefault(fg, qty)
        found, vol = [], {}
        for n in slots:
            # Pass 1: lines of parts used under one FG only.
            for fg in fgs:
                ratios = [round(awarded[(cpn, n)] / qty) for f, cpn, qty in rows
                          if f == fg and len(by_cpn[cpn]) == 1 and (cpn, n) in awarded and qty]
                best = dominant(ratios)
                if best:
                    vol[(fg, n)] = float(best[0])
                    found.append((fg, n, float(best[0]), best[1], len(ratios)))
            # Pass 2: an FG with no part of its own. A part shared with FGs already known carries the sum of their demands
            # (batch-05: shared parts 3700 = 681H33201's 3000 + 681H31201's 700), so its volume is the remainder.
            progress = True
            while progress:
                progress = False
                for fg in fgs:
                    if (fg, n) in vol:
                        continue
                    ratios = []
                    for cpn, per_fg in by_cpn.items():
                        others = [o for o in per_fg if o != fg]
                        if fg in per_fg and others and all((o, n) in vol for o in others) and (cpn, n) in awarded and per_fg[fg]:
                            rest = awarded[(cpn, n)] - sum(vol[(o, n)] * per_fg[o] for o in others)
                            if rest > 0:
                                ratios.append(round(rest / per_fg[fg]))
                    best = dominant(ratios)
                    if best:
                        vol[(fg, n)] = float(best[0])
                        found.append((fg, n, float(best[0]), best[1], len(ratios)))
                        progress = True
        missing = sorted({fg for fg in fgs} - {fg for fg, *_ in found})
        if not found:
            return {"derived": False, "reason": "the awarded volumes do not agree on one value per FG", "fgs": fgs}
        for fg, n, volume, support, total in found:
            con.execute("INSERT INTO volume (fg, volume_name, batch_qty, rfq_id) VALUES (?, ?, ?, ?)", [fg, f"V{n}", volume, key])
            con.execute("INSERT INTO batch (fg, volume, batch_qty, rfq_id) VALUES (?, ?, ?, ?)", [fg, f"V{n}", volume, key])
        detail = "; ".join(f"{fg} V{n} = {volume:g} ({support} of {total} parts agree)" for fg, n, volume, support, total in found)
        con.execute("DELETE FROM input_notes WHERE rfq_id = ? AND item = 'Volumes'", [key])
        con.execute("INSERT INTO input_notes VALUES (?, 'Volumes', 'DERIVED from QuoteWin', ?)",
                    [key, "The BOM workbook has no Settings sheet. Volume = QuoteWin awarded volume / quantity per FG, from parts used "
                          f"under one FG only: {detail}. No Batch sheet either: each volume is one batch. Check against the customer's "
                          "volumes." + (f" Not derivable (no part used under that FG alone, or no dominant value): {', '.join(missing)}; "
                                       "its volume-dependent figures stay 0." if missing else "")])
        return {"derived": True, "not_derived": missing, "volumes": [{"fg": fg, "volume": f"V{n}", "qty": volume, "parts_agreeing": support, "parts": total}
                                             for fg, n, volume, support, total in found]}
