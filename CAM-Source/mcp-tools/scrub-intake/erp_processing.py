import json

import llm_mapping
import pandas as pd


# ==========================================================
# CANONICAL SCHEMA — ERP
#
# Target for the erp table. Standardization only. id and imported_at
# are DB-generated (UUID DEFAULT / CURRENT_TIMESTAMP) and are never
# present in the incoming file, so they are excluded from this schema.
# ==========================================================

ERP_TEMPLATE_HEADERS = [
    "mpn",
    "mfr",
    "quantity",
    "uom",
    "last_purchase_price",
    "currency",
    "supplier_name",
    "in_stock_qty",
    "reserved_qty",
    "available_qty",
    "last_po_number",
    "last_po_date",
    "notes",
]


# ==========================================================
# LLM SCHEMA MAPPING
# ==========================================================

def semantic_mapping_erp(headers):

    system_prompt = """
You are an ERP schema mapping engine.

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

{ERP_TEMPLATE_HEADERS}

Incoming Headers:

{headers}

Return JSON only.

Example:

{{
    "mpn": "MPN",
    "mfr": "Manufacturer",
    "last_purchase_price": "Last PO Price"
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
        required=("mpn", "mfr", "quantity", "uom", "last_purchase_price", "currency", "in_stock_qty", "reserved_qty", "available_qty"),
    )

    mapping = json.loads(
        response["message"]["content"]
    )

    final_mapping = {}

    for col in ERP_TEMPLATE_HEADERS:
        final_mapping[col] = mapping.get(col)

    return final_mapping


# ==========================================================
# STANDARDIZATION
# ==========================================================

def standardize_erp(df, mapping):

    rename_dict = {}
    claimed_sources = set()

    for target_col in ERP_TEMPLATE_HEADERS:

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

    for col in ERP_TEMPLATE_HEADERS:

        if col not in standardized_df.columns:
            standardized_df[col] = None

    standardized_df = standardized_df[
        ERP_TEMPLATE_HEADERS
    ]

    # last_po_date arrives as a "DD/MM/YY" string — parse to a real date
    # so it casts cleanly into the erp table's DATE column. Explicit
    # format avoids pandas' per-row dateutil fallback (slow and emits a
    # UserWarning); any value that doesn't match falls back to a generic
    # dayfirst parse.
    parsed = pd.to_datetime(
        standardized_df["last_po_date"],
        format="%d/%m/%y",
        errors="coerce"
    )

    unparsed = parsed.isna() & standardized_df["last_po_date"].notna()

    if unparsed.any():
        parsed[unparsed] = pd.to_datetime(
            standardized_df.loc[unparsed, "last_po_date"],
            dayfirst=True,
            errors="coerce"
        )

    standardized_df["last_po_date"] = parsed.dt.date

    return standardized_df


# ==========================================================
# MAIN PROCESSOR
# ==========================================================

def process_erp(file_path, sheet_name=0):

    print("\nLoading ERP export...")

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
        "\nRunning ERP schema mapping..."
    )

    mapping = semantic_mapping_erp(
        headers
    )

    # ======================================================
    # VALIDATION
    #
    # Mirrors the erp table's NOT NULL columns (everything except
    # supplier_name, last_po_number, last_po_date, and notes).
    # ======================================================

    required_fields = [
        "mpn",
        "mfr",
        "quantity",
        "uom",
        "last_purchase_price",
        "currency",
        "in_stock_qty",
        "reserved_qty",
        "available_qty",
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
    print("ERP SCHEMA MAPPING")
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
        standardize_erp(
            raw_df,
            mapping
        )
    )

    print(
        "\n===================================="
    )
    print("ERP STANDARDIZATION SUMMARY")
    print(
        "===================================="
    )
    print(f"Original ERP rows:          {original_rows}")
    print(f"Standardized rows:          {len(standardized_df)}")
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
            "  python erp_processing.py "
            "<erp.xlsx> [output.xlsx]"
        )
        sys.exit(1)

    _erp_file = sys.argv[1].strip().strip('"')
    _output_file = (
        sys.argv[2].strip().strip('"')
        if len(sys.argv) >= 3
        else "standardized_erp.xlsx"
    )

    if not Path(_erp_file).exists():
        print(f"ERROR: File not found: {_erp_file}")
        sys.exit(1)

    _standardized_df = process_erp(_erp_file)

    _standardized_df.to_excel(_output_file, index=False)

    print(f"Done.\nOutput written to: {_output_file}")
