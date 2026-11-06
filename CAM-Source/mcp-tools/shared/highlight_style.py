# Single source of truth for the "manually edited cell" highlight color used
# across every Python-side Excel export (export_bom.py, quote_summary.py,
# gerber-integration's report export). MUST match the frontend's own copy of
# this same color in accomplish-ui/apps/web/src/client/components/execution/
# StageExecutionOutput.tsx (MANUAL_EDIT_FILL) -- if one changes, update both.
#
# openpyxl's PatternFill wants an 8-char ARGB hex string (alpha + RGB), fully
# opaque here since Excel cell fills don't composite the way CSS rgba() does.
MANUAL_EDIT_FILL_ARGB = "FFFFF9C4"
