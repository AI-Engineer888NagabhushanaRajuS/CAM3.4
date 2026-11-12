"""CAM Formula Engine - an Excel-formula calculation engine built from the
reverse-engineered CAM corpus semantics.

Public API:
    from excel_formula_engine import Workbook, parse_formula
    wb = Workbook("file.xlsx")
    v = wb.cell_value_now("BOM MATRIX", 9, 7)
    wb.set_value("7.0 CBOM VL-1", 26, 16, 5.0)   # edit -> dependents recalc
"""
from .parser import parse_formula, ParseError
from .workbook import Workbook
from .values import (ErrorValue, BLANK, NA, VALUE_ERR, REF_ERR, DIV0,
                     NAME_ERR, NUM_ERR, is_error, is_blank)

__version__ = "0.1.0"
