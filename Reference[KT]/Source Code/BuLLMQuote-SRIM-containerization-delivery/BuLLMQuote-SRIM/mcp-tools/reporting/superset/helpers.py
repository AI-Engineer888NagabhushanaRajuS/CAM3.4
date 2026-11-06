"""Small, generic utility functions shared across the module -- SQL-literal quoting,
filename slugification, and pandas/openpyxl NA-value sanitization. No business logic.
"""

import re
import unicodedata
import uuid as uuidlib

import pandas as pd


def sql_quote(value):
    """SQL-quote a string literal (single-quote doubling)."""
    return "'" + str(value).replace("'", "''") + "'"


def slugify(value):
    """Filesystem/Excel-sheet-safe slug -- used for exported workbook filenames."""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return value[:60] or "unknown_rfq"


def excel_safe(value):
    """Converts a single value to something openpyxl's Cell.value setter accepts:
    UUID -> str, any pandas NA sentinel -> None, everything else passes through.
    """
    if isinstance(value, uuidlib.UUID):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def sanitize_dataframe(df):
    """Replaces pandas/numpy NA sentinels (pd.NA, NaN, NaT) with plain Python None
    everywhere, including inside nullable-dtype columns (BOOLEAN/Int64/etc, which
    `.where(notnull, None)` alone doesn't fully clean) -- openpyxl's Cell.value setter
    rejects pd.NA outright, and downstream code reads values via direct .get()/.iloc[]
    access, so this must happen once at load time.
    """
    return df.astype(object).where(df.notnull(), None)


def records(df):
    return df.to_dict("records")
