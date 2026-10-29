"""Scrap Factor tier configuration -- single source of truth for the whole pipeline,
backed by Postgres logic_db.scrap_factor_settings. Mirrors currency.py's own pattern
(get_currency_rates()/build_rate_case_sql()) for the exact same reason: previously the
same three price tiers (>1.25 -> A/1%, >0.25 -> B/2%, else -> C/5%) were hardcoded
independently in queries.py (twice: cbom_insert_sql() and
final_selection_recompute_derived_sql()), reports/summary.py's _scrap_percent(), and
reports/aclass_parts.py's own (dead -- see that module's own comment) recomputation.
Changing a threshold or percentage meant editing code in 4 places. Now every one of
those reads through this module instead, and the generated CBOM workbook also gets a
hidden "Scrap Factor" sheet (see reports/cbom_vl.py's build_scrap_factor_sheet())
populated from this exact same table, with the CBOM VL-1 sheet's own ABC
Classification/Scrap columns looking values up from it via live Excel formulas instead
of a static backend-computed value -- so the sheet, the SQL, and the Python-side MOQ
cost math all agree by construction, not by convention.

Business rule (confirmed): Min Price is INCLUSIVE, Max Price is EXCLUSIVE (a price of
exactly 1.25 is Class A, not B; a price of exactly 0.25 is Class B, not C) -- this is a
deliberate correction versus the previous hardcoded `> 1.25`/`> 0.25` (strict) comparison.

A component is only eligible for a Scrap Class/Percentage at all if it HAS a price --
a component with no price data at all (NULL) gets neither, not a silent default. A
price of exactly 0 is a genuinely valid, present price (not "no price"), and per
explicit business-rule confirmation falls into Class C (its own tier's min_price is
0.0) exactly like any other sub-0.25 price -- it must NOT be treated the same as a
missing price. An EARLIER version of this eligibility guard used `price <= 0`
(inherited from the old hardcoded `ELSE 0.05` branch's own "uncosted" gate, is_costed's
own `price > 0` threshold), which silently left every zero-priced component's Scrap
Class/Percentage blank -- confirmed wrong: zero price is real, present data, not an
absent value. This is a DELIBERATE DIVERGENCE from is_costed (queries.py's
`final_price_conv IS NOT NULL AND final_price_conv > 0`) -- is_costed is a distinct
concept (used for Uncosted Line Items Count, MOQ/SPQ Missing exemptions, etc., all
unchanged by this module) that specifically excludes zero price; Scrap Class
eligibility does not.

Rates are cached for the lifetime of one pipeline run (same reasoning as
currency.py's own cache -- this is read per-row, potentially thousands of times per
report). Call clear_cache() if the table might have changed since the cache was
populated (e.g. a long-lived process/notebook).
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# [BuLLMQuote-SRIM MIGRATION NOTE -- fixed 2026-08-11] see currency.py's
# identical note: db.py now lives in fastmcp-router/, a sibling directory
# three levels up from this file, not its immediate parent.
_PROJECT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR))), "fastmcp-router"
)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from db import get_logic_connection  # noqa: E402  (path setup above must run first)

_table_cache = None

# Seed values used ONLY the first time scrap_factor_settings is empty (a brand-new
# logic_db) -- matches the business rule's own default configuration document. Every
# other read goes through Postgres, not this constant -- this is deliberately NOT
# consulted by classify_price()/build_scrap_class_case_sql()/etc., only by
# ensure_scrap_factor_schema()'s one-time seed insert.
_DEFAULT_TIERS = [
    (1.25, None, "A", 0.01),
    (0.25, 1.25, "B", 0.02),
    (0.0, 0.25, "C", 0.05),
]


def ensure_scrap_factor_schema():
    """Idempotent migration: creates logic_db.scrap_factor_settings if it doesn't
    already exist, seeding it with the current default 3-tier configuration. Safe to
    call on every request (cheap information_schema-style check via CREATE TABLE IF
    NOT EXISTS) -- same idiom as db.py's ensure_version_schema().

    max_price is nullable -- NULL means "no upper bound" (the top-most tier).
    """
    with get_logic_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS scrap_factor_settings (
                    id SERIAL PRIMARY KEY,
                    min_price DOUBLE PRECISION NOT NULL,
                    max_price DOUBLE PRECISION,
                    scrap_class VARCHAR NOT NULL,
                    scrap_percent DOUBLE PRECISION NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT true
                )
                """
            )
            cursor.execute("SELECT COUNT(*) FROM scrap_factor_settings")
            if cursor.fetchone()[0] == 0:
                cursor.executemany(
                    """
                    INSERT INTO scrap_factor_settings (min_price, max_price, scrap_class, scrap_percent)
                    VALUES (%s, %s, %s, %s)
                    """,
                    _DEFAULT_TIERS,
                )
            conn.commit()


