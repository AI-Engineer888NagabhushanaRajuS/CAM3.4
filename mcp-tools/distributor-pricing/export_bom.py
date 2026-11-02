import datetime
import json
import re
import uuid
from pathlib import Path

import duckdb
import numpy as np
import openpyxl
import pandas as pd

from config import DB_PATH
# config.py's own import already put mcp-tools/ on sys.path -- see that
# file's own sys.path.insert(). Single source of truth for the "manually
# edited cell" highlight color, shared with duck_db_api.py's Gerber export
# and quote_summary.py below -- keep all three in sync.
from shared.highlight_style import MANUAL_EDIT_FILL_ARGB

_MANUAL_EDIT_FILL = openpyxl.styles.PatternFill("solid", fgColor=MANUAL_EDIT_FILL_ARGB)

# ==========================================================
# EXISTING TEMPLATE TO FILL
# ==========================================================

# [BuLLMQuote-SRIM MIGRATION NOTE -- fixed 2026-08-11] Was hardcoded to
# C:\Users\ADMIN\Documents\SRIM\Tools\distributor_pricing\... -- a path that
# never actually existed (missing the "I n D" segment the old live location
# has: SRIM\Tools\I n D\distributor_pricing\...), so export_enriched_bom
# always failed with "Excel template not found." The real template has been
# copied alongside this file so it travels with this repo instead of
# depending on the old tree; resolved relative to this file so it can't
# drift out of sync with wherever this script itself lives again.
TEMPLATE_PATH = Path(__file__).resolve().parent / "Distributor_Verification_Output.xlsx"

# A handful of common friendly labels that don't normalize onto their
# DuckDB column name directly (e.g. "Mouser Price" has no "unit" in it).
HEADER_ALIASES = {
    "digikey_price": "digikey_unit_price",
    "element14_price": "element14_unit_price",
    "mouser_price": "mouser_unit_price",
}


def _to_excel_value(value):
    """Coerce DB/pandas types openpyxl can't natively write into plain
    Python types it can (UUID -> str, numpy scalars -> native, NaT/NaN
    -> None)."""

    if value is None:
        return None

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, (pd.Timestamp,)):
        if pd.isna(value):
            return None
        return value.to_pydatetime()

    if isinstance(value, np.generic):
        value = value.item()

    if isinstance(value, float) and value != value:  # NaN
        return None

    if isinstance(value, (datetime.date, datetime.datetime, str, int, float, bool)):
        return value

    return str(value)


def _normalize(label):
    return re.sub(
        r"[^a-z0-9]+", "_", str(label).strip().lower()
    ).strip("_")


def _build_header_map(header_row):
    """excel column letter position (1-indexed) -> db column name it maps to."""

    header_map = {}
    matched_headers = []

    for col_idx, cell in enumerate(header_row, start=1):

        if cell.value is None:
            continue

        normalized = _normalize(cell.value)
        db_column = HEADER_ALIASES.get(normalized, normalized)

        header_map[col_idx] = db_column
        matched_headers.append((cell.value, db_column))

    return header_map, matched_headers


def export_bom(rfq_id):

    rfq_id = str(rfq_id).strip()

    # ----------------------------------------------------
    # LOAD DB DATA
    # ----------------------------------------------------

    with duckdb.connect(DB_PATH) as conn:
        df = conn.execute(
            """
            SELECT *
            FROM processed_bom_items
            WHERE CAST(rfq_id AS VARCHAR)=?
            """,
            [rfq_id]
        ).fetchdf()

    # ----------------------------------------------------
    # LOAD EXISTING TEMPLATE (openpyxl — preserves styles,
    # formatting, formulas and any other sheets untouched)
    # ----------------------------------------------------

    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Excel template not found: {TEMPLATE_PATH}"
        )

    workbook = openpyxl.load_workbook(TEMPLATE_PATH)
    sheet = workbook.active

    print("\n========================================")
    print(" EXCEL EXPORT (TEMPLATE FILL)")
    print("========================================")
    print(f"Excel template loaded : {TEMPLATE_PATH.name}")

    header_row = next(
        sheet.iter_rows(min_row=1, max_row=1)
    )
    header_map, matched_headers = _build_header_map(header_row)

    db_columns = list(df.columns)
    matched_db_columns = {
        db_col for db_col in header_map.values()
    } & set(db_columns)
    skipped_db_columns = [
        col for col in db_columns
        if col not in matched_db_columns
    ]

    max_col = sheet.max_column
    max_row = sheet.max_row

    # ----------------------------------------------------
    # CLEAR EXISTING DATA ROWS (row 1 header is untouched;
    # cell formatting/styles stay attached to the cell — only
    # .value is cleared)
    # ----------------------------------------------------

    for row_idx in range(2, max_row + 1):
        for col_idx in range(1, max_col + 1):
            sheet.cell(row=row_idx, column=col_idx).value = None

    # ----------------------------------------------------
    # WRITE FRESH ENRICHED DATA INTO MATCHING COLUMNS ONLY
    # ----------------------------------------------------

    records = df.to_dict("records")

    for row_offset, record in enumerate(records):

        row_idx = row_offset + 2

        try:
            edited_fields = set(json.loads(record.get("manually_edited_fields") or "[]"))
        except (TypeError, ValueError):
            edited_fields = set()

        for col_idx, db_column in header_map.items():

            if db_column not in record:
                continue

            value = _to_excel_value(record[db_column])

            cell = sheet.cell(row=row_idx, column=col_idx)
            cell.value = value
            if db_column in edited_fields:
                cell.fill = _MANUAL_EDIT_FILL

    # ----------------------------------------------------
    # SAVE AS A NEW FILE — ORIGINAL TEMPLATE IS NEVER OVERWRITTEN
    #
    # Scoped by rfq_id + timestamp (not a fixed shared filename) -- a fixed
    # "_filled.xlsx" name meant every RFQ's export clobbered the previous
    # one, and duck_db_api.py's download endpoint has no way to pick the
    # right file for a specific rfq_id without this. Mirrors reporting_
    # module's own CBOM_Report_<key>_<timestamp>.xlsx convention.
    # ----------------------------------------------------

    rfq_slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", rfq_id).strip("_")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = TEMPLATE_PATH.with_name(
        f"{TEMPLATE_PATH.stem}_{rfq_slug}_{timestamp}{TEMPLATE_PATH.suffix}"
    )

    workbook.save(output_path)

    print(f"Rows written           : {len(records)}")
    print(f"Columns matched        : {len(matched_db_columns)}")
    print(f"Columns skipped        : {len(skipped_db_columns)}")
    if skipped_db_columns:
        for col in skipped_db_columns:
            print(f"    - {col}")
    print(f"Output file path       : {output_path}")
    print("========================================\n")

    return {
        "status": "success",
        "rows_written": len(records),
        "columns_matched": len(matched_db_columns),
        "columns_skipped": len(skipped_db_columns),
        "skipped_columns": skipped_db_columns,
        "output_file": str(output_path)
    }


if __name__ == "__main__":

    rfq_id = input(
        "Enter RFQ ID: "
    ).strip()

    result = export_bom(
        rfq_id
    )

    print(result)
