import json
import re

import llm_mapping
import pandas as pd


# ==========================================================
# WORKBOOK SHEET NAMES
#
# A SCRUB BOM file is a single workbook with three sheets, mapping to
# three DuckDB tables: SCRUB BOM -> scrub_bom_items, Settings -> volume,
# Batch -> batch.
# ==========================================================

SHEET_SCRUB_BOM = "SCRUB BOM"
SHEET_SETTINGS = "Settings"
SHEET_BATCH = "Batch"


# ==========================================================
# CANONICAL SCHEMA — SCRUB BOM
#
# Target for the scrub_bom_items table. Standardization only: no volume
# expansion, no consolidation, no duplicate-CPN detection — those are
# out of scope for the SCRUB BOM pipeline.
# ==========================================================

SCRUB_BOM_TEMPLATE_HEADERS = [
    "fg",
    "level",
    "assembly",

    "cpn",
    "description",
    "manufacturer",
    "mpn",

    "commodity",

    "quantity",
    "unit_of_measure",

    "part_status",
    "ce_remarks",
    "drawing_reference",
    "designators",
    "item_number",
    "part_type",
    "ltb_date",
    "common_aml",
    "change_remarks",
    "inventory_stock",
    "exported_at"
]


# ==========================================================
# LLM SCHEMA MAPPING
# ==========================================================

def semantic_mapping_scrub(headers):

    system_prompt = """
You are a SCRUB BOM schema mapping engine.

Rules:

1. Output ALL predefined schema fields.
2. JSON key must be predefined schema field.
3. Value must be matching incoming header.
4. Use null when no confident match exists.
5. Never guess.
6. Return JSON only.
7. Accuracy is more important than coverage.
"""

    user_prompt = f"""
Predefined Schema:

{SCRUB_BOM_TEMPLATE_HEADERS}

Incoming Headers:

{headers}

Return JSON only.

Example:

{{
    "mpn": "Manufacturer Part Number",
    "description": "Part Description",
    "commodity": null
}}
"""

    response = llm_mapping.chat(
        model="qwen2.5-coder:7b",
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        format="json",
        required=("cpn", "mpn", "quantity"),
    )

    mapping = json.loads(
        response["message"]["content"]
    )

    final_mapping = {}

    for col in SCRUB_BOM_TEMPLATE_HEADERS:
        final_mapping[col] = mapping.get(col)

    return final_mapping


# ==========================================================
# STANDARDIZATION
# ==========================================================

def _coerce_item_number(value):
    """item_number is stored as VARCHAR in scrub_bom_items -- it is a free-form
    identifier, not a numeric line count. Real Scrub BOM exports confirm it can be
    genuine free text ('F/N: 0070 _ 1', '10, 20', 'MCL for MPN', '149 A/R',
    '0001_PN_B') or a large, non-item-number-shaped value that's actually a real CPN
    (confirmed on real data, RFQ-000015: 5010980138 -- this was previously nulled out
    by an INT32-range check, which was wrong; item_number must preserve whatever value
    is present, whatever its shape, not just small line numbers). The column used to
    be INTEGER, which crashed the whole insert outright on any of the above ("value is
    out of range for the destination type INT32" / "Could not convert string ... to
    INT32") -- one anomalous cell in one row dropped every row for the file. VARCHAR
    has no such failure mode, so this now only normalizes representation (no
    extraction, no truncation, no range check): NaN/None -> None, a whole-number float
    (e.g. 5010980138.0, however it arrived from Excel) -> its clean integer string
    (avoiding a trailing ".0"), anything else -> str(value) unchanged.
    """
    if pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


_MAX_HIERARCHY_DEPTH = 64  # backstop, not expected to trigger -- real data reaches L8