def clear_cache():
    """Forces the next get_scrap_factor_table() call to re-query Postgres. Not needed
    within one pipeline run (the table doesn't change mid-run); exposed for tests and
    long-lived processes.
    """
    global _table_cache
    _table_cache = None


def get_scrap_factor_table():
    """[{"min_price": 0.0, "max_price": 0.25, "scrap_class": "C", "scrap_percent": 0.05}, ...],
    ordered by min_price ascending -- every active tier, fetched fresh from Postgres on
    first use this run (then cached; see clear_cache()).
    """
    global _table_cache
    if _table_cache is None:
        ensure_scrap_factor_schema()
        with get_logic_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT min_price, max_price, scrap_class, scrap_percent "
                    "FROM scrap_factor_settings WHERE is_active = true ORDER BY min_price ASC"
                )
                _table_cache = [
                    {
                        "min_price": float(min_price),
                        "max_price": (float(max_price) if max_price is not None else None),
                        "scrap_class": scrap_class,
                        "scrap_percent": float(scrap_percent),
                    }
                    for min_price, max_price, scrap_class, scrap_percent in cur.fetchall()
                ]
    return _table_cache


def classify_price(price):
    """(scrap_class, scrap_percent) for a single unit price, in pure Python -- used by
    reports/summary.py's MOQ-cost math, which needs a plain number to keep computing
    with (net_order_qty, net_excess_cost, ...), not a live Excel formula (that
    computation chain lives entirely in Python, not in the workbook itself).

    Returns (None, None) if `price` is None (no price data at all -- not eligible for
    scrap calculation) or if no configured tier's range contains it (a misconfigured
    table with a gap, or a negative price no tier's min_price ever reaches -- fails
    safe rather than guessing). A price of exactly 0 IS eligible (falls into whichever
    tier's range contains 0, normally Class C) -- 0 is a real, present price, not a
    missing one; only None means "not eligible".
    """
    if price is None:
        return None, None
    for tier in get_scrap_factor_table():
        if price >= tier["min_price"] and (tier["max_price"] is None or price < tier["max_price"]):
            return tier["scrap_class"], tier["scrap_percent"]
    return None, None


def _tiers_desc():
    return sorted(get_scrap_factor_table(), key=lambda t: t["min_price"], reverse=True)


def _eligibility_guard_sql(price_column):
    # NULL only -- a price of exactly 0 is present, real data (Class C, same as any
    # other sub-0.25 price), not "not eligible". See classify_price()'s own docstring
    # for why this deliberately does NOT reuse is_costed's `price > 0` threshold.
    return f"({price_column} IS NULL)"


def build_scrap_class_case_sql(price_column):
    """Dynamically builds a `CASE WHEN <not eligible> THEN NULL WHEN price >= tier1.min
    THEN 'tier1.class' ... ELSE NULL END` SQL expression from get_scrap_factor_table()
    -- replaces the old hardcoded `CASE WHEN final_price_conv > 1.25 THEN 'A' ... END`
    in queries.py. Tiers are walked highest-min-price-first so the FIRST matching WHEN
    is always the correct (and only, given a gap-free, non-overlapping configured
    table) bucket -- relies on `price_column >= min_price` alone (no upper-bound check
    needed) precisely because contiguous, sorted-descending tiers make that equivalent
    to "min <= price < next tier's min" for every tier but the topmost, which has no
    upper bound by definition.
    """
    when_clauses = "\n        ".join(
        f"WHEN {price_column} >= {tier['min_price']} THEN '{tier['scrap_class']}'" for tier in _tiers_desc()
    )
    return (
        f"(CASE WHEN {_eligibility_guard_sql(price_column)} THEN NULL\n"
        f"        {when_clauses}\n"
        f"        ELSE NULL END)"
    )


def build_scrap_percent_case_sql(price_column):
    """Same as build_scrap_class_case_sql(), for the Scrap Percentage value instead of
    the Scrap Class label."""
    when_clauses = "\n        ".join(
        f"WHEN {price_column} >= {tier['min_price']} THEN {tier['scrap_percent']}" for tier in _tiers_desc()
    )
    return (
        f"(CASE WHEN {_eligibility_guard_sql(price_column)} THEN NULL\n"
        f"        {when_clauses}\n"
        f"        ELSE NULL END)"
    )
