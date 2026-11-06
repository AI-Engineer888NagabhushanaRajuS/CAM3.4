import json
from pathlib import Path

import ollama
import pandas as pd

# The machine/user-level OLLAMA_HOST env var on this box is set to
# "0.0.0.0:11434" (so `ollama serve` binds on all interfaces for remote/
# Tailscale access). ollama.chat()'s module-level default client reads
# that same var as a value to CONNECT to, and 0.0.0.0 is not a valid
# outbound destination -- every call fails with the library's generic
# "Failed to connect to Ollama" ConnectionError even while Ollama is up.
# Pin an explicit client to loopback so this tool is immune to that
# server-side env var regardless of how it's set.
_OLLAMA_CLIENT = ollama.Client(host="http://127.0.0.1:11434")


# ==========================================================
# CANONICAL SCHEMA
#
# cpn is a MANDATORY, DETERMINISTIC mapping: cpn <- UBR Number.
# This is a confirmed business rule (UBR Number IS the Customer Part
# Number), enforced in process_bom() — never left to the LLM semantic
# mapping. See the CPN validation block below.
# ==========================================================

PREDEFINED_TEMPLATE_HEADERS = [
    "fg",
    "bom_id",
    "bom_level",

    "cpn",
    "description",
    "mfr",
    "mpn",

    "commodity",

    "bom_qty",
    "volume",
    "required_qty",

    "uom",

    "ce_remarks",
    "item_num",
    "part_type",
    "ltb_date",
    "common_aml",
    "change_remarks",
    "exported_at",
    "imported_at"
]

# Fields with a FORCED/deterministic source column (bom_id, bom_level, mpn,
# bom_qty, uom via critical_overrides in process_bom(); cpn via its own
# dedicated validation block). These always win a source-column collision
# during standardize_bom() — if the LLM's semantic guess also happens to
# point some other, non-forced field (e.g. item_num) at the same raw
# column, that non-forced field is dropped rather than silently
# overwriting the forced field's claim on it.
FORCED_FIELDS = ["bom_id", "bom_level", "cpn", "mpn", "bom_qty", "uom"]


# ==========================================================
# UNIT NORMALIZATION
# ==========================================================

def normalize_length(qty, uom):

    if pd.isna(uom):
        return qty, uom

    uom = str(uom).strip().lower()

    if uom in ["meter", "meters", "m"]:
        return qty * 1000, "mm"

    if uom in ["feet", "foot", "ft"]:
        return qty * 304.8, "mm"

    return qty, uom


# Canonical label for all count-based units
_COUNT_UOM_CANONICAL = "Nos"

# Every spelling that should map to "Nos" (lowercase for matching)
_COUNT_UOMS = {
    "ea", "each", "nos", "no",
    "number", "numbers", "pcs",
    "pc", "piece", "pieces",
}

# Canonical spelling for length unit strings (no quantity conversion)
_LENGTH_UOM_MAP = {
    "meter": "Meter", "meters": "Meter", "m": "Meter",
    "feet": "Feet", "foot": "Feet", "ft": "Feet",
    "mm": "mm", "millimeter": "mm", "millimeters": "mm",
}


def normalize_uom(uom):
    """Normalize UOM strings to canonical form without converting quantities.
    Count variants (EA, Each, NOS, PCS, etc.) → 'Nos'.
    Length case variants (meter/METER/m) → 'Meter'; feet/ft → 'Feet'; etc."""
    if pd.isna(uom):
        return uom
    cleaned = str(uom).strip().lower()
    if cleaned in _COUNT_UOMS:
        return _COUNT_UOM_CANONICAL
    if cleaned in _LENGTH_UOM_MAP:
        return _LENGTH_UOM_MAP[cleaned]
    return str(uom).strip()


# ==========================================================
# LLM SCHEMA MAPPING
# ==========================================================

def semantic_mapping(headers):

    system_prompt = """
You are a BOM schema mapping engine.

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

{PREDEFINED_TEMPLATE_HEADERS}

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

    response = _OLLAMA_CLIENT.chat(
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
        format="json"
    )

    mapping = json.loads(
        response["message"]["content"]
    )

    final_mapping = {}

    for col in PREDEFINED_TEMPLATE_HEADERS:
        final_mapping[col] = mapping.get(col)

    return final_mapping


# ==========================================================
# VOLUME FILE SCHEMA MAPPING
#
# Generic, customer-agnostic mapping of a Volume file's headers to the
# two fields the pipeline needs. fg_mpn is deliberately named (not
# "fg") to make the target unambiguous to the LLM: it must be the
# Finished Good's MANUFACTURER Part Number, never a customer/internal
# part number column, even when a CPN-style column reads more
# naturally as "the assembly identifier". FG detection in
# expand_bom_with_volume() matches BOM rows on mpn only, so volume_map
# must be keyed by MPN values for every customer.
# ==========================================================

PREDEFINED_VOLUME_HEADERS = ["fg_mpn", "volume"]


def volume_semantic_mapping(headers):

    system_prompt = """
