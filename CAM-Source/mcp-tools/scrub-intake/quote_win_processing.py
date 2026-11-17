import datetime
import json
import re

import llm_mapping
import pandas as pd


# ==========================================================
# CANONICAL SCHEMA — QUOTE WIN
#
# Target for the quote_win table. Standardization only.
#
# The source file is a "SupplyWin/Awards" export: a metadata preamble
# (Template/Project/Volume/... key-value rows), an "*** Assembly Summary"
# aggregate block, then the actual per-part data table under a
# "*** Group Detail" marker. The real header row (Project, Part Number,
# Mfg Part Number, ...) is located dynamically rather than assumed at a
# fixed row index, since the preamble/summary block length can vary
# between exports (e.g. grouped reports).
#
# Volume-suffixed fields (cost_N_conv, price_original_N, awarded_volume_N,
# award_N, source_N) are generated for however many volumes the SOURCE FILE
# actually has -- confirmed real (RFQ-000125): a file whose own metadata
# preamble says "Volume: 1-3" carries a full "Cost #3 (Conv.)"/"Price
# (Original) #3"/etc. column set, which a hardcoded 2-slot schema silently
# dropped (never even offered to the LLM header-mapper below), leaving the
# 3rd volume's CBOM rows with no matching price and all-NULL/0 output.
# build_quote_win_template_headers()/_detect_volume_slot_count() below make
# this self-extending for any N, not just a bump from 2 to 3.
# ==========================================================


def build_quote_win_template_headers(slot_count=2):
    """Generates the canonical QuoteWin schema for `slot_count` volume slots
    -- every non-volume field stays in its original position; the
    cost/price/award/source fields repeat once per slot, in the same
    relative grouping the original fixed 2-slot list used.
    """
    cost_fields = []
    for n in range(1, slot_count + 1):
        cost_fields += [f"cost_{n}_conv", f"price_original_{n}"]

    award_fields = []
    for n in range(1, slot_count + 1):
        award_fields += [f"awarded_volume_{n}", f"award_{n}"]

    source_fields = [f"source_{n}" for n in range(1, slot_count + 1)]

    return (
        [
            "project",
            "part_number",
            "part_description",
            "commodity",
            "mfg_name",
            "mfg_part_number",
        ]
        + cost_fields
        + ["currency_original", "supp_name", "supplier_type", "pkg_qty", "moq", "lead_time"]
        + award_fields
        + ["part_qty", "corrected_mpn", "long_comment"]
        + source_fields
        + [
            "price_type",
            "no_bid_reason",
            "short_comment",
            "ncnr",
            "rfq_number",
            "eff_date",
            "exp_date",
            "quote_validity",
            "part_status",
        ]
    )


def build_numeric_headers(slot_count=2):
    """Same slot-count parametrization as build_quote_win_template_headers(),
    for the subset of fields that are DOUBLE-typed in quote_win_to_database.py's
    QUOTE_WIN_DDL (see _NUMERIC_HEADERS' own usage below)."""
    numeric = []
    for n in range(1, slot_count + 1):
        numeric += [f"cost_{n}_conv", f"price_original_{n}"]
    numeric += ["pkg_qty", "moq", "lead_time"]
    for n in range(1, slot_count + 1):
        numeric += [f"awarded_volume_{n}", f"award_{n}"]
    numeric += ["part_qty"]
    return numeric


# Kept as a plain module-level constant (not just the function above) --
# test_quote_win_processing.py, scrub_mcp_server.py, and
# reporting_module/batch_validate_all_tests.py import this name directly and
# expect the historical fixed 2-slot schema; process_quote_win() below
# builds its own wider list per-file when a file actually needs more slots.
QUOTE_WIN_TEMPLATE_HEADERS = build_quote_win_template_headers(2)


# Matches a volume-slot suffix on any of the QuoteWin header labels this
# format actually uses ("Cost #3 (Conv.)", "Price (Original) #3", "Awarded
# Volume #3", "Award #3", "Source #3") -- deliberately not anchored to one
# exact label text, since only the "#N" token itself needs detecting.
_VOLUME_SLOT_HEADER_RE = re.compile(r"#\s*(\d+)")


def _detect_volume_slot_count(headers, minimum=2):
    """Scans raw QuoteWin headers for the highest "#N" volume-slot suffix
    actually present, so a file with more volumes than the historical
    2-slot default (confirmed real: RFQ-000125's file declares "Volume:
    1-3" and carries Cost/Price/Award/Source #1/#2/#3) gets every slot
    mapped, not just the first 2. Defaults to `minimum` so an ordinary
    1-2-volume file's behavior is completely unchanged.
    """
    max_slot = minimum
    for h in headers:
        for m in _VOLUME_SLOT_HEADER_RE.finditer(str(h)):
            max_slot = max(max_slot, int(m.group(1)))
    return max_slot

