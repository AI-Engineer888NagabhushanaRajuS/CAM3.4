import json

import llm_mapping
import pandas as pd


# ==========================================================
# CANONICAL SCHEMA — COSTING SHEET
#
# Target for the costing_sheet table. Standardization only. rfq_id is
# added by the database layer and is never present in the incoming
# file, so it is excluded from this schema.
# ==========================================================

COSTING_SHEET_TEMPLATE_HEADERS = [
    "assembly",
    "part_number",
    "description",
    "commodity",
    "mfg_name",
    "mfg_part_number",
    "unit",
    "part_qty",
    "price_original",
    "currency_original",
    "supp_name",
    "pkg_qty",
    "moq",
    "lead_time",
    "nre_charge",
    "nre_charge_conv",
    "ncnr",
    "price_control",
    "price_type",
    "exp_date",
    "long_comment",
]


# ==========================================================
# LLM SCHEMA MAPPING
# ==========================================================

def semantic_mapping_costing_sheet(headers):

    system_prompt = """
You are a COSTING SHEET schema mapping engine.

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

{COSTING_SHEET_TEMPLATE_HEADERS}

Incoming Headers:

{headers}

Return JSON only.

Example:

{{
    "part_number": "Part Number",
    "mfg_part_number": "Mfg Part Number",
    "commodity": "Commodity"
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
        required=("part_number", "mfg_part_number"),
    )

    mapping = json.loads(
        response["message"]["content"]
    )

    final_mapping = {}

    for col in COSTING_SHEET_TEMPLATE_HEADERS:
        final_mapping[col] = mapping.get(col)

    return final_mapping


# ==========================================================
# STANDARDIZATION
# ==========================================================

def _excel_serial_to_date(value):
    """Some Costing Sheet exports carry exp_date as a bare Excel serial date number
    (days since 1899-12-30) instead of a "DD/MM/YY" string -- confirmed on real data:
    the classic symptom is a near-1970 garbage timestamp (e.g. '46196 ns' past epoch),
    which is exactly what you get when a genuine serial number like 46196 (a real date,
    ~2026) is fed straight into the string-based dayfirst parser below and misread as
    nanoseconds-since-epoch instead of days-since-1899-12-30. Converts those numeric
    values up front via the standard Excel-serial formula; leaves anything else (real
    date strings, already-parsed datetime/date objects, NaN) untouched for the existing
    parsing below to handle.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or pd.isna(value):
        return value
    return pd.to_datetime(value, unit="D", origin="1899-12-30").date()


def standardize_costing_sheet(df, mapping):

    rename_dict = {}
    claimed_sources = set()

    for target_col in COSTING_SHEET_TEMPLATE_HEADERS:

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

    for col in COSTING_SHEET_TEMPLATE_HEADERS:

        if col not in standardized_df.columns:
            standardized_df[col] = None

    standardized_df = standardized_df[
        COSTING_SHEET_TEMPLATE_HEADERS
    ]

    # exp_date arrives as a "DD/MM/YY" string — parse to a real date so
    # it casts cleanly into the costing_sheet table's DATE column.
    # Explicit format avoids pandas' per-row dateutil fallback (slow and
    # emits a UserWarning); any value that doesn't match falls back to a
    # generic dayfirst parse. Raw Excel serial date numbers are converted
    # up front (see _excel_serial_to_date()) since they aren't valid input
    # for either the format-string or dayfirst string parsers below.
    standardized_df["exp_date"] = standardized_df["exp_date"].apply(_excel_serial_to_date)

    parsed = pd.to_datetime(
        standardized_df["exp_date"],
        format="%d/%m/%y",
        errors="coerce"
    )

    unparsed = parsed.isna() & standardized_df["exp_date"].notna()

    if unparsed.any():
        parsed[unparsed] = pd.to_datetime(
            standardized_df.loc[unparsed, "exp_date"],
            dayfirst=True,
            errors="coerce"
        )

    standardized_df["exp_date"] = parsed.dt.date

    return standardized_df


# ==========================================================
# MAIN PROCESSOR
# ==========================================================

def process_costing_sheet(file_path, sheet_name=0):

    print("\nLoading COSTING SHEET...")

    raw_df = pd.read_excel(
        file_path,
        sheet_name=sheet_name
    )

    raw_df.columns = (
        raw_df.columns
        .astype(str)
        .str.strip()
    )

    original_rows = len(raw_df)

    headers = list(
        raw_df.columns
    )

    # ======================================================
    # LLM HEADER MAPPING
    # ======================================================

    print(
        "\nRunning COSTING SHEET schema mapping..."
    )

    mapping = semantic_mapping_costing_sheet(
        headers
    )

    # ======================================================
    # FORCE CRITICAL MAPPINGS
    #
    # Repeated runs against the same real "005570 Costing sheet.xlsx"
    # headers showed ncnr, price_control, and price_type each mapped
    # inconsistently (null on one run, correctly matched on the next)
    # even though the exact-named column is present verbatim — same
    # flakiness previously observed for quote_win. Forced
    # deterministically over the LLM's guess when the header is present
    # verbatim.
    # ======================================================

    header_lookup = {
        str(col).strip().upper(): col
        for col in raw_df.columns
    }

    critical_overrides = {
        "ncnr": "NCNR",
        "price_control": "PRICE CONTROL",
        "price_type": "PRICE TYPE",
    }

    for canonical, actual in critical_overrides.items():

        if actual in header_lookup:

            mapping[canonical] = (
                header_lookup[actual]
            )

    # assembly has no reliable header text to match on — real exports
    # have shown it as a bare "1" or as "Project " depending on sheet,
    # neither of which the LLM can safely tie to "assembly". It is
    # consistently the first column of the sheet, so force it
    # positionally whenever the LLM left it unmapped.
    if mapping.get("assembly") is None and len(raw_df.columns) > 0:

        mapping["assembly"] = raw_df.columns[0]

    # ======================================================
    # VALIDATION
    # ======================================================

    required_fields = [
        "part_number",
        "mfg_part_number"
    ]

    missing = [
        field
        for field in required_fields
        if mapping.get(field) is None
    ]

    if missing:

        raise ValueError(
            f"Missing critical mappings: "
            f"{missing}"
        )

    print(
        "\n===================================="
    )
    print("COSTING SHEET SCHEMA MAPPING")
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
        standardize_costing_sheet(
            raw_df,
            mapping
        )
    )

    print(
        "\n===================================="
    )
    print("COSTING SHEET STANDARDIZATION SUMMARY")
    print(
        "===================================="
    )
    print(f"Original COSTING SHEET rows: {original_rows}")
    print(f"Standardized rows:            {len(standardized_df)}")
    print(
        "====================================\n"
    )

    return standardized_df


# ==========================================================
# ENTRYPOINT
# ==========================================================

if __name__ == "__main__":

    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  python costing_sheet_processing.py "
            "<costing_sheet.xlsx> [output.xlsx]"
        )
        sys.exit(1)

    _costing_sheet_file = sys.argv[1].strip().strip('"')
    _output_file = (
        sys.argv[2].strip().strip('"')
        if len(sys.argv) >= 3
        else "standardized_costing_sheet.xlsx"
    )

    if not Path(_costing_sheet_file).exists():
        print(f"ERROR: File not found: {_costing_sheet_file}")
        sys.exit(1)

    _standardized_df = process_costing_sheet(_costing_sheet_file)

    _standardized_df.to_excel(_output_file, index=False)

    print(f"Done.\nOutput written to: {_output_file}")
