"""Shared Excel presentation building blocks: styles, DB->payload mappings, formula templates.

- excel_styles.py     -- shared fill/font/border constants for sheets this module builds
                          directly (the raw "CBOM" tab; the 16 report tabs keep their own
                          already-verified local style constants, unchanged -- see README
                          "Design boundary" note).
- excel_mappings.py   -- reshapes RFQ-scoped DuckDB rows into the exact payload shape each
                          reports/*.py module's compute function expects.
- formula_templates.py -- reusable Excel number-format strings (money/percent) applied by
                          excel_formatter.py.
"""