# Header values that must all be present in a row for it to be treated
# as the Group Detail data table's header row.
_HEADER_ROW_SIGNATURE = ["Part Number", "Mfg Part Number", "Commodity"]


# ==========================================================
# REPORT TABLE LOCATION
# ==========================================================

def _find_header_row(raw_df):

    for i in range(len(raw_df)):

        row_values = [
            str(v).strip()
            for v in raw_df.iloc[i].values
            if pd.notna(v)
        ]

        if all(sig in row_values for sig in _HEADER_ROW_SIGNATURE):
            return i

    raise ValueError(
        "Could not locate the QuoteWin data header row "
        f"(expected columns: {_HEADER_ROW_SIGNATURE})."
    )


def load_quote_win_table(file_path, sheet_name=0):

    raw_df = pd.read_excel(
        file_path,
        sheet_name=sheet_name,
        header=None
    )

    header_row_idx = _find_header_row(raw_df)

    header_values = [
        str(v).strip() if pd.notna(v) else f"__unnamed_{i}"
        for i, v in enumerate(raw_df.iloc[header_row_idx].values)
    ]

    data_df = raw_df.iloc[header_row_idx + 1:].reset_index(drop=True)
    data_df.columns = header_values

    # Grouped reports may repeat the header row before each group's data —
    # drop any data row that is itself the header row verbatim.
    is_repeated_header = data_df.apply(
        lambda row: [
            str(v).strip() if pd.notna(v) else f"__unnamed_{i}"
            for i, v in enumerate(row.values)
        ] == header_values,
        axis=1
    )
    data_df = data_df[~is_repeated_header].reset_index(drop=True)

    # Drop fully-blank trailing/separator rows.
    data_df = data_df.dropna(how="all").reset_index(drop=True)

    return data_df


# ==========================================================
# LLM SCHEMA MAPPING
# ==========================================================

