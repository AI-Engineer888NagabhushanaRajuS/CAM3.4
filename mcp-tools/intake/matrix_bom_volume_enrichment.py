"""
Schema-flexible enrichment of a matrix-format Consolidated BOM with
volume-weighted Required_Qty_V1, Required_Qty_V2, ... columns.

This module is intentionally independent from bom_processing.py's
flat/hierarchical BOM-Level pipeline (build_volume_map, _build_bom_structure,
_expand_recursive, consolidate_bom) - it targets a different input shape: a
"matrix" Consolidated BOM where each Finished-Good (FG) assembly is its own
column (rather than a row-level Assembly/FG field), matched against a volume
file that may contain multiple volume scenarios (V1, V2, ...).

Nothing in bom_processing.py, server.py, or the database/enrichment modules
is imported or modified by this file.
"""

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


# ============================================================
# Alias / pattern constants
# ============================================================

ID_COLUMN_ALIASES = [
    "CPN", "FG", "FG CPN", "FG NUMBER", "FG CODE",
    "ASSEMBLY", "ASSY", "ASSY #", "ASSY NO", "ASSY NUMBER",
    "ITEM PART", "ITEM PART NUMBER", "UBR", "UBR NUMBER",
]

ID_COLUMN_PATTERN = re.compile(
    r"\b(CPN|FG|ASSY|ASSEMBLY|UBR|ITEM\s*PART)\b",
    re.IGNORECASE,
)

VOLUME_COLUMN_PATTERN = re.compile(
    r"\b(VOLUME|VOL|VL|V)\s*[\-_]?\s*\d+\b",
    re.IGNORECASE,
)

MIN_ID_UNIQUENESS_RATIO = 0.9
MIN_VOLUME_FILL_RATIO = 0.9

_ANCHOR_TOKENS = [
    "CPN", "ASSEMBLY", "ASSY", "FG", "DESCRIPTION", "MPN", "MFR",
    "SL NO", "CATEGORY", "GRAND TOTAL", "REQUIRED QTY",
    "ORDERING QTY", "UOM", "BOM QTY", "QUANTITY",
]


def _normalize_header(col) -> str:
    return re.sub(r"\s+", " ", str(col).strip()).upper()


def _normalize_id_value(value) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _dedupe_columns(columns):
    seen = Counter()
    result = []
    for col in columns:
        seen[col] += 1
        result.append(col if seen[col] == 1 else f"{col}.{seen[col] - 1}")
    return result


# ============================================================
# Step 1: BOM matrix header-row detection + loading
# ============================================================

def detect_header_row(raw_df: pd.DataFrame, max_scan_rows: int = 10) -> int:
    """
    raw_df must be read with header=None (row 0 = literal sheet row 1).
    Scores each of the first max_scan_rows rows and returns the 0-indexed
    row most likely to be the real header row.
    """
    n_scan = min(max_scan_rows, len(raw_df))
    best_row = None
    best_score = 0

    for i in range(n_scan):
        row = raw_df.iloc[i]
        non_null = row.notna()
        if non_null.sum() == 0:
            continue

        blank_ratio = 1 - (non_null.sum() / len(row))
        if blank_ratio > 0.5:
            continue

        if i + 1 < len(raw_df):
            below_non_null = raw_df.iloc[i + 1].notna().sum()
            if below_non_null == 0 and i < n_scan - 1:
                continue

        score = 0
        for cell in row:
            if pd.isna(cell):
                continue
            text = _normalize_header(cell)
            if any(tok in text for tok in _ANCHOR_TOKENS):
                score += 3
            elif isinstance(cell, str) and cell.strip():
                score += 1

        if score >= best_score and score > 0:
            best_score = score
            best_row = i

    if best_row is None or best_score < 3:
        raise ValueError(
            "Could not auto-detect a header row in the first "
            f"{n_scan} rows. First rows:\n{raw_df.head(n_scan)}"
        )
    return best_row


def load_bom_matrix(bom_file, sheet_name=None):
    """
    Returns (bom_df, header_row_index_0based, chosen_sheet_name).
    Auto-detects the header row instead of assuming row 0, and preserves
    every original column (no dropping of blank/spacer columns).
    """
    xl = pd.ExcelFile(bom_file)
    chosen_sheet = sheet_name or xl.sheet_names[0]

    raw = xl.parse(chosen_sheet, header=None)
    header_row = detect_header_row(raw)

    raw_headers = [
        f"Unnamed: {i}" if pd.isna(v) else str(v).strip()
        for i, v in enumerate(raw.iloc[header_row])
    ]
    columns = _dedupe_columns(raw_headers)
    data = raw.iloc[header_row + 1:].reset_index(drop=True)
    data.columns = columns
    data = data.dropna(how="all").reset_index(drop=True)

    return data, header_row, chosen_sheet


