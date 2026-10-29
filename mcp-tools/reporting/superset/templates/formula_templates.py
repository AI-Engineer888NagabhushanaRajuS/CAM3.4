"""Reusable Excel number-format strings, applied by excel_formatter.py to the raw "CBOM"
tab. The 16 report tabs (reports/*.py) already set their own number formats locally
(verified against the reference production workbook in an earlier pass -- money columns
at 4 decimal places, percentage columns at Excel `%` format); those are left untouched,
consistent with the "Design boundary" note in excel_styles.py.
"""

MONEY_FORMAT = '"$"#,##0.0000'
PERCENT_FORMAT = "0.00%"
