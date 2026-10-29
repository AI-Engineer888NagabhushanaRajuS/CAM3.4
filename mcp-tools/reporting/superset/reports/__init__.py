"""16 report-builder modules -- one per CBOM workbook tab.

Each module is a self-contained, production-reverse-engineered port of the corresponding
Laravel Excel export: a pure-Python `compute()`-style function (no DB access, takes a
payload dict) plus a `build_*_sheet(wb, ...)` function that writes the styled worksheet,
including live Excel formulas wherever the real production workbook uses them.

These modules are unchanged from their original, independently-tested form -- this
refactor only relocated them into a single self-contained package. See the module
docstring of each file for its own PHP source references and formula/quirk documentation.
"""