# ============================================================
# Step 2: ID-column alias detection
# ============================================================

def find_id_column(columns, aliases=ID_COLUMN_ALIASES, pattern=ID_COLUMN_PATTERN):
    """
    Alias/regex matcher for an FG/Assembly/CPN-style identifier column.
    Exact-alias match wins over pattern match; leftmost column wins ties.
    Raises ValueError if nothing matches (never guesses).
    """
    normalized = {c: _normalize_header(c) for c in columns}
    alias_set = {_normalize_header(a) for a in aliases}

    for c in columns:
        if normalized[c] in alias_set:
            return c

    for c in columns:
        if pattern.search(normalized[c]):
            return c

    raise ValueError(
        f"Could not detect an ID/FG column among columns: {list(columns)}"
    )


# ============================================================
# Step 3: Volume-column detection + volume-sheet selection
# ============================================================

def find_volume_columns(columns):
    """Returns matching column names in left-to-right sheet order."""
    return [c for c in columns if VOLUME_COLUMN_PATTERN.search(_normalize_header(c))]


def score_sheet_as_volume_sheet(df: pd.DataFrame) -> dict:
    """
    Scores a sheet's fitness as "the volume file" using both column-name
    matching AND data-shape checks (id uniqueness, volume-column fill
    ratio) -- the data-shape checks are what correctly reject a sheet
    whose columns are merely NAMED like volume columns but are mostly
    blank / keyed by a non-unique id (e.g. a decoy "VL 1"/"Vl2" pair
    embedded in a component-level BOM sheet).
    """
    try:
        id_col = find_id_column(list(df.columns))
    except ValueError:
        return {
            "qualifies": False, "id_col": None, "volume_cols": [],
            "reason": "no ID/FG column found",
        }

    volume_cols = find_volume_columns(list(df.columns))
    if not volume_cols:
        return {
            "qualifies": False, "id_col": id_col, "volume_cols": [],
            "reason": "no volume-like columns found",
        }

    ids = df[id_col].dropna().map(_normalize_id_value)
    id_unique_ratio = (ids.nunique() / len(ids)) if len(ids) else 0.0

    fill_ratios = [
        pd.to_numeric(df[vc], errors="coerce").notna().mean()
        for vc in volume_cols
    ]
    volume_fill_ratio = sum(fill_ratios) / len(fill_ratios) if fill_ratios else 0.0

    qualifies = (
        id_unique_ratio >= MIN_ID_UNIQUENESS_RATIO
        and volume_fill_ratio >= MIN_VOLUME_FILL_RATIO
    )

    reason = None
    if not qualifies:
        if id_unique_ratio < MIN_ID_UNIQUENESS_RATIO:
            reason = (
                f"id uniqueness {id_unique_ratio:.1%} < "
                f"{MIN_ID_UNIQUENESS_RATIO:.0%}"
            )
        else:
            reason = (
                f"volume fill ratio {volume_fill_ratio:.1%} < "
                f"{MIN_VOLUME_FILL_RATIO:.0%}"
            )

    return {
        "qualifies": qualifies,
        "id_col": id_col,
        "volume_cols": volume_cols,
        "id_unique_ratio": id_unique_ratio,
        "volume_fill_ratio": volume_fill_ratio,
        "reason": reason,
    }


def select_volume_sheet(volume_file, sheet_name=None):
    """
    Returns (chosen_sheet_name, chosen_df, chosen_score, rejections).
    Raises ValueError if zero or more than one sheet qualifies, rather
    than silently guessing.
    """
    xl = pd.ExcelFile(volume_file)
    candidate_names = [sheet_name] if sheet_name else xl.sheet_names

    candidates = {}
    for name in candidate_names:
        df = xl.parse(name, header=0)
        df.columns = df.columns.astype(str).str.strip()
        candidates[name] = (df, score_sheet_as_volume_sheet(df))

    qualifying = {n: s for n, (_, s) in candidates.items() if s["qualifies"]}

    if not qualifying:
        details = "; ".join(
            f"'{n}' rejected: {s['reason']}" for n, (_, s) in candidates.items()
        )
        raise ValueError(
            f"No sheet in '{volume_file}' qualifies as a volume file. {details}"
        )

    if len(qualifying) > 1:
        details = ", ".join(
            f"'{n}' (id_col={s['id_col']}, volume_cols={s['volume_cols']})"
            for n, s in qualifying.items()
        )
        raise ValueError(
            f"Multiple sheets in '{volume_file}' qualify as a volume sheet: "
            f"{details}. Pass volume_sheet_name explicitly to disambiguate."
        )

    chosen_name = next(iter(qualifying))
    chosen_df, chosen_score = candidates[chosen_name]
    rejections = [
        {"sheet": n, "reason": s["reason"]}
        for n, (_, s) in candidates.items()
        if n != chosen_name
    ]
    return chosen_name, chosen_df, chosen_score, rejections