def semantic_mapping_quote_win(headers, template_headers=QUOTE_WIN_TEMPLATE_HEADERS):

    system_prompt = """
You are a QuoteWin schema mapping engine.

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

{template_headers}

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

    for col in template_headers:
        final_mapping[col] = mapping.get(col)

    return final_mapping


# ==========================================================
# STANDARDIZATION
# ==========================================================

# The only quote_win columns typed DOUBLE/DATE in quote_win_to_database.py's
# QUOTE_WIN_DDL -- every other column is VARCHAR. Used below to decide which
# columns need the date/time stringification pass (numeric/date columns are
# already handled by their own explicit conversions).
_NUMERIC_HEADERS = build_numeric_headers(2)
_DATE_HEADERS = ["eff_date", "exp_date"]


def standardize_quote_win(df, mapping, template_headers=QUOTE_WIN_TEMPLATE_HEADERS, numeric_headers=_NUMERIC_HEADERS):

    rename_dict = {}
    claimed_sources = set()

    for target_col in template_headers:

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

    for col in template_headers:

        if col not in standardized_df.columns:
            standardized_df[col] = None

    standardized_df = standardized_df[
        template_headers
    ]

    # eff_date / exp_date arrive as "DD/MM/YY" strings — parse to real
    # dates so they cast cleanly into the quote_win table's DATE columns.
    # Explicit format avoids pandas' per-row dateutil fallback (slow and
    # emits a UserWarning); any value that doesn't match falls back to a
    # generic dayfirst parse.
    for date_col in ["eff_date", "exp_date"]:

        parsed = pd.to_datetime(
            standardized_df[date_col],
            format="%d/%m/%y",
            errors="coerce"
        )

        unparsed = parsed.isna() & standardized_df[date_col].notna()

        if unparsed.any():
            parsed[unparsed] = pd.to_datetime(
                standardized_df.loc[unparsed, date_col],
                dayfirst=True,
                errors="coerce"
            )

        standardized_df[date_col] = parsed.dt.date

    # Some QuoteWin exports have per-cell Excel number-formatting quirks on
    # otherwise free-text columns -- e.g. a "Quote Validity" column where most
    # rows hold a real date but a handful of rows are formatted as bare
    # time-of-day cells, which openpyxl hands back as datetime.time(0, 0)
    # rather than a string. A column mixing datetime and time objects fails
    # to insert into DuckDB at all ("Unimplemented type for cast (TIME ->
    # TIMESTAMP)"), which silently drops every row -- and every price -- for
    # the whole file. Stringify anything date/time-like in every column that
    # isn't itself numeric or one of the two real DATE columns (datetime.date
    # covers datetime.datetime/pd.Timestamp too, since both subclass it).
    #
    # Confirmed real-data bug (RFQ-000061): a free-text column that's blank for
    # nearly every row (e.g. "Corrected MPN", populated on only a handful of
    # rows out of ~12,700) leaves this column's pandas dtype ambiguous. DuckDB's
    # conn.register()/INSERT...SELECT (quote_win_to_database.py) infers the
    # column's type from the DataFrame itself and can misinfer a
    # mostly-empty object column as numeric -- the insert then aborts the
    # moment it scans a real string value ("Could not convert string
    # 'RT-375-3/64-X-STK' to INT32"), even though this column's target
    # DuckDB schema column is correctly VARCHAR. Same failure class as the
    # date/time-mixing and "Internal Stock" bugs above: one bad cell in one
    # row silently drops every row -- and every price -- for the whole file.
    # Casting to pandas' "string" extension dtype removes the ambiguity
    # DuckDB's inference was tripping on, for every free-text column, not
    # just this one.
    for col in template_headers:
        if col in numeric_headers or col in _DATE_HEADERS:
            continue
        standardized_df[col] = standardized_df[col].map(
            lambda v: str(v) if isinstance(v, (datetime.date, datetime.time)) else v
        ).astype("string")

    # Confirmed real-data bug (RFQ-000012): suppliers sometimes write a qualitative
    # status -- e.g. "Internal Stock" -- directly into a numeric column like Lead
    # Time instead of leaving it blank or putting it in a remarks field. DuckDB's
    # INSERT then raises "Conversion Error: Could not convert string 'Internal
    # Stock' to DOUBLE" and aborts the ENTIRE quote_win insert for this rfq_id --
    # same class of failure as the quote_validity fix above (one bad cell in one
    # row silently drops every row -- and every price -- for the whole file).
    # Coerce every numeric-designated column so any non-numeric text becomes NULL
    # instead of crashing the insert; pd.to_numeric(errors="coerce") leaves real
    # numbers untouched.
    for col in numeric_headers:
        standardized_df[col] = pd.to_numeric(standardized_df[col], errors="coerce")

    return standardized_df


# ==========================================================
# MAIN PROCESSOR
# ==========================================================

_AWARD_SLOT_COL_RE = re.compile(r"^award_(\d+)$")


def _deduplicate_awarded_rows(df):
    """Some QuoteWin files contain multiple rows for the same manufacturer part
    that are ALL fully awarded (award_N == 100 on every volume slot present)
    with IDENTICAL price_original_N on every one of those same slots -- these
    rows carry no meaningful distinction, so only the first occurrence is kept
    and the rest are dropped.

    Deliberately conservative: a row is only ever collapsed into an earlier
    one if EVERY present volume slot agrees on both award status and price.
    Slot numbers are discovered from the DataFrame's own award_N columns
    (not a hardcoded (1, 2) -- a file can carry more slots, see
    build_quote_win_template_headers()'s own docstring), so this naturally
    covers however many volumes standardize_quote_win() produced. If award
    percentages differ, or prices differ, on even one slot, the rows are
    left untouched -- that's the existing, deliberate multi-supplier-quote
    case (different suppliers genuinely quoting the same part), which
    reporting_module/queries.py's `selected_quote` tie-break view already
    handles at report-generation time; this function only removes true,
    no-distinction duplicates before that view ever sees them.

    Grouped by mfg_part_number alone (not part_number/CPN) -- the same
    manufacturer part can appear under different customer part numbers and
    is still the same physical part/award decision.
    """
    detected_slots = sorted(
        int(m.group(1)) for col in df.columns for m in [_AWARD_SLOT_COL_RE.match(col)] if m
    )
    volume_slots = [
        (f"award_{n}", f"price_original_{n}")
        for n in detected_slots
        if f"price_original_{n}" in df.columns
    ]
    if not volume_slots or "mfg_part_number" not in df.columns:
        return df

    def _is_fully_awarded(row):
        return all(
            pd.notna(row[award_col]) and float(row[award_col]) == 100
            for award_col, _ in volume_slots
        )

    def _price_fingerprint(row):
        return tuple(
            round(float(row[price_col]), 6) if pd.notna(row[price_col]) else None
            for _, price_col in volume_slots
        )

    seen = set()
    keep_mask = []
    for _, row in df.iterrows():
        mfg_part = row.get("mfg_part_number")
        if pd.isna(mfg_part) or not _is_fully_awarded(row):
            keep_mask.append(True)
            continue
        key = (mfg_part, _price_fingerprint(row))
        if key in seen:
            keep_mask.append(False)
        else:
            seen.add(key)
            keep_mask.append(True)

    deduped_df = df[keep_mask].reset_index(drop=True)
    dropped = len(df) - len(deduped_df)
    if dropped:
        print(
            f"QuoteWin dedup: dropped {dropped} duplicate fully-awarded row(s) "
            "with identical pricing (kept first occurrence of each)."
        )
    return deduped_df


def process_quote_win(file_path, sheet_name=0):

    print("\nLoading QuoteWin report...")

    raw_df = load_quote_win_table(
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

    # Detects however many volume slots this specific file's headers
    # actually carry (e.g. 3 for RFQ-000125's "Cost #3 (Conv.)" etc.) --
    # see build_quote_win_template_headers()/_detect_volume_slot_count()'s
    # own docstrings. A plain 1-2-volume file resolves to 2, identical to
    # the previous hardcoded behavior.
    slot_count = _detect_volume_slot_count(headers)
    template_headers = build_quote_win_template_headers(slot_count)
    numeric_headers = build_numeric_headers(slot_count)

    # ======================================================
    # LLM HEADER MAPPING
    # ======================================================

    print(
        "\nRunning QuoteWin schema mapping..."
    )

    mapping = semantic_mapping_quote_win(
        headers,
        template_headers=template_headers,
    )

    # ======================================================
    # FORCE CRITICAL MAPPINGS
    #
    # Dry-run testing (repeated semantic_mapping_quote_win() calls
    # against the same headers) showed these fields mapped
    # inconsistently — pkg_qty and part_qty occasionally, ncnr in the
    # majority of runs, no_bid_reason intermittently across a larger
    # batch of runs — even though the exact-named column is present.
    # Forced deterministically over the LLM's guess when the header is
    # present verbatim.
    # ======================================================

    header_lookup = {
        str(col).strip().upper(): col
        for col in raw_df.columns
    }

    critical_overrides = {
        "pkg_qty": "PKG QTY",
        "part_qty": "PART QTY",
        "ncnr": "NCNR",
        "no_bid_reason": "NO BID REASON",
    }

    for canonical, actual in critical_overrides.items():

        if actual in header_lookup:

            mapping[canonical] = (
                header_lookup[actual]
            )

    # Deterministic overrides for the volume-suffixed columns themselves
    # (same reasoning as critical_overrides above -- don't depend on LLM
    # accuracy for a field whose exact source label is already known).
    # Matches this format's confirmed real header text ("Cost #3 (Conv.)",
    # "Price (Original) #3", "Awarded Volume #3", "Award #3", "Source #3");
    # falls back to whatever the LLM guessed if the exact text isn't found
    # (e.g. a differently-worded export), same as any other unmatched field.
    for n in range(1, slot_count + 1):
        volume_overrides = {
            f"cost_{n}_conv": f"COST #{n} (CONV.)",
            f"price_original_{n}": f"PRICE (ORIGINAL) #{n}",
            f"awarded_volume_{n}": f"AWARDED VOLUME #{n}",
            f"award_{n}": f"AWARD #{n}",
            f"source_{n}": f"SOURCE #{n}",
        }
        for canonical, actual in volume_overrides.items():
            if actual in header_lookup:
                mapping[canonical] = header_lookup[actual]

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
    print("QUOTE WIN SCHEMA MAPPING")
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
        standardize_quote_win(
            raw_df,
            mapping,
            template_headers=template_headers,
            numeric_headers=numeric_headers,
        )
    )

    standardized_df = _deduplicate_awarded_rows(standardized_df)

    print(
        "\n===================================="
    )
    print("QUOTE WIN STANDARDIZATION SUMMARY")
    print(
        "===================================="
    )
    print(f"Original QuoteWin rows:     {original_rows}")
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
            "  python quote_win_processing.py "
            "<quote_win.xlsx> [output.xlsx]"
        )
        sys.exit(1)

    _quote_win_file = sys.argv[1].strip().strip('"')
    _output_file = (
        sys.argv[2].strip().strip('"')
        if len(sys.argv) >= 3
        else "standardized_quote_win.xlsx"
    )

    if not Path(_quote_win_file).exists():
        print(f"ERROR: File not found: {_quote_win_file}")
        sys.exit(1)

    _standardized_df = process_quote_win(_quote_win_file)

    _standardized_df.to_excel(_output_file, index=False)

    print(f"Done.\nOutput written to: {_output_file}")
