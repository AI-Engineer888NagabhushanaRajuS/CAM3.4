"""Currency conversion for distributor-fetched prices -- reads the same canonical
rate table reporting_module's currency.py already centralizes
(logic_db.currency_conversion_rates, admin-managed via accomplish-ui's
Settings -> Currencies UI) rather than hardcoding a duplicate USD->INR rate here.
distributor_pricing has no other Postgres access today (DuckDB-only, see
config.py/shared/db_config.py), so this connects directly instead of importing
reporting_module's own currency.py across a sibling tool-server's directory.

Rates are cached for the lifetime of the process (mirrors reporting_module's own
per-run cache) -- enrich_bom can call this hundreds of times per RFQ.
"""

import os

import psycopg2

LOGIC_DB_URL = os.environ["LOGIC_DB_URL"]

_rates_cache = None

# Falls back to this fixed rate only if logic_db is unreachable -- keeps
# enrichment usable rather than leaving every price unconverted, but this
# path should never be hit once logic_db is up (see get_currency_rates()).
_FALLBACK_USD_TO_INR = 83.5


def get_currency_rates():
    """{"USD": 1.0, "INR": 83.5, ...} -- units of that currency per 1 USD.
    Same convention as reporting_module's currency.py."""
    global _rates_cache
    if _rates_cache is None:
        try:
            conn = psycopg2.connect(LOGIC_DB_URL)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT currency_code, conversion_rate FROM currency_conversion_rates "
                        "WHERE is_active = true"
                    )
                    _rates_cache = {code: float(rate) for code, rate in cur.fetchall()}
            finally:
                conn.close()
        except Exception as e:
            print(f"[CURRENCY] Could not reach logic_db, using fallback rates: {e}")
            _rates_cache = {"USD": 1.0, "INR": _FALLBACK_USD_TO_INR}

        if "USD" not in _rates_cache or "INR" not in _rates_cache:
            _rates_cache.setdefault("USD", 1.0)
            _rates_cache.setdefault("INR", _FALLBACK_USD_TO_INR)

    return _rates_cache


def convert_to_inr(amount, from_currency):
    """Converts amount (in from_currency) to INR. Returns None for an amount
    that's already None, or a currency this rate table doesn't know about --
    never silently mislabels an unconverted number as INR."""
    if amount is None:
        return None
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None
    rates = get_currency_rates()
    from_currency = (from_currency or "USD").upper()
    if from_currency not in rates:
        print(f"[CURRENCY] Unknown currency '{from_currency}' -- leaving unconverted")
        return None
    usd_amount = amount / rates[from_currency]
    return usd_amount * rates["INR"]