def _build_hierarchy_multipliers(df):
    """Confirmed real-data bug (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md): every FG-wide
    quantity roll-up in this codebase (BOM MATRIX, CBOM VL's "FG Part Qty", A Class Parts,
    Sum & Count, Summary) was a flat sum of each row's own LOCAL `quantity`, never
    multiplied by how many times the row's own parent sub-assembly is itself used. When a
    sub-assembly is used N times, every part inside it is under-counted by that factor
    (confirmed: part LM1785-061226-001 should be 3 for one FG, flat-summed to 2 -- 75 of
    243 parts on that FG alone were wrong).

    Returns a Series aligned to df.index: this row's own cumulative ancestor multiplier --
    the product of every ancestor sub-assembly's own local qty, walking from this row's
    `assembly` value up to the FG root (where cpn == fg == assembly). Always >= 1 (a row
    at the FG root, or whose assembly chain terminates without reaching a parent, gets 1 --
    a no-op multiplier, not a dropped row).

    A structural line's CPN is one that is itself used as an `assembly` value somewhere in
    the same FG (excluding the FG's own self-referencing root row via `cpn != assembly`).
    parent_of is a flat (fg, assembly_cpn) -> (parent_assembly, qty) dict -- confirmed safe
    against real data (direct scan of the actual validation file): no assembly-role CPN
    ever has more than one distinct parent within the same FG. Leaf parts CAN repeat under
    different parents (the bug's own example: LM1785-061226-001 under two different
    sub-assemblies) -- that's fine, since the multiplier is walked from THIS ROW's own
    `assembly` value, never via a CPN-keyed lookup for leaves.

    Cycle guard (`seen`, per walk) is required, not optional -- malformed BOMs with a
    circular assembly reference exist in principle even if not in today's real data; a
    depth backstop (_MAX_HIERARCHY_DEPTH) additionally guards a long-but-non-cyclic chain.
    Null/blank quantity on a structural line is treated as 1 (a bare "this sub-assembly
    exists" with no stated multiplier shouldn't zero out everything beneath it).
    """
    assemblies = set(zip(df["fg"], df["assembly"]))
    parent_of = {}
    for fg, assembly, cpn, qty in zip(df["fg"], df["assembly"], df["cpn"], df["quantity"]):
        if (fg, cpn) in assemblies and cpn != assembly:
            parent_of.setdefault((fg, cpn), (assembly, qty))

    cache = {}

    def multiplier(fg, assembly):
        key = (fg, assembly)
        if key in cache:
            return cache[key]
        m, seen, node, depth = 1.0, set(), assembly, 0
        while node != fg and (fg, node) in parent_of and node not in seen and depth < _MAX_HIERARCHY_DEPTH:
            seen.add(node)
            parent, qty = parent_of[(fg, node)]
            m *= qty if qty is not None and not pd.isna(qty) else 1.0
            node = parent
            depth += 1
        cache[key] = m
        return m

    return pd.Series(
        [multiplier(fg, assembly) for fg, assembly in zip(df["fg"], df["assembly"])],
        index=df.index,
    )


def _coerce_ltb_date(series):
    """ltb_date is stored as DATE, but arrives as a DD-MM-YYYY (or similar non-ISO)
    string -- DuckDB's DATE cast only accepts ISO YYYY-MM-DD and rejects everything else
    outright (confirmed on real data: '31-12-2026', '30-09-2021', '20-06-2022'). Mirrors
    quote_win_processing.py's eff_date/exp_date handling: try the observed primary format
    first, then fall back to a general dayfirst parse for anything that doesn't match
    (other separators, 2-digit years, etc.) instead of erroring.
    """
    parsed = pd.to_datetime(series, format="%d-%m-%Y", errors="coerce")
    unparsed = parsed.isna() & series.notna()
    if unparsed.any():
        parsed[unparsed] = pd.to_datetime(series[unparsed], dayfirst=True, errors="coerce")
    return parsed.dt.date


def standardize_scrub_bom(df, mapping):

    rename_dict = {}
    claimed_sources = set()

    for target_col in SCRUB_BOM_TEMPLATE_HEADERS:

        source_col = mapping.get(target_col)

        if (
            source_col is not None
            and source_col in df.columns
            and source_col not in claimed_sources
        ):
            rename_dict[source_col] = target_col
            claimed_sources.add(source_col)

    standardized_df = df.rename(
        columns=rename_dict
    )

    for col in SCRUB_BOM_TEMPLATE_HEADERS:

        if col not in standardized_df.columns:
            standardized_df[col] = None

    standardized_df = standardized_df[
        SCRUB_BOM_TEMPLATE_HEADERS
    ]

    standardized_df["item_number"] = standardized_df["item_number"].apply(_coerce_item_number)
    standardized_df["ltb_date"] = _coerce_ltb_date(standardized_df["ltb_date"])
    standardized_df["hierarchy_multiplier"] = _build_hierarchy_multipliers(standardized_df)

    return standardized_df


# ==========================================================
# MAIN PROCESSOR
# ==========================================================

