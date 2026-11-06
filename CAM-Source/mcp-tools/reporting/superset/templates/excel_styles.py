"""Shared openpyxl style constants for the sheets this module builds directly (currently
just the raw "CBOM" tab -- see exporter.py). The 16 report tabs in reports/*.py already
carry their own local style constants, verified byte-for-byte against the reference
production workbook; they are NOT repointed at this file, to avoid touching
already-tested, already-verified code for a cosmetic consistency gain (see README
"Design boundary" section for the full rationale).

These constants happen to match what every reports/*.py module already uses locally
(navy header, light-blue data rows) -- same palette, kept as a single named source for
any NEW sheet-building code added to this module going forward.
"""

from openpyxl.styles import Border, Font, PatternFill, Side

HEADER_FILL = PatternFill("solid", fgColor="2F5496")
HEADER_FONT = Font(bold=True, color="FFFFFF")
DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
TOTAL_FILL = PatternFill("solid", fgColor="FFD966")

_THIN_SIDE = Side(style="thin", color="000000")
THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)
