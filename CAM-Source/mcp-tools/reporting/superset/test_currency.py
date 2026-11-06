"""Unit tests for currency.py -- the consolidated, Postgres-backed currency
conversion source of truth (see the module's own docstring for what it replaced).

Uses the standard library's unittest (no pytest -- this project has no existing
unit-test framework/convention to build on; unittest needs no new dependency).
Run with: python -m unittest test_currency -v
"""

import unittest
from unittest.mock import MagicMock, patch

import currency


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **kw):
        pass

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self._rows)


def _mock_logic_connection(rows):
    return patch.object(currency, "get_logic_connection", return_value=FakeConn(rows))


class CurrencyTests(unittest.TestCase):
    def setUp(self):
        currency.clear_cache()

    def tearDown(self):
        currency.clear_cache()

    def test_get_currency_rates(self):
        with _mock_logic_connection([("USD", "1.000000"), ("INR", "83.500000"), ("EUR", "0.930000")]):
            rates = currency.get_currency_rates()
        self.assertEqual(rates, {"USD": 1.0, "INR": 83.5, "EUR": 0.93})

    def test_get_currency_rates_is_cached(self):
        # Only the FIRST call should touch the "DB" -- verifies the per-run cache
        # (these functions are called per-row, potentially thousands of times).
        with _mock_logic_connection([("USD", "1.0")]) as mocked:
            currency.get_currency_rates()
            currency.get_currency_rates()
            currency.get_currency_rates()
            self.assertEqual(mocked.call_count, 1)

    def test_get_default_quote_currency(self):
        with _mock_logic_connection([("GBP",)]):
            self.assertEqual(currency.get_default_quote_currency(), "GBP")

    def test_get_default_quote_currency_falls_back_to_usd_if_missing(self):
        with _mock_logic_connection([]):
            self.assertEqual(currency.get_default_quote_currency(), "USD")

    def test_build_rate_case_sql_default_column(self):
        with _mock_logic_connection([("USD", "1.0"), ("INR", "83.5")]):
            sql = currency.build_rate_case_sql()
        self.assertIn("CASE currency_original", sql)
        self.assertIn("WHEN 'USD' THEN 1.0", sql)
        self.assertIn("WHEN 'INR' THEN 83.5", sql)
        self.assertIn("ELSE NULL", sql)

    def test_build_rate_case_sql_qualified_column(self):
        with _mock_logic_connection([("USD", "1.0")]):
            sql = currency.build_rate_case_sql("t.currency_original")
        self.assertIn("CASE t.currency_original", sql)

    def test_convert_currency_same_currency_is_noop(self):
        with _mock_logic_connection([("USD", "1.0")]):
            self.assertEqual(currency.convert_currency(100, "USD", "USD"), 100)

    def test_convert_currency_eur_to_usd(self):
        with _mock_logic_connection([("USD", "1.0"), ("EUR", "0.93")]):
            result = currency.convert_currency(100, "EUR", "USD")
        self.assertAlmostEqual(result, 100 / 0.93)

    def test_convert_currency_eur_to_inr(self):
        with _mock_logic_connection([("USD", "1.0"), ("EUR", "0.93"), ("INR", "83.5")]):
            result = currency.convert_currency(100, "EUR", "INR")
        self.assertAlmostEqual(result, (100 / 0.93) * 83.5)

    def test_convert_currency_unknown_currency_raises_instead_of_passing_through(self):
        # SPEC-017 default: an unknown currency must not be reported as if it were USD.
        with _mock_logic_connection([("USD", "1.0")]):
            with self.assertRaises(ValueError):
                currency.convert_currency(100, "XYZ", "USD")

    def test_convert_currency_defaults_target_to_default_quote_currency(self):
        # convert_currency(to_currency=None) resolves get_default_quote_currency()
        # FIRST, then get_currency_rates() -- side_effect order mirrors that.
        with patch.object(
            currency,
            "get_logic_connection",
            side_effect=[
                FakeConn([("INR",)]),
                FakeConn([("USD", "1.0"), ("INR", "83.5")]),
            ],
        ):
            result = currency.convert_currency(100, "USD")
        self.assertAlmostEqual(result, 8350.0)


if __name__ == "__main__":
    unittest.main()