def process_scrub_bom(bom_file, sheet_name=0):

    print("\nLoading SCRUB BOM...")

    bom_df = pd.read_excel(
        bom_file,
        sheet_name=sheet_name
    )

    bom_df.columns = (
        bom_df.columns
        .astype(str)
        .str.strip()
    )

    original_rows = len(bom_df)

    headers = list(
        bom_df.columns
    )

    # ======================================================
    # LLM HEADER MAPPING
    # ======================================================

    print(
        "\nRunning SCRUB BOM schema mapping..."
    )

    mapping = semantic_mapping_scrub(
        headers
    )

    # ======================================================
    # FORCE CRITICAL MAPPINGS
    #
    # Dry-run testing (15 repeated semantic_mapping_scrub() calls against
    # the same real headers) showed these fields mapped inconsistently:
    # drawing_reference (14/15 null), part_status (5/15 null), commodity
    # (2/15 null), and quantity (1/15 null — but quantity is a required
    # field, so even a single miss aborts the whole run). Forced
    # deterministically over the LLM's guess when the header is present
    # verbatim — same treatment previously used for CPN <- UBR Number.
    # ======================================================

    header_lookup = {
        str(col).strip().upper(): col
        for col in bom_df.columns
    }

    critical_overrides = {
        "cpn": "CPN",
        "mpn": "MPN",
        "quantity": "QUANTITY",
        "commodity": "COMMODITY",
        "part_status": "PART STATUS",
        "drawing_reference": "DRAWING REFERENCE",
    }

    for canonical, actual in critical_overrides.items():

        if actual in header_lookup:

            mapping[canonical] = (
                header_lookup[actual]
            )

    # ======================================================
    # VALIDATION
    # ======================================================

    required_fields = [
        "cpn",
        "mpn",
        "quantity"
    ]

    # A mapping that names a header the sheet does not have leaves the column empty without an error,
    # so a required field counts as missing unless its source header is really in the sheet.
    missing = [
        field
        for field in required_fields
        if mapping.get(field) not in bom_df.columns
    ]

    if missing:

        raise ValueError(
            f"Missing critical mappings: "
            f"{missing}"
        )

    print(
        "\n===================================="
    )
    print("SCRUB BOM SCHEMA MAPPING")
    print(
        "===================================="
    )

    for target, source in mapping.items():

        print(
            f"{target:<20}"
            f" -> "
            f"{source}"
        )

    print(
        "====================================\n"
    )

    # ======================================================
    # STANDARDIZE
    # ======================================================

    standardized_df = (
        standardize_scrub_bom(
            bom_df,
            mapping
        )
    )

    print(
        "\n===================================="
    )
    print("SCRUB BOM STANDARDIZATION SUMMARY")
    print(
        "===================================="
    )
    print(f"Original SCRUB BOM rows:    {original_rows}")
    print(f"Standardized rows:          {len(standardized_df)}")
    print(
        "====================================\n"
    )

    return standardized_df


# ==========================================================
# VOLUME (Settings sheet) & BATCH SHEET PROCESSING
#
# Both sheets are wide-format: one FG per row, followed by one column
# per volume scenario (e.g. "V1 Qty", "V2 Qty" / "V1 Batch Qty",
# "V2 Batch Qty"). The target tables (volume, batch) are long-format —
# one row per (fg, scenario) pair — so every non-FG column is melted
# into its own row. The number of scenario columns is not fixed (V1,
# V2, V3, ...), so all non-FG columns are melted rather than a hardcoded
# count.
# ==========================================================

_VOLUME_QTY_SUFFIX_RE = re.compile(r"\s*Qty\s*$", re.IGNORECASE)
_BATCH_QTY_SUFFIX_RE = re.compile(r"\s*Batch\s*Qty\s*$", re.IGNORECASE)


def _coerce_numeric(series):
    """batch_qty is stored as DOUBLE in both the volume and batch tables, but a stray
    leading/trailing space in the source Excel cell (confirmed on real data: ' 750')
    makes DuckDB's VARCHAR->DOUBLE cast fail outright rather than trimming and parsing
    the number. Strips whitespace and coerces via pandas first so the DB insert always
    receives a real float (or NULL, for genuinely non-numeric values) instead of a raw
    string.
    """
    return pd.to_numeric(series.astype(str).str.strip(), errors="coerce")


def _find_fg_column(columns):

    for col in columns:
        if str(col).strip().upper() == "FG":
            return col

    raise ValueError(
        f"Could not find an 'FG' column. Available columns: {list(columns)}"
    )


def _value_columns(columns, fg_col):
    """The quantity columns: every column but FG that has a real header. pandas names a column with a blank header
    'Unnamed: N'; found 2026-11-18 (batch-04 Settings: a stray 21.33 in E3, no header, no FG) it became volume
    'Unnamed: 4' and the export failed on it."""
    return [c for c in columns if c != fg_col and c and not c.startswith("Unnamed:") and c.lower() not in ("nan", "none")]


def _has_fg(value):
    return not (value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "")


def process_volume_sheet(volume_df):

    volume_df = volume_df.copy()
    volume_df.columns = volume_df.columns.astype(str).str.strip()

    fg_col = _find_fg_column(volume_df.columns)
    value_cols = _value_columns(volume_df.columns, fg_col)

    if not value_cols:
        raise ValueError(
            "Settings sheet has no volume quantity columns besides FG."
        )

    rows = []

    for _, row in volume_df.iterrows():

        fg = row[fg_col]
        if not _has_fg(fg):
            continue  # a row without an assembly cannot carry a quantity for one

        for col in value_cols:

            volume_name = _VOLUME_QTY_SUFFIX_RE.sub("", col).strip() or col

            rows.append({
                "fg": fg,
                "volume_name": volume_name,
                "batch_qty": row[col]
            })

    result = pd.DataFrame(
        rows,
        columns=["fg", "volume_name", "batch_qty"]
    )
    result["batch_qty"] = _coerce_numeric(result["batch_qty"])
    return result