You are a Volume file schema mapping engine.

Rules:

1. Output ALL predefined schema fields.
2. JSON key must be predefined schema field.
3. Value must be matching incoming header.
4. Use null when no confident match exists.
5. Never guess.
6. Return JSON only.
7. Accuracy is more important than coverage.

Field definitions:

fg_mpn: The Finished Good's Manufacturer Part Number (MPN) — the
column whose values identify which assembly a volume applies to.
This must be a MANUFACTURER part number column (e.g. "MPN",
"Manufacturer Part Number"), NEVER a customer/internal part number
column (e.g. "CPN", "Customer Part Number", "UBR Number", "Item
Number"). Even if a customer/internal-part-number-style column looks
like the more natural "assembly identifier", the correct mapping for
fg_mpn is always the manufacturer part number column.

volume: The build/production quantity column for that Finished Good
(e.g. "Volume", "Vol-1", "Quantity", "Build Qty", "Required Volume",
"Order Qty").
"""

    user_prompt = f"""
Predefined Schema:

{PREDEFINED_VOLUME_HEADERS}

Incoming Headers:

{headers}

Return JSON only.

Example:

{{
    "fg_mpn": "MPN",
    "volume": "Vol-1"
}}
"""

    response = _OLLAMA_CLIENT.chat(
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
        format="json"
    )

    mapping = json.loads(
        response["message"]["content"]
    )

    final_mapping = {}

    for col in PREDEFINED_VOLUME_HEADERS:
        final_mapping[col] = mapping.get(col)

    return final_mapping


# ==========================================================
# STANDARDIZATION
# ==========================================================

def standardize_bom(df, mapping):

    rename_dict = {}
    claimed_sources = set()

    # FORCED_FIELDS are processed first so they always claim their source
    # column, regardless of mapping.items() iteration order — this is what
    # prevents a non-forced field's LLM-guessed mapping from silently
    # overwriting a forced field that happens to point at the same column.
    ordered_fields = FORCED_FIELDS + [
        col for col in PREDEFINED_TEMPLATE_HEADERS
        if col not in FORCED_FIELDS
    ]

    for target_col in ordered_fields:

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

    for col in PREDEFINED_TEMPLATE_HEADERS:

        if col not in standardized_df.columns:
            standardized_df[col] = None

    standardized_df = standardized_df[
        PREDEFINED_TEMPLATE_HEADERS
    ]

    return standardized_df


# ==========================================================
# EXPORT MAPPING
# ==========================================================

def export_mapping(
    mapping,
    output_path
):

    mapping_df = pd.DataFrame(
        [
            {
                "canonical_field": k,
                "incoming_header": v
            }
            for k, v in mapping.items()
        ]
    )

    mapping_df.to_excel(
        output_path,
        index=False
    )


# ==========================================================
# VOLUME FILE PROCESSING
# ==========================================================

def build_volume_map(volume_df, mapping):

    volume_df.columns = (
        volume_df.columns
        .astype(str)
        .str.strip()
    )

    fg_col = mapping.get("fg_mpn")
    vol_col = mapping.get("volume")

    if fg_col is None or fg_col not in volume_df.columns:
        raise ValueError(
            "Validation Error:\n\n"
            "Could not resolve the Volume file's Finished-Good MPN "
            "column (fg_mpn).\n\n"
            f"Volume mapping produced: {mapping}\n"
            f"Available columns: {list(volume_df.columns)}\n\n"
            "Import aborted."
        )

    if vol_col is None or vol_col not in volume_df.columns:
        raise ValueError(
            "Validation Error:\n\n"
            "Could not resolve the Volume file's volume/quantity "
            "column.\n\n"
            f"Volume mapping produced: {mapping}\n"
            f"Available columns: {list(volume_df.columns)}\n\n"
            "Import aborted."
        )

    print(
        f"\nVolume mapping resolved: "
        f"fg_mpn -> {fg_col}   volume -> {vol_col}"
    )

    volume_map = dict(
        zip(
            volume_df[fg_col]
            .astype(str)
            .str.strip()
            .str.upper(),

            pd.to_numeric(
                volume_df[vol_col],
                errors="coerce"
            ).fillna(0)
        )
    )

    print("\n====================================")
    print("VOLUME MAP")
    print("====================================")

    for fg, vol in volume_map.items():

        print(
            f"{fg:<20}"
            f" -> "
            f"{vol}"
        )

    print("====================================\n")

    return volume_map


# ==========================================================
# BOM EXPANSION
#
# FG identification is driven ENTIRELY by the Volume file: a row's own
# MPN matching a Volume Mapping entry starts a new FG section. The BOM
# file is scanned once, in its original row order, and every row that is
# not itself an FG marker is a child of whichever FG was most recently
# seen -- direct or, when a BOM LEVEL column is present, nested under an
# intermediate sub-assembly row.
#
# Confirmed real-data bug: a sub-assembly's own bom_qty (how many of that
# sub-assembly are used within ITS parent) was never multiplied into its
# children's required_qty -- every part was scaled by volume alone,
# under-counting by the sub-assembly's own qty whenever one is used more
# than once. Same failure mode as centum intake\scrub_bom_processing.py's
# _build_hierarchy_multipliers() bug (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md)
# -- that fix walks an explicit `assembly` parent-reference column; this BOM
# format has no such column, only a numeric BOM LEVEL depth per row, so the
# hierarchy is reconstructed here via a level stack over row order instead.
# ==========================================================

def expand_bom_with_volume(
    standardized_df,
    volume_map
):
    current_fg = None
    current_volume = None
    current_fg_multiplier = 1.0
    current_entry = None
    trace = []
    expanded_rows = []
    seen_fgs = set()

    # Only engage the LEVEL-STACK walk when the source file actually carries a
    # numeric BOM LEVEL for at least one row -- files without it (e.g. the
    # already-verified flat Centum_BOM.xlsx test file, which has no BOM LEVEL
    # column at all) have no sub-assembly depth to walk, so every child is a
    # direct child of the FG. The FG marker's own bom_qty (current_fg_multiplier)
    # still applies either way -- see the FG-marker branch below.
    has_hierarchy = (
        "bom_level" in standardized_df.columns
        and pd.to_numeric(standardized_df["bom_level"], errors="coerce").notna().any()
    )

    # Stack of (level, cumulative_multiplier) frames for the CURRENT fg only --
    # reset every time a new FG marker is seen below, since each FG's
    # hierarchy is independent. cumulative_multiplier at a frame is the
    # product of every ancestor row's own bom_qty up to (not including) that
    # frame's own row -- i.e. what a CHILD of that frame should multiply by.
    level_stack = []

    rows = standardized_df.to_dict("records")

    for i, row in enumerate(rows):

        excel_row = i + 2  # +1 for 0-index, +1 for the header row

        mpn = str(row.get("mpn", "")).strip().upper()

        if mpn and mpn in volume_map:
            if current_entry is not None:
                trace.append(current_entry)
            current_fg = mpn
            current_volume = volume_map[mpn]
            seen_fgs.add(mpn)
            # Confirmed real-data bug: this FG marker row's OWN bom_qty (how
            # many of this FG-level assembly are used -- e.g. a harness used
            # twice within a larger, unlisted parent) was discarded entirely
            # by resetting to an empty stack (implicit multiplier 1.0) here.
            # Seed the stack with it instead, exactly as an ordinary
            # (non-FG-marker) assembly row's own qty seeds its children's
            # multiplier below -- this FG marker is not special-cased, it's
            # just the first frame. bom_level defaults to 0 (not NaN) so any
            # real child level compares/pops correctly against it.
            fg_qty = pd.to_numeric(row.get("bom_qty"), errors="coerce")
            fg_qty = 1.0 if pd.isna(fg_qty) or fg_qty <= 0 else fg_qty
            fg_level = pd.to_numeric(row.get("bom_level"), errors="coerce")
            fg_level = 0 if pd.isna(fg_level) else fg_level
            current_fg_multiplier = fg_qty
            level_stack = [(fg_level, fg_qty)]
            current_entry = {
                "fg": mpn,
                "start_row": excel_row,
                "end_row": excel_row,
                "child_count": 0
            }
            continue

        if current_fg is None:
            print(
                f"WARNING: row {excel_row} appears before any FG "
                f"marker — skipped."
            )
            continue

        if not mpn:
            print(
                f"WARNING: blank MPN under FG "
                f"'{current_fg}' — row skipped."
            )
            continue

        qty = pd.to_numeric(
            row.get("bom_qty"),
            errors="coerce"
        )

        if pd.isna(qty) or qty <= 0:
            print(
                f"WARNING: invalid qty for "
                f"'{mpn}' under FG '{current_fg}' — row skipped."
            )
            continue

        if has_hierarchy:
            level = pd.to_numeric(row.get("bom_level"), errors="coerce")
            if pd.isna(level):
                # No level stated on this specific row -- treat it as a
                # sibling of whatever the current top-of-stack ancestor is,
                # rather than letting a NaN comparison (always False) stop
                # the pop loop below and silently inherit an unrelated
                # ancestor's multiplier.
                level = level_stack[-1][0] if level_stack else 0
            while level_stack and level_stack[-1][0] >= level:
                level_stack.pop()
            # Falls back to current_fg_multiplier (not a bare 1.0) if a
            # malformed row's level popped even the FG marker's own seeded
            # frame -- the FG's own qty must still apply with no deeper
            # hierarchy left, same as the has_hierarchy=False branch below.
            ancestor_multiplier = level_stack[-1][1] if level_stack else current_fg_multiplier
        else:
            level = None
            ancestor_multiplier = current_fg_multiplier

        new_row = dict(row)
        new_row["fg"] = current_fg
        new_row["bom_qty"] = qty
        new_row["volume"] = current_volume
        new_row["required_qty"] = qty * ancestor_multiplier * current_volume
        # Resolved numeric level (None on a no-hierarchy/flat BOM, otherwise the
        # value actually used above -- including the sibling-of-top-of-stack
        # fallback for a row with no level of its own -- never the raw,
        # possibly-NaN row value). Exposed alongside required_qty (rather than
        # folded silently into it) so a downstream per-occurrence structural
        # view (e.g. a hierarchical BOM report) can compute its own extended
        # cost for ONE fg instance (bom_qty * hierarchy_multiplier) separately
        # from required_qty's already-volume-scaled total.
        new_row["bom_level"] = level
        new_row["hierarchy_multiplier"] = ancestor_multiplier
        expanded_rows.append(new_row)

        if has_hierarchy:
            # Pushed AFTER computing this row's own required_qty -- a row
            # that turns out to be a sub-assembly (deeper rows follow) makes
            # its own bom_qty available to those children via this frame,
            # without affecting its own multiplier above.
            level_stack.append((level, ancestor_multiplier * qty))

        current_entry["end_row"] = excel_row
        current_entry["child_count"] += 1

    if current_entry is not None:
        trace.append(current_entry)

    print("\n====================================")
    print("FG DETECTION TRACE")
    print("====================================")
    for entry in trace:
        print(
            f"FG detected: {entry['fg']:<15}"
            f"  Starting row: {entry['start_row']:<8}"
            f"  Ending row: {entry['end_row']:<8}"
            f"  Child count: {entry['child_count']}"
        )
    print("====================================\n")

    missing_volumes = [fg for fg in volume_map if fg not in seen_fgs]
    if missing_volumes:
        for fg in missing_volumes:
            print(
                f"WARNING: '{fg}' is in the volume "
                f"file but was never found as a row's MPN — skipped."
            )

    expanded_df = pd.DataFrame(expanded_rows)

    print(
        f"\nExpanded Rows: "
        f"{len(expanded_df)}"
    )

    return expanded_df


# ==========================================================
# CONSOLIDATION
#
# MPN (Manufacturer Part Number) is the sole consolidation key: the
# distributor pricing pipeline needs exactly one row per manufacturer
# part, so rows are merged whenever their MPN matches, regardless of
# CPN. CPN is preserved only as combined reference data (same pattern
# already used for fg). Same-CPN-different-MPN ("alternate
# manufacturer") handling is a separate concern, out of scope here.
# ==========================================================

def consolidate_bom(df):

    df = df.copy()

    df["mpn"] = (
        df["mpn"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df["cpn"] = (
        df["cpn"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df = df[df["mpn"] != ""]

    # ----------------------------------
    # NUMERIC CONVERSION
    # ----------------------------------

    df["bom_qty"] = pd.to_numeric(
        df["bom_qty"],
        errors="coerce"
    ).fillna(0)

    df["volume"] = pd.to_numeric(
        df["volume"],
        errors="coerce"
    ).fillna(0)

    df["required_qty"] = pd.to_numeric(
        df["required_qty"],
        errors="coerce"
    ).fillna(0)

    # ----------------------------------
    # UNIT NORMALIZATION
    # Step 1: normalize count-based UOM variants to "Nos".
    # Step 2: convert length UOMs to mm.
    #
    # required_qty is scaled proportionally to bom_qty so
    # the expansion-computed value (effective_qty × volume)
    # is preserved in consistent mm units.
    # ----------------------------------

    df["uom"] = df["uom"].apply(normalize_uom)

    normalized = df.apply(
        lambda row: normalize_length(
            row["bom_qty"],
            row["uom"]
        ),
        axis=1
    )

    original_bom_qty = df["bom_qty"].copy()

    df["bom_qty"] = normalized.apply(
        lambda x: x[0]
    )

    df["uom"] = normalized.apply(
        lambda x: x[1]
    )

    ratio = df["bom_qty"] / original_bom_qty.replace(0, 1)
    df["required_qty"] = df["required_qty"] * ratio

    # Confirmed real-data bug: consolidated bom_qty below used to sum this
    # row's own local bom_qty as-is, never multiplied by hierarchy_multiplier
    # -- under-counting any MPN whose ancestor chain (an FG's own qty, or a
    # sub-assembly's own qty) is greater than 1, exactly like required_qty
    # was under-counted before hierarchy_multiplier existed. required_qty is
    # additionally volume-scaled (needed for distributor price-break tier
    # selection); this is the same weighting one level up from that, kept as
    # its own column rather than folding it into required_qty so "quantity
    # per FG instance" and "total demand across the whole build" stay
    # distinguishable, per the "don't mix quantity concepts" rule this
    # pipeline follows elsewhere (see bom_structure_items/quote_summary.py).
    df["hierarchy_multiplier"] = pd.to_numeric(
        df.get("hierarchy_multiplier"), errors="coerce"
    ).fillna(1.0)
    df["weighted_bom_qty"] = df["bom_qty"] * df["hierarchy_multiplier"]

    # ----------------------------------
    # UOM CONFLICT DETECTION
    # Rows sharing the same MPN (the consolidation key below) with
    # different units cannot be safely summed together.
    # ----------------------------------

    uom_per_mpn = df.groupby("mpn")["uom"].nunique()
    conflicting = uom_per_mpn[uom_per_mpn > 1].index.tolist()

    if conflicting:
        raise ValueError(
            f"UOM conflict — cannot consolidate the following "
            f"MPN(s) because they appear with different "
            f"units of measure: {conflicting}"
        )

    # ----------------------------------
    # CONSOLIDATE
    # Grouping key is mpn ALONE: every row sharing the same MPN is
    # merged into a single row with summed quantities, regardless of
    # CPN. CPN is preserved as combined reference data, same pattern
    # as fg. This guarantees zero duplicate MPNs in the output.
    # ----------------------------------

    consolidated_df = (
        df.groupby(["mpn"], as_index=False)
        .agg(
            bom_qty=("weighted_bom_qty", "sum"),

            # volume is a root assembly's production volume;
            # it is not an additive quantity across assemblies.
            volume=("volume", "first"),

            required_qty=("required_qty", "sum"),

            fg=("fg", lambda x: ", ".join(
                sorted(set(x.astype(str)))
            )),

            cpn=("cpn", lambda x: ", ".join(
                sorted(set(x.astype(str)))
            )),

            description=("description", "first"),
            mfr=("mfr", "first"),
            commodity=("commodity", "first"),
            uom=("uom", "first"),

            # Number of raw rows merged into this MPN row —
            # used for the duplicate-CPN occurrence report.
            occurrences=("mpn", "size")
        )
    )

    return consolidated_df


# ==========================================================
# DUPLICATE CPN VALIDATION
#
# Unchanged function: kept exactly as-is per scope. consolidate_bom()
# now groups by mpn alone (not (cpn, mpn)), so cpn on consolidated_df
# is a combined reference string rather than an atomic value — the
# same-CPN-different-MPN ("alternate manufacturer") detection this
# function performs is deferred to a separate alternate-approval
# workflow, not fixed here.
# ==========================================================

def detect_duplicate_cpn_conflicts(consolidated_df):

    if consolidated_df.empty:
        return []

    mpn_counts = consolidated_df.groupby("cpn")["mpn"].nunique()
    conflicting_cpns = mpn_counts[mpn_counts > 1].index.tolist()

    conflicts = []

    for cpn in conflicting_cpns:

        group = consolidated_df[consolidated_df["cpn"] == cpn]

        conflicts.append({
            "cpn": cpn,
            "mpns": group["mpn"].tolist(),
            "occurrences": dict(
                zip(group["mpn"], group["occurrences"])
            )
        })

    return conflicts


def print_duplicate_cpn_report(conflicts):

    if not conflicts:
        return

    print(
        "\n===================================="
    )
    print("DUPLICATE CPN WITH DIFFERENT MPN DETECTED")
    print(
        "===================================="
    )

    for conflict in conflicts:

        print(f"CPN: {conflict['cpn']}")

        for mpn, count in conflict["occurrences"].items():
            print(f"    MPN: {mpn:<20} occurrences: {count}")

    print(
        "====================================\n"
    )

# ==========================================================
# MAIN PROCESSOR
# ==========================================================

def process_bom(
    bom_file,
    volume_file
):

    print("\nLoading BOM...")

    bom_df = pd.read_excel(
        bom_file
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
        "\nRunning schema mapping..."
    )

    mapping = semantic_mapping(
        headers
    )

    # ======================================================
    # FORCE CRITICAL MAPPINGS
    # ======================================================

    header_lookup = {
        str(col).strip().upper(): col
        for col in bom_df.columns
    }

    # ======================================================
    # CPN (Customer Part Number)
    #
    # Business rule: where present, UBR Number IS the Customer Part
    # Number, and is forced deterministically over the LLM's semantic
    # guess — that guess was empirically non-deterministic (mapped to
    # Assy # or Part Number across identical runs), which silently
    # broke alternate-manufacturer-part detection (same CPN + different
    # MPN). Not every customer names this column "UBR Number" (e.g.
    # Centum uses "CPN" directly) — when the literal override isn't
    # present, semantic_mapping()'s own guess for "cpn" is kept as-is,
    # same graceful pattern as every other critical_overrides field
    # below. Required-fields validation still fails loudly if cpn
    # can't be resolved by either path.
    # ======================================================

    if "UBR NUMBER" in header_lookup:
        mapping["cpn"] = header_lookup["UBR NUMBER"]

    # bom_qty accepts a short list of common literal header names, tried in
    # order -- confirmed real-data gap: a file whose quantity column is
    # named "Quantity" (Centum_BOM.xlsx) has no "BOM QTY" header at all, so
    # this override never triggered and bom_qty was left entirely to
    # semantic_mapping()'s LLM guess, which does not reliably pick "Quantity"
    # out of a header list containing no more-quantity-sounding alternative
    # (empirically: mapped to None, failing "Missing critical mappings"
    # every time against this file, not just intermittently).
    critical_overrides = {
        "bom_id": ["BOM_ID"],
        "bom_level": ["BOM LEVEL"],
        "mpn": ["MPN"],
        "bom_qty": ["BOM QTY", "QUANTITY", "QTY"],
        "uom": ["UOM"]
    }

    for canonical, candidates in critical_overrides.items():

        for actual in candidates:

            if actual in header_lookup:

                mapping[canonical] = (
                    header_lookup[actual]
                )
                break

    # ======================================================
    # VALIDATION
    # ======================================================

    required_fields = [
        "cpn",
        "mpn",
        "bom_qty"
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
    print("SCHEMA MAPPING")
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
        standardize_bom(
            bom_df,
            mapping
        )
    )

    # ======================================================
    # VOLUME LOOKUP
    # ======================================================

    volume_df = pd.read_excel(
        volume_file
    )

    volume_mapping = volume_semantic_mapping(
        list(volume_df.columns)
    )

    volume_map = build_volume_map(
        volume_df,
        volume_mapping
    )

    # ======================================================
    # EXPANSION
    # ======================================================

    expanded_df = (
        expand_bom_with_volume(
            standardized_df,
            volume_map
        )
    )

    # ======================================================
    # CONSOLIDATION
    # ======================================================

    # pd.DataFrame([]) on zero expanded rows has no columns at all, so
    # consolidate_bom's df["mpn"]/df["cpn"] would raise KeyError instead of
    # a meaningful result -- e.g. a Volume file with no MPNs in common with
    # the BOM. Return a typed-empty frame instead of crashing.
    if expanded_df.empty:
        consolidated_df = pd.DataFrame(columns=list(expanded_df.columns) + ["mpn", "cpn"]) \
            if not expanded_df.columns.empty \
            else pd.DataFrame(columns=["mpn", "cpn"])
    else:
        consolidated_df = (
            consolidate_bom(
                expanded_df
            )
        )

    # ======================================================
    # DUPLICATE CPN VALIDATION
    # Must run BEFORE distributor enrichment (this function
    # returns before any distributor API call is ever made).
    # ======================================================

    duplicate_cpn_conflicts = detect_duplicate_cpn_conflicts(
        consolidated_df
    )

    print_duplicate_cpn_report(
        duplicate_cpn_conflicts
    )

    # ======================================================
    # VALIDATION SUMMARY
    # ======================================================

    print(
        "\n===================================="
    )
    print("BOM PROCESSING SUMMARY")
    print(
        "===================================="
    )
    print(f"Original BOM rows:          {original_rows}")
    print(f"Rows after consolidation:   {len(consolidated_df)}")
    print(f"Duplicate CPN conflicts:    {len(duplicate_cpn_conflicts)}")
    print(f"Unique parts sent for pricing: {len(consolidated_df)}")
    print(
        "====================================\n"
    )

    # expanded_df: the pre-consolidation, per-occurrence rows (fg, bom_level,
    # hierarchy_multiplier, local bom_qty, etc.) consolidate_bom() discards via
    # its groupby(["mpn"]) above. Returned alongside consolidated_df (not
    # merged into it) so a caller that needs per-occurrence structure (a
    # hierarchical BOM report) can persist it, without changing what
    # consolidated_df itself is used for (distributor enrichment, one row per
    # unique MPN).
    return consolidated_df, duplicate_cpn_conflicts, expanded_df


# ==========================================================
# ENTRYPOINT
# ==========================================================

if __name__ == "__main__":

    import sys

    SEP = "-" * 48

    # ----------------------------------------------------------
    # ARGUMENT PARSING
    # ----------------------------------------------------------

    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python bom_processing.py "
            "<bom.xlsx> <volume.xlsx> [output.xlsx]\n"
            "\nExample:\n"
            "  python bom_processing.py "
            "raw_bom.xlsx volume_mapping.xlsx"
        )
        sys.exit(1)

    _bom_file    = sys.argv[1].strip().strip('"')
    _volume_file = sys.argv[2].strip().strip('"')
    _output_file = (
        sys.argv[3].strip().strip('"')
        if len(sys.argv) >= 4
        else "consolidated_BOM.xlsx"
    )

    # ----------------------------------------------------------
    # HELPERS — collect stats and errors as we go
    # ----------------------------------------------------------

    _stats = {
        "original_rows":         0,
        "root_assemblies":       0,
        "leaf_components":       0,
        "consolidated_mpns":     0,
        "duplicate_cpn_conflicts": 0,
        "missing_volumes":       [],
        "cyclic_errors":         0,
        "uom_conflicts":         0,
    }

    _exit_code = 0

    print(SEP)
    print("BOM Consolidation Tool")
    print(SEP)

    # ----------------------------------------------------------
    # STEP 1: LOAD BOM FILE
    # ----------------------------------------------------------

    print(f"Loading BOM...           {Path(_bom_file).name}")

    if not Path(_bom_file).exists():
        print(f"ERROR: File not found: {_bom_file}")
        sys.exit(1)

    _bom_df = pd.read_excel(_bom_file)
    _bom_df.columns = (
        _bom_df.columns.astype(str).str.strip()
    )
    _headers = list(_bom_df.columns)

    _stats["original_rows"] = len(_bom_df)

    # ----------------------------------------------------------
    # STEP 2: SCHEMA MAPPING (same logic as process_bom)
    # ----------------------------------------------------------

    print("Running schema mapping...")

    _mapping = semantic_mapping(_headers)

    _header_lookup = {
        str(col).strip().upper(): col
        for col in _bom_df.columns
    }

    if "UBR NUMBER" in _header_lookup:
        _mapping["cpn"] = _header_lookup["UBR NUMBER"]

    _critical_overrides = {
        "bom_id":    ["BOM_ID"],
        "bom_level": ["BOM LEVEL"],
        "mpn":       ["MPN"],
        "bom_qty":   ["BOM QTY", "QUANTITY", "QTY"],
        "uom":       ["UOM"],
    }

    for _canonical, _candidates in _critical_overrides.items():
        for _actual in _candidates:
            if _actual in _header_lookup:
                _mapping[_canonical] = _header_lookup[_actual]
                break

    _missing_fields = [
        f for f in ["cpn", "mpn", "bom_qty"]
        if _mapping.get(f) is None
    ]

    if _missing_fields:
        print(
            f"ERROR: Missing critical BOM column mappings: "
            f"{_missing_fields}"
        )
        sys.exit(1)

    # ----------------------------------------------------------
    # STEP 3: STANDARDIZE
    # ----------------------------------------------------------

    _standardized_df = standardize_bom(_bom_df, _mapping)

    # ----------------------------------------------------------
    # STEP 4: LOAD VOLUME MAPPING (Volume Mapping must be read before BOM
    # structure is built — it is the primary signal for identifying FGs)
    # ----------------------------------------------------------

    print(
        f"Loading Volume Mapping...  "
        f"{Path(_volume_file).name}"
    )

    if not Path(_volume_file).exists():
        print(f"ERROR: File not found: {_volume_file}")
        sys.exit(1)

    _volume_df      = pd.read_excel(_volume_file)
    _volume_mapping = volume_semantic_mapping(list(_volume_df.columns))
    _volume_map     = build_volume_map(_volume_df, _volume_mapping)

    # ----------------------------------------------------------
    # STEP 5: EXPAND BOM (FG detection is Volume-file-driven, done
    # inside expand_bom_with_volume(); stats derived from its output)
    # ----------------------------------------------------------

    print("Expanding BOM...")

    try:
        _expanded_df = expand_bom_with_volume(
            _standardized_df,
            _volume_map
        )
    except ValueError as _e:
        print(f"ERROR: {_e}")
        _stats["cyclic_errors"] = 1
        _exit_code = 1
        _expanded_df = pd.DataFrame()

    _stats["leaf_components"] = len(_expanded_df)
    _stats["root_assemblies"] = (
        _expanded_df["fg"].nunique() if not _expanded_df.empty else 0
    )
    _seen_fgs = set(_expanded_df["fg"]) if not _expanded_df.empty else set()
    _stats["missing_volumes"] = [
        fg for fg in _volume_map
        if fg not in _seen_fgs
    ]

    print(
        f"  Root assemblies (FGs) : "
        f"{_stats['root_assemblies']}"
    )
    if not _exit_code:
        print(
            f"  Leaf components   : "
            f"{_stats['leaf_components']}"
        )

    # ----------------------------------------------------------
    # STEP 7: CONSOLIDATE
    # ----------------------------------------------------------

    _consolidated_df = pd.DataFrame()
    _duplicate_cpn_conflicts = []

    if not _exit_code and not _expanded_df.empty:

        print("Consolidating MPNs...")

        try:
            _consolidated_df = consolidate_bom(_expanded_df)
            _stats["consolidated_mpns"] = len(_consolidated_df)

            _duplicate_cpn_conflicts = detect_duplicate_cpn_conflicts(
                _consolidated_df
            )
            _stats["duplicate_cpn_conflicts"] = len(_duplicate_cpn_conflicts)
            print_duplicate_cpn_report(_duplicate_cpn_conflicts)

        except ValueError as _e:
            print(f"ERROR: {_e}")
            _stats["uom_conflicts"] = 1
            _exit_code = 1

    # ----------------------------------------------------------
    # STEP 8: EXPORT
    # ----------------------------------------------------------

    if not _exit_code and not _consolidated_df.empty:

        print("Writing output...")

        _written_path = None

        try:
            _consolidated_df.to_excel(_output_file, index=False)
            _written_path = _output_file
        except Exception:
            _csv_path = (
                Path(_output_file).with_suffix(".csv")
            )
            try:
                _consolidated_df.to_csv(_csv_path, index=False)
                _written_path = str(_csv_path)
                print(
                    "  NOTE: Excel export failed; "
                    "output written as CSV."
                )
            except Exception as _csv_err:
                print(
                    f"ERROR: Could not write output file: "
                    f"{_csv_err}"
                )
                _exit_code = 1

        if _written_path:
            print(f"\nDone.\nOutput written to: {_written_path}")

    # ----------------------------------------------------------
    # VALIDATION SUMMARY
    # ----------------------------------------------------------

    print(f"\n{SEP}")
    print("VALIDATION SUMMARY")
    print(SEP)
    print(
        f"{'Original BOM rows':<28}: "
        f"{_stats['original_rows']}"
    )
    print(
        f"{'Root assemblies (FGs)':<28}: "
        f"{_stats['root_assemblies']}"
    )
    print(
        f"{'Leaf components (expanded)':<28}: "
        f"{_stats['leaf_components']}"
    )
    print(
        f"{'Rows after consolidation':<28}: "
        f"{_stats['consolidated_mpns']}"
    )
    print(
        f"{'Duplicate CPN conflicts':<28}: "
        f"{_stats['duplicate_cpn_conflicts']}"
    )
    print(
        f"{'Unique parts sent for pricing':<28}: "
        f"{_stats['consolidated_mpns']}"
    )

    _missing_count = len(_stats["missing_volumes"])
    print(
        f"{'Missing volume mappings':<28}: "
        f"{_missing_count}"
    )
    if _missing_count:
        for _fg in _stats["missing_volumes"]:
            print(f"    - {_fg}")

    print(
        f"{'Cyclic BOM errors':<28}: "
        f"{_stats['cyclic_errors']}"
    )
    print(
        f"{'UOM conflicts':<28}: "
        f"{_stats['uom_conflicts']}"
    )
    print(SEP)

    sys.exit(_exit_code)