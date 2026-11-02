"""Currency conversion rates + the default quote currency -- single source of truth for
the whole pipeline, backed by Postgres logic_db.currency_conversion_rates /
currency_settings (managed via accomplish-ui's Settings -> Currencies admin UI, see
apps/daemon/src/browser-api-server.ts's ensureCurrencySchema()/currency.* RPC cases).

Previously this module (and 7 other files: queries.py's _rate_case()/_to_usd_sql(),
templates/excel_mappings.py, and 6 report files' local _CURRENCY_RATES/_convert_currency()
pairs) each hardcoded the same {"USD": 1.0, "INR": 83.5, "EUR": 0.93} independently --
changing a rate or adding a currency meant editing code in 8 places. Now every one of
those reads through this module instead.

Rates are cached for the lifetime of one pipeline run (these functions are called
per-row, potentially thousands of times per report -- querying Postgres on every call
would be far too slow). Call clear_cache() at the start of a fresh run if rates might
have changed since the cache was populated (e.g. a long-lived process/notebook).
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# [BuLLMQuote-SRIM MIGRATION NOTE -- fixed 2026-08-11] db.py lives in
# fastmcp-router/, not one level up from this file. That was correct at the
# old location (centum intake/reporting_module/ -> centum intake/db.py, one
# level up) but this copy sits three levels below the repo root
# (mcp-tools/reporting/superset/), with db.py now in a sibling directory
# (fastmcp-router/), not an ancestor -- os.path.dirname(_THIS_DIR) landed on
# the nonexistent mcp-tools/reporting/db.py instead, raising
# ModuleNotFoundError at import time (confirmed: crashed reporting_mcp_server
# on startup).
_PROJECT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR))), "fastapi-router"
)
if _PROJECT_DIR not in sys.path:
    sys.path.append(_PROJECT_DIR)  # append: this folder's own config.py must win the name lookup

from db import get_logic_connection  # noqa: E402  (path setup above must run first)

_rates_cache = None
_default_currency_cache = None


def clear_cache():
    """Forces the next get_currency_rates()/get_default_quote_currency() call to
    re-query Postgres. Not needed within one pipeline run (rates don't change
    mid-run); exposed for tests and long-lived processes.
    """
    global _rates_cache, _default_currency_cache
    _rates_cache = None
    _default_currency_cache = None


def get_currency_rates():
    """{"USD": 1.0, "INR": 83.5, ...} for every active currency -- units of that
    currency per 1 USD (USD's own rate is always 1.0, the fixed internal pivot;
    matches the convention every one of the 8 consolidated call sites already used).
    """
    global _rates_cache
    if _rates_cache is None:
        with get_logic_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT currency_code, conversion_rate FROM currency_conversion_rates "
                    "WHERE is_active = true"
                )
                _rates_cache = {code: float(rate) for code, rate in cur.fetchall()}
    return _rates_cache


def get_default_quote_currency():
    """The admin-configured standard output currency for CBOM/Price Splits/reports/
    exports (Settings -> Currencies -> "default quote currency"). Falls back to
    'USD' only if the settings row is somehow missing (should never happen once
    ensureCurrencySchema() has run at least once).
    """
    global _default_currency_cache
    if _default_currency_cache is None:
        with get_logic_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT default_quote_currency_code FROM currency_settings WHERE id = 1")
                row = cur.fetchone()
                _default_currency_cache = row[0] if row else "USD"
    return _default_currency_cache


def build_rate_case_sql(column_ref="currency_original"):
    """Dynamically builds a `CASE {column_ref} WHEN 'USD' THEN 1.0 ... ELSE NULL END`
    SQL expression from get_currency_rates() -- replaces both the old hardcoded
    CURRENCY_RATE_CASE_SQL constant (bare `currency_original`) and queries.py's
    duplicate _rate_case(column) (needed a column-qualified version since
    costing_sheet/erp joins have their own currency columns in scope). Any currency
    outside the active set still resolves to NULL, never silently guessed --
    same behavior as before.
    """
    rates = get_currency_rates()
    when_clauses = "\n        ".join(f"WHEN '{code}' THEN {rate}" for code, rate in rates.items())
    return f"""
    CASE {column_ref}
        {when_clauses}
        ELSE NULL
    END
    """


def convert_currency(amount, from_currency, to_currency=None):
    """Generalized version of the 6 duplicated per-report `_convert_currency()`
    helpers -- `to_currency` now defaults to get_default_quote_currency() instead
    of each call site's hardcoded "USD" literal. Falls back to the raw amount
    raises if either currency isn't in the active rate table: an unconverted amount reported
    as if it were in the target currency is a silent wrong number (SPEC-017 default).
    """
    if to_currency is None:
        to_currency = get_default_quote_currency()
    rates = get_currency_rates()
    if from_currency not in rates or to_currency not in rates:
        raise ValueError(
            f"no active conversion rate for {from_currency!r} -> {to_currency!r}; "
            "refusing to report an unconverted amount"
        )
    usd_amount = amount / rates[from_currency]
    return usd_amount * rates[to_currency]