def process_batch_sheet(batch_df):

    batch_df = batch_df.copy()
    batch_df.columns = batch_df.columns.astype(str).str.strip()

    fg_col = _find_fg_column(batch_df.columns)
    value_cols = _value_columns(batch_df.columns, fg_col)

    if not value_cols:
        raise ValueError(
            "Batch sheet has no batch quantity columns besides FG."
        )

    rows = []

    for _, row in batch_df.iterrows():

        fg = row[fg_col]
        if not _has_fg(fg):
            continue  # a row without an assembly cannot carry a quantity for one

        for col in value_cols:

            volume_label = _BATCH_QTY_SUFFIX_RE.sub("", col).strip() or col

            rows.append({
                "fg": fg,
                "volume": volume_label,
                "batch_qty": row[col]
            })

    result = pd.DataFrame(
        rows,
        columns=["fg", "volume", "batch_qty"]
    )
    result["batch_qty"] = _coerce_numeric(result["batch_qty"])
    return result


# ==========================================================
# WORKBOOK ORCHESTRATOR
#
# Reads all three sheets from a single SCRUB BOM workbook and returns
# their standardized DataFrames, keyed by target table name.
# ==========================================================

def _resolve_sheet_name(file_path, expected_name, required=True):

    # pd.ExcelFile keeps the underlying file handle open until closed
    # explicitly -- unlike pd.read_excel(path), which opens/closes internally
    # per call. On Windows that handle is an OS-level lock, so leaving this
    # unclosed (as it was before) meant every uploaded BOM stayed locked on
    # disk indefinitely after processing, blocking any later cleanup/delete.
    with pd.ExcelFile(file_path) as workbook:
        sheet_names = workbook.sheet_names

        for name in sheet_names:
            if name.strip().upper() == expected_name.strip().upper():
                return name

        if not required:
            return None

        raise ValueError(
            f"Could not find a sheet named '{expected_name}' in {file_path}. "
            f"Available sheets: {sheet_names}"
        )


def process_scrub_bom_workbook(file_path):

    # Settings/Batch are the FG-volume-quantity sheets -- some real Scrub BOM exports
    # (confirmed: a Thales export using a completely different template -- 'CPN vs QTY',
    # 'MPN vs CPN', 'SUM & COUNT', 'SUMMARY', 'Revision History' -- with no equivalent of
    # either sheet at all) omit them entirely. The 'SCRUB BOM' sheet itself (the actual
    # line-item data) is still required -- there's no reasonable fallback for that -- but
    # missing volume/batch data degrades to "no configured volumes", which
    # queries.detect_volumes() already handles by falling back to a single implicit
    # volume, rather than failing the whole upload over data this file just doesn't have.
    scrub_sheet = _resolve_sheet_name(file_path, SHEET_SCRUB_BOM)
    settings_sheet = _resolve_sheet_name(file_path, SHEET_SETTINGS, required=False)
    batch_sheet = _resolve_sheet_name(file_path, SHEET_BATCH, required=False)

    standardized_scrub_df = process_scrub_bom(
        file_path,
        sheet_name=scrub_sheet
    )

    if settings_sheet is not None:
        settings_raw_df = pd.read_excel(file_path, sheet_name=settings_sheet)
        volume_df = process_volume_sheet(settings_raw_df)
    else:
        volume_df = pd.DataFrame(columns=["fg", "volume_name", "batch_qty"])

    if batch_sheet is not None:
        batch_raw_df = pd.read_excel(file_path, sheet_name=batch_sheet)
        batch_df = process_batch_sheet(batch_raw_df)
    else:
        batch_df = pd.DataFrame(columns=["fg", "volume", "batch_qty"])

    return {
        "scrub_bom": standardized_scrub_df,
        "volume": volume_df,
        "batch": batch_df
    }


# ==========================================================
# ENTRYPOINT
# ==========================================================

if __name__ == "__main__":

    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  python scrub_bom_processing.py "
            "<scrub_bom.xlsx> [output.xlsx]"
        )
        sys.exit(1)

    _bom_file = sys.argv[1].strip().strip('"')
    _output_file = (
        sys.argv[2].strip().strip('"')
        if len(sys.argv) >= 3
        else "standardized_scrub_bom.xlsx"
    )

    if not Path(_bom_file).exists():
        print(f"ERROR: File not found: {_bom_file}")
        sys.exit(1)

    _standardized_df = process_scrub_bom(_bom_file)

    _standardized_df.to_excel(_output_file, index=False)

    print(f"Done.\nOutput written to: {_output_file}")