def build_multi_volume_map(volume_df: pd.DataFrame, id_col: str, volume_cols: list):
    """
    Returns ({normalized_id: {orig_vol_col: numeric_value, ...}}, warnings).
    Non-numeric volume cells coerce to 0.0 with a collected warning;
    duplicate ids warn and use last-row-wins -- never raises.
    """
    volume_map = {}
    warnings = {"non_numeric_volume_cells": [], "duplicate_volume_ids": []}
    seen_ids = Counter()

    for _, row in volume_df.iterrows():
        raw_id = row[id_col]
        if pd.isna(raw_id):
            continue
        norm_id = _normalize_id_value(raw_id)
        seen_ids[norm_id] += 1
        if seen_ids[norm_id] > 1 and norm_id not in warnings["duplicate_volume_ids"]:
            warnings["duplicate_volume_ids"].append(norm_id)

        entry = {}
        for vc in volume_cols:
            raw_val = row[vc]
            coerced = pd.to_numeric(pd.Series([raw_val]), errors="coerce").iloc[0]
            if pd.notna(raw_val) and pd.isna(coerced):
                warnings["non_numeric_volume_cells"].append(
                    {"id": norm_id, "column": vc, "value": raw_val}
                )
            entry[vc] = 0.0 if pd.isna(coerced) else float(coerced)
        volume_map[norm_id] = entry

    return volume_map, warnings


# ============================================================
# Step 4: FG-column matching + weighted required-qty calculation
# ============================================================

def match_fg_columns(bom_columns, volume_map):
    """
    Matches BOM matrix COLUMN HEADERS against volume_map keys (the FGs),
    normalized for whitespace/case. Returns:
      matched_columns: {normalized_id: original_bom_column_name}
      unmatched_in_volume: [normalized_id, ...] present in the volume
                            file with no matching BOM column
      unmatched_in_bom: [] (reserved; the BOM matrix has no independent
                            FG list beyond its own columns)
      duplicate_bom_fg_columns: columns that collide after normalization
                                 (first occurrence used, rest ignored)
    """
    normalized_to_originals = {}
    for c in bom_columns:
        normalized_to_originals.setdefault(_normalize_id_value(c), []).append(c)

    matched_columns = {}
    duplicate_bom_fg_columns = []
    for norm, originals in normalized_to_originals.items():
        if norm not in volume_map:
            continue
        if len(originals) > 1:
            duplicate_bom_fg_columns.append({"normalized": norm, "originals": originals})
        matched_columns[norm] = originals[0]

    unmatched_in_volume = [fg for fg in volume_map if fg not in normalized_to_originals]
    unmatched_in_bom = []

    return matched_columns, unmatched_in_volume, unmatched_in_bom, duplicate_bom_fg_columns


def compute_required_qty_columns(bom_df, matched_columns, volume_map, volume_cols_ordered):
    """
    Appends Required_Qty_V1, Required_Qty_V2, ... at the end of bom_df,
    one per volume scenario in volume_cols_ordered (source order, not
    literal spelling). Never touches any existing column. NaN cells in a
    matched FG column are treated as 0 before multiplying.
    """
    output_names = []
    for i, orig_vol_col in enumerate(volume_cols_ordered, start=1):
        out_name = f"Required_Qty_V{i}"
        if out_name in bom_df.columns:
            raise ValueError(
                f"Cannot append column '{out_name}': a column with that "
                "name already exists in the BOM file."
            )
        output_names.append(out_name)

        accumulator = pd.Series(0.0, index=bom_df.index)
        for norm_id, bom_col in matched_columns.items():
            cell_values = pd.to_numeric(bom_df[bom_col], errors="coerce").fillna(0)
            vol_value = volume_map[norm_id].get(orig_vol_col, 0.0)
            accumulator = accumulator + (cell_values * vol_value)
        bom_df[out_name] = accumulator

    return bom_df, output_names


# ============================================================
# Step 5: Top-level orchestration + report
# ============================================================

def enrich_bom_with_volume(bom_file, volume_file, bom_sheet_name=None,
                            volume_sheet_name=None, output_file=None):
    bom_file = Path(bom_file)
    volume_file = Path(volume_file)

    bom_df, header_row_idx, chosen_bom_sheet = load_bom_matrix(bom_file, bom_sheet_name)

    try:
        bom_id_col = find_id_column(list(bom_df.columns))
    except ValueError:
        bom_id_col = None

    vol_sheet_name, volume_df, vol_score, vol_rejections = select_volume_sheet(
        volume_file, volume_sheet_name
    )
    id_col = vol_score["id_col"]
    volume_cols_ordered = vol_score["volume_cols"]

    volume_map, vol_warnings = build_multi_volume_map(volume_df, id_col, volume_cols_ordered)

    matched_columns, unmatched_in_volume, unmatched_in_bom, dup_bom_fg = match_fg_columns(
        list(bom_df.columns), volume_map
    )

    result_df, output_names = compute_required_qty_columns(
        bom_df, matched_columns, volume_map, volume_cols_ordered
    )

    if output_file is None:
        output_file = bom_file.with_name(f"{bom_file.stem}_with_required_qty.xlsx")
    else:
        output_file = Path(output_file)

    result_df.to_excel(output_file, index=False)

    return {
        "bom_file": bom_file.name,
        "bom_sheet": chosen_bom_sheet,
        "bom_header_row_1idx": header_row_idx + 1,
        "bom_rows_read": len(bom_df),
        "bom_id_column": bom_id_col,
        "volume_file": volume_file.name,
        "volume_sheet_selected": vol_sheet_name,
        "volume_sheet_rejections": vol_rejections,
        "volume_rows_read": len(volume_df),
        "volume_id_column": id_col,
        "volume_columns_ordered": volume_cols_ordered,
        "output_column_names": output_names,
        "fg_columns_matched": list(matched_columns.values()),
        "fg_match_count": len(matched_columns),
        "fg_total_count": len(volume_map),
        "warnings": {
            "unmatched_in_volume": unmatched_in_volume,
            "unmatched_in_bom": unmatched_in_bom,
            "non_numeric_volume_cells": vol_warnings["non_numeric_volume_cells"],
            "duplicate_volume_ids": vol_warnings["duplicate_volume_ids"],
            "duplicate_bom_fg_columns": dup_bom_fg,
        },
        "final_row_count": len(result_df),
        "output_file": str(output_file),
    }


def print_report(report: dict) -> None:
    SEP = "-" * 48
    print(SEP)
    print("Matrix BOM Volume Enrichment - Validation Report")
    print(SEP)
    print(f"BOM file                 : {report['bom_file']}")
    print(f"BOM sheet                : {report['bom_sheet']}")
    print(f"BOM header row (1-idx)   : {report['bom_header_row_1idx']}")
    print(f"BOM rows read            : {report['bom_rows_read']}")
    print(f"Detected BOM mapping col : {report['bom_id_column'] or 'N/A (FGs are BOM columns, not a row field)'}")
    print()
    print(f"Volume file              : {report['volume_file']}")
    print(f"Volume sheet selected    : {report['volume_sheet_selected']}")
    for rej in report["volume_sheet_rejections"]:
        print(f"  (rejected: '{rej['sheet']}' - {rej['reason']})")
    print(f"Volume rows read         : {report['volume_rows_read']}")
    print(f"Detected volume mapping column : {report['volume_id_column']}")
    print()
    print("Volume columns detected (in order):")
    for i, (orig, out) in enumerate(
        zip(report["volume_columns_ordered"], report["output_column_names"]), start=1
    ):
        print(f"  {i}. {orig} -> {out}")
    print()
    print(
        f"FG columns matched (BOM <-> Volume): "
        f"{report['fg_match_count']} / {report['fg_total_count']}"
    )
    for c in report["fg_columns_matched"]:
        print(f"  {c}")
    print()
    w = report["warnings"]
    print("Warnings:")
    print(f"  - unmatched FGs in volume file (no BOM column): {w['unmatched_in_volume'] or 'none'}")
    print(f"  - unmatched FG columns in BOM (no volume entry): {w['unmatched_in_bom'] or 'none'}")
    print(f"  - non-numeric volume cells coerced to 0: {w['non_numeric_volume_cells'] or 'none'}")
    print(f"  - duplicate ID keys in volume file: {w['duplicate_volume_ids'] or 'none'}")
    print(f"  - duplicate FG columns in BOM matrix: {w['duplicate_bom_fg_columns'] or 'none'}")
    print()
    print(f"Required-quantity columns created : {', '.join(report['output_column_names'])}")
    print(f"Final output row count            : {report['final_row_count']}")
    print(f"Output written to                 : {report['output_file']}")
    print(SEP)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python matrix_bom_volume_enrichment.py "
            "<consolidated_bom.xlsx> <volume.xlsx> [output.xlsx]"
        )
        sys.exit(1)

    _bom_file = sys.argv[1].strip().strip('"')
    _volume_file = sys.argv[2].strip().strip('"')
    _output_file = sys.argv[3].strip().strip('"') if len(sys.argv) >= 4 else None

    try:
        _report = enrich_bom_with_volume(_bom_file, _volume_file, output_file=_output_file)
        print_report(_report)
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    sys.exit(0)
