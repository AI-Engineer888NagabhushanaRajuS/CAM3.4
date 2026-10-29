"""Reshapes RFQ-scoped DuckDB rows (cbom + the 4 input tables) into the exact payload
shapes each of the 16 report-builder modules' own compute functions already expect
(documented in each module's own docstring). No business logic lives here -- this is
pure reshaping, so the already-validated compute/build functions run unchanged.

Rule of thumb used throughout: prefer sourcing every field directly from `cbom` (it
already carries the merged Scrub BOM + Quote Win fields per row); fall back to raw
`scrub_bom_items`/`quote_win` only for the handful of fields cbom doesn't carry
(Part Status, No Bid Reason, Exp Date for Missing Notes -- cbom already has exp_date but
not part_status/no_bid_reason).

Unchanged from the pre-refactor `excel_export_adapters.py` -- only the module name and
its location moved (into this package), not its logic.
"""

import re

import pandas as pd

from currency import get_default_quote_currency
from queries import detect_volumes, normalize_volume_label, selected_quote_sql

_RESERVED_CBOM_KEYS = {"summary", "validation_counts", "project_name", "total_MOQ_costs", "hierarchical_order"}


def resolve_last_volume(rfqs):
    """Port of CBOMWorkbookExport::resolveLastVolume(): max is_L1 volume_no, fallback 1.
    "proto" is never a candidate for "last volume" -- it is not a production volume and
    a bare int("proto") would crash here.
    """
    vols = [
        int(r["volume_no"]) for r in rfqs
        if r.get("is_L1") and r.get("volume_no") and str(r["volume_no"]).lower() != "proto"
    ]
    last_volume = max(vols, default=0)
    return last_volume if last_volume > 0 else 1


def extract_contract_names(cbom_json, volume):
    """Port of CBOMWorkbookExport::extractContractNames(): distinct non-Centum/CNP/Customer
    price_control labels at a given volume, natural-case-sorted."""
    names = {}
    for assembly, fg_groups in cbom_json.items():
        if assembly in _RESERVED_CBOM_KEYS:
            continue
        for items in fg_groups.values():
            if not isinstance(items, list):
                continue
            for item in items:
                for vol in item.get("volumes", []):
                    if str(vol.get("volume")) != str(volume):
                        continue
                    pc = str(vol.get("price_control") or "").strip()
                    if not pc:
                        continue
                    upper = pc.upper()
                    if upper in ("CENTUM", "CNP", "CUSTOMER"):
                        continue
                    names.setdefault(upper, pc)
    values = list(names.values())
    values.sort(key=str.casefold)
    return values


def _q(value):
    return "'" + str(value).replace("'", "''") + "'"


def _sanitize(df):
    """Replaces pandas/numpy NA sentinels (pd.NA, NaN, NaT) with plain Python None
    everywhere, including inside nullable-dtype columns (BOOLEAN/Int64/etc, which
    `.where(notnull, None)` alone doesn't fully clean) -- openpyxl's Cell.value setter
    rejects pd.NA outright, and every adapter below reads values via direct
    .get()/.iloc[] access (not just _records()), so this must happen once at load time.
    """
    return df.astype(object).where(df.notnull(), None)


def load_cbom_df(con, rfq_id):
    return _sanitize(con.execute(f"SELECT * FROM cbom_db.cbom WHERE rfq_id = {_q(rfq_id)}").df())


def load_scrub_df(con, rfq_id):
    return _sanitize(con.execute(f"SELECT * FROM input_db.scrub_bom_items WHERE rfq_id = {_q(rfq_id)}").df())


def load_quote_win_df(con, rfq_id):
    return _sanitize(con.execute(f"SELECT * FROM input_db.quote_win WHERE rfq_id = {_q(rfq_id)}").df())


def load_selected_quote_df(con, rfq_id):
    """One row per (part_number, volume_no) -- the same tie-broken/awarded quote used to
    build cbom (see queries.py's selected_quote_sql()/build_volume_tie_break_cte()) --
    instead of raw quote_win, which fans out to up to 262 rows per part_number. Recreates
    the TEMP VIEW in this connection (read-only: a view, no table writes) and filters to
    the first non-proto (numbered) volume -- the one representative "the RFQ's quote" row
    per part. PROTO is deliberately never this row: it's a pre-production sampling quote,
    not the real production quote this view feeds to Missing Notes. Falls back to
    "proto" only when no numbered volume was detected at all (a PROTO-only RFQ).
    """
    rfq_lit = _q(rfq_id)
    volumes = detect_volumes(con, rfq_lit)
    con.execute(selected_quote_sql(rfq_lit, volumes, con=con))
    numbered = [v for v in volumes if str(v).lower() != "proto"]
    first_volume = numbered[0] if numbered else "proto"
    df = _sanitize(con.execute(f"SELECT * FROM selected_quote WHERE volume_no = {_q(first_volume)}").df())
    return df


def load_selected_quote_all_volumes_df(con, rfq_id):
    """Same tie-broken `selected_quote` view as load_selected_quote_df() -- one row per
    (part_number, volume_no), the same dedup CBOM itself is built from -- but across
    EVERY detected volume, not restricted to volume_no==1. Payload builders that need one
    deduplicated quote per part PER VOLUME (Summary, Sum & Count, Price Control) must
    source from this, not raw quote_win directly: raw quote_win fans out to many rows per
    part_number (multiple supplier quotes -- confirmed up to ~12 per part, 1483 raw rows
    for 201 distinct parts, on real RFQ-000009 data), and those payload builders used to
    iterate/accumulate every raw row per volume, silently inflating every dollar total by
    however many raw quote rows happened to exist for that part -- caught by cross-
    checking BOM Matrix's Grand Total (CBOM-sourced, already tie-broken) against Summary's
    cbom_cost total for the same RFQ/volume and finding them off by roughly the average
    fan-out factor. This also incidentally fixes those payloads' pricing to use the
    already currency-converted `price_conv` column (COALESCE(cost_N_conv, price_original_N
    / rate)) instead of their previous `cost_N_conv or price_original_N` fallback, which
    read a raw, unconverted price_original when cost_N_conv was missing.
    """
    rfq_lit = _q(rfq_id)
    volumes = detect_volumes(con, rfq_lit)
    con.execute(selected_quote_sql(rfq_lit, volumes, con=con))
    return _sanitize(con.execute("SELECT * FROM selected_quote").df())


def _records(df):
    return df.to_dict("records")


def _to_bool(value):
    """cbom.new_supplier/mfg_part_num_in_scrub_bom are VARCHAR ('TRUE'/'FALSE' text, per
    the multi-source schema change) -- cast back to a real Python bool here so downstream
    Excel formulas (e.g. reports/cbom_vl.py's `$AQ=FALSE` native-boolean comparison) see
    exactly what they did before the column type changed.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().upper() == "TRUE"


# ------------------------------------------------------------------
# Shared: structural CPN exclusion, refined for "dual-role" CPNs
# ------------------------------------------------------------------

def _effective_structural_fg_cpns(cbom_df, scrub_df):
    """`structural_fg_cpns` (a CPN used as an `assembly` value elsewhere in the same FG)
    MINUS "dual-role" CPNs -- ones that are structural by that definition but ALSO carry
    their own genuine, directly-quoted price (a real quote/costing result, not a rollup)
    while their own children (rows where `assembly` == this CPN, within the same FG) sum
    to zero real cost.

    Confirmed real-data pattern (RFQ-000042): a sub-assembly can be BOTH decomposed into
    its own material breakdown in Scrub BOM (for BOM-compliance/documentation) AND
    independently quoted as one finished assembled unit -- e.g. CPN `BH96568A`
    ("BAC TRAY", commodity "Sub Assembly Mechanical") has a real quoted price, but its
    own individual mechanical piece-parts (cable tie mounts, screws, inserts, aluminum
    plate) were never separately priced (`final_price_conv` = 0 for every one of them).
    Treating `BH96568A` as a pure "container" (excluded from cost totals, no row of its
    own on A CLASS PARTS/BOM MATRIX) silently drops its ENTIRE real cost -- nothing else
    captures it, since the rollup-from-children path only applies (and only should
    apply) when the children actually carry real cost. Confirmed at scale: 17 such CPNs
    across 6 FGs in RFQ-000042, $681.58 total silently dropped from FG totals before
    this fix.

    A CPN missing this refinement remains correctly treated as a genuine "pure
    container" (only its children count, its own row excluded) -- this ONLY reclassifies
    CPNs that are structural by name but have no real rollup substance of their own.

    Mirrors (must stay in lockstep with) `reports/cbom_vl.py`'s own live "Is Assembly"
    (AH) formula, which applies the identical two-part test (structural AND own
    children's Ext Price sum <> 0) directly in Excel -- this function is the Python-side
    equivalent for the two payload builders (`to_bom_matrix_payload()`,
    `to_aclass_parts_payload()`) that decide row EXISTENCE/inclusion up front, before any
    sheet or live formula exists to filter on AH. `to_cbom_tree_payload()`'s own
    `_structural_rollup()` deliberately does NOT use this refined set -- its own
    `if v.get("price_conv"): continue` guard already leaves a dual-role CPN's real price
    untouched, and its recursion must still walk through every structural descendant
    regardless of whether that descendant is later reclassified as dual-role.
    """
    structural_fg_cpns = set(zip(scrub_df["fg"], scrub_df["assembly"])) if "assembly" in scrub_df.columns else set()
    if not structural_fg_cpns:
        return structural_fg_cpns

    data = cbom_df[cbom_df["is_data"] == True]  # noqa: E712
    ext_price = (data["part_qty"].fillna(0) * data["final_price_conv"].fillna(0)).rename("_ext_price")
    data = pd.concat([data, ext_price], axis=1)

    own_price_by_fg_cpn = data.groupby(["fg", "cpn"])["final_price_conv"].first()
    children_cost_by_fg_assembly = data.groupby(["fg", "assembly"])["_ext_price"].sum()

    dual_role = set()
    for fg, cpn in structural_fg_cpns:
        own_price = own_price_by_fg_cpn.get((fg, cpn))
        if own_price is None or pd.isna(own_price) or own_price <= 0:
            continue  # no genuine own price of its own -- a real container, stays excluded
        children_cost = children_cost_by_fg_assembly.get((fg, cpn), 0.0)
        if not children_cost:  # zero (or NaN, coalesced to 0 above) -- rollup has no real substance
            dual_role.add((fg, cpn))

    return structural_fg_cpns - dual_role


# ------------------------------------------------------------------
# BOM MATRIX
# ------------------------------------------------------------------

def to_bom_matrix_payload(cbom_df, scrub_df):
    """FG Counts / Grand Total: the real BOM quantity of this CPN in each FG, reusing
    fg_part_qty_sums() (the same (fg, cpn, mpn)-keyed sum already fixed for the CBOM VL
    sheet's Part Qty/FG Part Qty columns) -- NOT a raw row count. A CPN can have many raw
    cbom rows per FG (one per approved-alternate MPN, up to 32 observed for one real
    CPN), so counting rows (`.size()`/`.shape[0]`, the old logic) silently inflated every
    Ext Price figure and the sheet's Grand Total, causing it to disagree with every other
    report already built on the correct, deduped quantity.

    Two further confirmed real-data bugs fixed here (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md
    §6.1/§6.2):

    - Structural/in-house sub-assembly CPNs (level 1+ rows that are themselves used as an
      `assembly` value elsewhere in the same FG) previously still passed the `is_data`
      filter below (that flag only excludes each FG's own level-0 root) and were counted
      as their own purchasable matrix line -- confirmed against real data: 44 such
      assembly-role CPNs were present as line items that shouldn't have been. Excluded via
      `structural_fg_cpns` before the per-CPN groupby.
    - Conversely, each FG's own level-0 root row (`is_assembly`) was previously dropped
      entirely by that same `is_data` filter, so no FG ever got its own matrix line --
      confirmed against the expected reference workbook, which has exactly one row per FG
      (Part Number = the FG's own CPN, qty 1 in its own FG column, EAU = that FG's own
      demand). Added back explicitly after the main per-CPN loop.

    Uses `_effective_structural_fg_cpns()`, not the raw `structural_fg_cpns` set --
    excludes only genuine "pure container" structural CPNs (whose own children carry
    real cost), not "dual-role" CPNs that are structural by name but also carry their
    own genuine, directly-quoted price with no compensating children cost (see that
    function's own docstring). A dual-role CPN gets its normal matrix line here, exactly
    like any other purchased part.
    """
    data = cbom_df[cbom_df["is_data"] == True]  # noqa: E712

    structural_fg_cpns = _effective_structural_fg_cpns(cbom_df, scrub_df)
    data = data[~data.apply(lambda r: (r["fg"], r["cpn"]) in structural_fg_cpns, axis=1)]

    fg_part_qty = fg_part_qty_sums(scrub_df)
    fg_cpn_mpn = _fg_cpn_representative_mpn(scrub_df)
    cpn_bom_item_id = _cpn_representative_bom_item_id(scrub_df)
    # Per-(FG, volume) demand, computed once -- every cbom row sharing (fg, volume_no)
    # carries the identical volume_qty (a property of the FG+volume, not the individual
    # part), so first() is a safe pick, not an arbitrary one. Used for EAU below. Sourced
    # from the FULL cbom_df, not just is_data rows -- an FG with zero purchasable parts
    # (only its own root row) would otherwise never get a demand entry, leaving its own
    # new FG-level matrix row's EAU wrongly at 0 instead of that FG's real demand.
    fg_demand = cbom_df.groupby(["fg", "volume_no"])["volume_qty"].first().to_dict()
    rows = []
    for cpn, g in data.groupby("cpn", sort=False):
        fg_counts = {}
        for fg in g["fg"].unique():
            mpn = fg_cpn_mpn.get((fg, cpn))
            fg_counts[fg] = fg_part_qty.get((fg, cpn, mpn), 0)
        grand_total = sum(fg_counts.values())
        eau_volumes, mfg_name_vols, mpn_vols, unit_prices = {}, {}, {}, {}
        fg_total_costs = {}
        excess_info = {}
        rep_bom_item_id = cpn_bom_item_id.get(cpn)
        for vol_no, gv in g.groupby("volume_no"):
            key = f"VL-{vol_no}"
            # Price must come from the SAME approved-alternate-MPN row that fg_counts
            # above used as "representative" for this CPN's quantity -- gv still holds
            # every alternate-MPN's row for this CPN+volume (same many-rows-per-CPN
            # situation fg_counts already had to dedupe), and picking .iloc[0] alone
            # (pandas' arbitrary row order) can silently multiply one MPN's quantity by
            # a DIFFERENT MPN's price. Matching on bom_item_id (not the MPN string --
            # verified against real data that cbom.mfg_part_number diverges from
            # scrub_bom_items.mpn in ~22% of rows, mostly case-normalization but some
            # genuine corrected_mpn substitutions, so string equality silently misses
            # exactly the rows most likely to matter) ties back to the exact same source
            # row fg_part_qty_sums()/_fg_cpn_representative_mpn() resolved to.
            rep_rows = gv[gv["bom_item_id"] == rep_bom_item_id] if rep_bom_item_id is not None else gv.iloc[0:0]
            row0 = rep_rows.iloc[0] if not rep_rows.empty else gv.iloc[0]
            # EAU (§6.1): demand-weighted across every FG this CPN appears in, not just
            # row0's own single FG -- expected EAU = Sum(qty_fg * demand_fg). row0.get(
            # "volume_qty") (the old logic) was only ever one FG's own demand.
            eau_volumes[key] = sum(
                fg_counts.get(fg, 0) * (fg_demand.get((fg, vol_no)) or 0) for fg in fg_counts
            )
            mfg_name_vols[key] = row0.get("final_mfg_name") or "-"
            mpn_vols[key] = row0.get("mfg_part_number") or "-"
            unit_prices[key] = row0.get("final_price_conv")
            for fg in gv["fg"].unique():
                fg_total_costs.setdefault(fg, {})[key] = (row0.get("final_price_conv") or 0) * fg_counts.get(fg, 0)
            excess_info[key] = [{
                "MPN": row0.get("mfg_part_number") or "-",
                "Pkg Qty": row0.get("final_pkg_qty"), "MOQ": row0.get("final_moq"), "Lead Time": row0.get("final_lead_time"),
                "Long Comment": row0.get("long_comment") or "-", "Price Control": row0.get("price_control"),
                "NCNR": row0.get("ncnr") or "-", "Price Validity": "-", "Effective Date": "-",
                "Supp Name": row0.get("final_supp_name") or "-", "Corrected MPN": row0.get("corrected_mpn") or "-",
                "Net Excess Cost": "-",
            }]
        fg_grand_totals = {key: (unit_prices[key] or 0) * grand_total for key in eau_volumes}
        row0 = g.iloc[0]
        rows.append({
            "Part Number": cpn, "FG Counts": fg_counts, "Grand Total": grand_total,
            "EAU Volumes": eau_volumes, "Mfg Name Volumes": mfg_name_vols,
            "Mfg Part Number Volumes": mpn_vols, "Unit Prices": unit_prices,
            "FG Total Costs": fg_total_costs, "FG Grand Totals": fg_grand_totals,
            "Excess Info": excess_info,
            "Part Description": row0.get("description") or "-", "Commodity": row0.get("commodity") or "-",
        })

    # §6.2: each FG's own level-0 root row (excluded from `data` above by the is_data
    # filter) gets its own matrix line -- Part Number = the FG's own CPN, qty 1 in its
    # own FG column only, Grand Total 1, EAU = that FG's own demand (falls out of the
    # same formula above with fg_counts = {fg: 1}). Confirmed against the expected
    # reference workbook: exactly one such row per FG.
    fg_root_rows = cbom_df[cbom_df["is_assembly"] == True]  # noqa: E712
    for fg, gf in fg_root_rows.groupby("fg", sort=False):
        fg_counts = {fg: 1}
        eau_volumes = {
            f"VL-{vol_no}": fg_demand.get((fg, vol_no)) or 0
            for vol_no in gf["volume_no"].unique()
        }
        row0 = gf.iloc[0]
        rows.append({
            "Part Number": fg, "FG Counts": fg_counts, "Grand Total": 1,
            "EAU Volumes": eau_volumes, "Mfg Name Volumes": {},
            "Mfg Part Number Volumes": {}, "Unit Prices": {},
            "FG Total Costs": {}, "FG Grand Totals": {},
            "Excess Info": {},
            "Part Description": row0.get("description") or "-", "Commodity": row0.get("commodity") or "-",
        })
    return {"rows": rows}


# ------------------------------------------------------------------
# Part Num Vs Mfg Num
# ------------------------------------------------------------------

def to_part_num_vs_mfg_num_payload(scrub_df, quote_df):
    bom_details = [{"CPN": r["cpn"], "MPN": r["mpn"]} for r in _records(scrub_df[["cpn", "mpn"]])]
    rfqs = [
        {"cpn": r["part_number"], "is_L1": True, "MPN": r["mfg_part_number"]}
        for r in _records(quote_df[["part_number", "mfg_part_number"]])
    ]
    return {"bom_details_json_data": bom_details, "rfqs": rfqs}


# ------------------------------------------------------------------
# PCB NRE & FAI Charge / Mech & EM NRE
# ------------------------------------------------------------------

def to_nre_payload(scrub_df):
    bom_details = _records(scrub_df[["cpn", "commodity", "mpn", "description", "manufacturer"]].rename(
        columns={"cpn": "CPN", "commodity": "Commodity", "mpn": "MPN", "description": "Description", "manufacturer": "MFR"}
    ))
    # nre_charge is not populated anywhere in the source data (documented gap) -- no rfqs
    # qualify, matching production's own "no costed PCB/Mech parts" placeholder-row path.
    return {"bom_details_json_data": bom_details, "rfqs": []}


# ------------------------------------------------------------------
# Missing Notes
# ------------------------------------------------------------------

def to_missing_notes_payload(cbom_df, scrub_df, selected_quote_df, has_proto=False):
    """rfqs now sourced from the tie-broken `selected_quote` view (one row per
    part_number) instead of raw quote_win (up to 262 undeduplicated rows per
    part_number, confirmed against real data) -- every section built on `rfq_base`
    now sees the same single awarded/tie-broken quote the rest of the workbook (cbom)
    is built from, not an arbitrary raw-row-order pick.

    uncosted_rows is built from cbom (is_data==True, is_costed==False), replacing the
    old "no is_L1 quote_win row" check, which missed real uncosted parts (a quote can
    exist but never resolve a price -- e.g. GBP-quoted parts, since currency.py only
    defines USD/INR/EUR rates) and wrongly included the FG's own assembly-header row
    (cbom.is_data already excludes it). Reuses cbom.mfg_name/cbom.mfg_part_number,
    which are already Scrub-BOM-fallback-populated for uncosted rows (see the earlier
    "Populate MPN and Manufacturer Name for Uncosted Parts" fix). Excludes structural/
    container CPNs (see _effective_structural_fg_cpns()) -- a sub-assembly whose real
    cost is a rollup of its children is never "missing a quote" just because its own
    final_price_conv is NULL by design (confirmed real-data bug, RFQ-000128: CPNs
    38352770/38352771). Scoped to the same representative volume `rfqs` above uses,
    not every volume combined -- a part costed in that volume must not be flagged
    just because a different volume hasn't resolved a price yet.

    has_proto: threaded from exporter.py's own PROTO detection. Note this flag's actual
    meaning inside missing_notes()/build_missing_notes_sheet() is "run the volume-1-
    priced-at-zero section" -- a pre-existing legacy misnomer unrelated to whether real
    PROTO-volume data exists in this workbook. Wiring it to has_proto preserves today's
    call-site intent; it is not a fix for the misnomer itself.
    """
    bom_data = _records(scrub_df[["cpn", "mpn", "description", "commodity", "manufacturer", "part_status"]].rename(
        columns={"cpn": "CPN", "mpn": "MPN", "description": "Description", "commodity": "Commodity",
                 "manufacturer": "MFR", "part_status": "Part Status"}
    ))
    rfqs = []
    for i, r in enumerate(_records(selected_quote_df)):
        rfqs.append({
            "id": i + 1, "cpn": r.get("part_number"), "MPN": r.get("mfg_part_number"), "is_L1": True,
            "part_description": r.get("part_description"), "commodity": r.get("commodity"),
            "manufacturer_name": r.get("mfg_name"), "price_type": r.get("price_type"), "ncnr": r.get("ncnr"),
            "corrected_mpn": r.get("corrected_mpn"), "supplier_type": r.get("supplier_type"),
            "expiry_date": r.get("exp_date"), "part_status": r.get("part_status"),
        })

    uncosted_rows = []
    seen_cpns = set()

    # Structural/container CPNs (a sub-assembly used as another row's `assembly`
    # value, whose own final_price_conv is legitimately NULL because its real cost
    # is a rollup of its children -- see _effective_structural_fg_cpns()'s own
    # docstring) must never be flagged as "uncosted": they were never meant to
    # carry their own price. Confirmed real-data bug (RFQ-000128): CPNs
    # 38352770/38352771 are pure sub-assembly containers with real, individually-
    # costed children underneath them, yet showed up here because this check had
    # no structural awareness -- the exact same "container vs. real part"
    # distinction to_bom_matrix_payload()/to_aclass_parts_payload() already apply
    # via this same function.
    structural_fg_cpns = _effective_structural_fg_cpns(cbom_df, scrub_df)

    # Scoped to the same representative volume `rfqs` above is sourced from (see
    # load_selected_quote_df()'s own "first non-proto volume" convention) --
    # checking is_costed across every volume combined (the previous behavior)
    # meant a part costed in the report's own representative volume could still
    # be wrongly flagged just because a DIFFERENT volume hadn't resolved a price.
    # Falls back to the full multi-volume cbom_df if there's no quote data at all
    # for this RFQ (selected_quote_df empty) -- fail open, not fail closed.
    representative_volume = selected_quote_df["volume_no"].iloc[0] if not selected_quote_df.empty else None
    cbom_for_uncosted = (
        cbom_df[cbom_df["volume_no"] == representative_volume]
        if representative_volume is not None else cbom_df
    )

    uncosted = cbom_for_uncosted[
        (cbom_for_uncosted["is_data"] == True)  # noqa: E712
        & (cbom_for_uncosted["is_costed"] == False)  # noqa: E712
        & ~cbom_for_uncosted.apply(lambda r: (r["fg"], r["cpn"]) in structural_fg_cpns, axis=1)
    ]
    for r in _records(uncosted[["cpn", "description", "commodity", "final_mfg_name", "mfg_part_number"]]):
        cpn = r.get("cpn")
        if cpn in seen_cpns:
            continue
        seen_cpns.add(cpn)
        uncosted_rows.append({
            "id": None, "partNumber": cpn, "description": r.get("description") or "",
            "commodity": r.get("commodity") or "", "mfgName": r.get("final_mfg_name") or "-",
            "mfgPartNumber": r.get("mfg_part_number") or "", "x": "",
            "quotedMfr": "", "quotedMpn": "", "remarks": "",
        })

    return {
        "bom_data": bom_data, "smtp_details": [], "rfqs": rfqs, "include_proto": has_proto,
        "uncosted_rows": uncosted_rows,
    }


# ------------------------------------------------------------------
# Lead Time (FG Wise) / Lead Time Consolidated
# ------------------------------------------------------------------

def to_lead_time_fg_payload(cbom_df):
    """cbom is the source of truth (not raw scrub_bom_items/quote_win): sourcing from
    those directly used to pull in each FG's own assembly-header row (level='0', cpn=fg's
    own name) as a phantom quote-less "part number", inflating the blank-Lead-Time bucket
    by exactly 1 per FG (confirmed against real data). cbom.is_data==True already excludes
    those rows, and cbom.lead_time is already the correctly tie-broken/awarded value
    (raw quote_win can have many undeduplicated rows per part_number).

    PROTO rows are included alongside volume 1 -- mapped to volume_no=0 in the output
    rfqs (sorting before volume 1) to match lead_time_fg_blocks()'s own "sort ascending
    by volume_no, first lead-time value per CPN wins" convention: PROTO is
    chronologically the earliest quote, so this expresses "prefer PROTO's lead time if
    present, else fall back to volume 1" with no change to lead_time_fg.py's compute
    logic. Volume 2+ rows are still excluded -- that sort-and-take-first logic only ever
    uses ONE lead time per CPN, so any volume beyond the first available one is moot.
    """
    volume_no_str = cbom_df["volume_no"].astype(str)
    data = cbom_df[(cbom_df["is_data"] == True) & (volume_no_str.isin(["proto", "1"]))]  # noqa: E712
    bom_details = [{"CPN": r["cpn"], "FG": r["fg"]} for r in _records(data[["cpn", "fg"]])]
    rfqs = [
        {
            "cpn": r["cpn"], "is_L1": True, "lead_times": r["final_lead_time"],
            "volume_no": 0 if str(r["volume_no"]).lower() == "proto" else 1,
        }
        for r in _records(data[["cpn", "final_lead_time", "volume_no"]])
    ]
    return {"bom_details_json_data": bom_details, "rfqs": rfqs}


def to_lead_time_consolidated_payload(cbom_df):
    """Same cbom-sourced fix and PROTO handling as to_lead_time_fg_payload() -- see its
    docstring."""
    volume_no_str = cbom_df["volume_no"].astype(str)
    data = cbom_df[(cbom_df["is_data"] == True) & (volume_no_str.isin(["proto", "1"]))]  # noqa: E712
    bom_details = [{"CPN": r["cpn"]} for r in _records(data[["cpn"]])]
    rfqs = [
        {
            "cpn": r["cpn"], "is_L1": True, "lead_times": r["final_lead_time"],
            "volume_no": 0 if str(r["volume_no"]).lower() == "proto" else 1,
        }
        for r in _records(data[["cpn", "final_lead_time", "volume_no"]])
    ]
    return {"bom_details_json_data": bom_details, "rfqs": rfqs}


# ------------------------------------------------------------------
# Sum & Count / Sum & Count Detailed
# ------------------------------------------------------------------

def to_sum_and_count_payload(scrub_df, selected_quote_all_df, detected_volumes):
    """selected_quote_all_df: load_selected_quote_all_volumes_df()'s tie-broken, one-
    row-per-(part_number, volume_no) view -- NOT raw quote_win, which fans out to many
    rows per part_number and would misrepresent per-volume coverage. detected_volumes
    (queries.detect_volumes()'s result, already computed once by the caller from
    cbom_df) ensures a project-configured volume with zero quote coverage yet still gets
    its own VL-{n} column (a `cpn: None` placeholder that can never match a real scrub
    CPN, so it contributes no false coverage) instead of being silently omitted.
    Previously hardcoded every entry to volume_no=1 -- volume 2 (and beyond) coverage was
    silently dropped.

    volume_no is passed through as str(...) uniformly (never bare int) -- detected_volumes
    may now include "proto" alongside numbered volumes, and sum_and_count.py's own
    unique_volumes = sorted({...}) would raise TypeError on a mixed str/int set.
    """
    # Confirmed real-data bug (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md): sum_and_count.py/
    # sum_and_count_detailed.py sum this raw per-assembly Quantity as-is, un-multiplied by
    # how many times the assembly itself is used (e.g. "Sum & Count Detailed row 641
    # shows the raw, un-multiplied qty" for a sub-assembly used twice). Apply the
    # hierarchy multiplier here, at the payload boundary, rather than changing
    # sum_and_count*.py's own reshaping logic -- fillna(1.0) covers rows predating this
    # column (or a minimal synthetic scrub_df with no hierarchy_multiplier at all).
    if "hierarchy_multiplier" in scrub_df.columns:
        ext_quantity = scrub_df["quantity"] * scrub_df["hierarchy_multiplier"].fillna(1.0)
    else:
        ext_quantity = scrub_df["quantity"]
    scrub_items = _records(
        scrub_df[["assembly", "cpn"]].assign(quantity=ext_quantity)
        .rename(columns={"assembly": "Assembly", "cpn": "CPN", "quantity": "Quantity"})
    )
    rfqs = []
    covered_volumes = set()
    for r in _records(selected_quote_all_df):
        vol_no = r.get("volume_no")
        if vol_no is None:
            continue
        vol_no = str(vol_no)
        covered_volumes.add(vol_no)
        rfqs.append({"cpn": r.get("part_number"), "volume_no": vol_no})
    for vol_no in detected_volumes:
        vol_no = str(vol_no)
        if vol_no not in covered_volumes:
            rfqs.append({"cpn": None, "volume_no": vol_no})
    return {"scrub_bom_items": scrub_items, "rfqs": rfqs}


# ------------------------------------------------------------------
# Revision History
# ------------------------------------------------------------------

def to_revision_history_payload(rfq_id, scrub_df, quote_df):
    bom_data = _records(scrub_df[["cpn", "fg", "description", "mpn"]].rename(
        columns={"cpn": "CPN", "fg": "Assembly", "description": "Description", "mpn": "MPN"}
    ))
    rfqs = []
    for r in _records(quote_df):
        rfqs.append({
            "cpn": r.get("part_number"), "MPN": r.get("mfg_part_number"), "revision_no": "R1", "volume_no": 1,
            "vol_qty": r.get("awarded_volume_1"), "vol_pricing": r.get("cost_1_conv") or r.get("price_original_1"),
            "commodity": r.get("commodity"), "EAU": r.get("awarded_volume_1"),
            "manufacturer_name": r.get("mfg_name"), "currency": r.get("currency_original") or "USD",
        })
    return {"centum_id": rfq_id, "bom_data": bom_data, "rfqs": rfqs}


# ------------------------------------------------------------------
# A CLASS PARTS
# ------------------------------------------------------------------

def to_aclass_parts_payload(scrub_df, quote_df, cbom_df):
    """scrub_df is filtered to level != '0' before anything else here -- level='0' rows
    are each FG's own self-referential assembly-header row (cpn == fg == assembly),
    matching cbom's own is_assembly = (level = '0') convention used elsewhere (e.g.
    to_missing_notes_payload()'s precedent). Left in, these phantom "parts" have no real
    quantity/cost meaning and, because their own CPN never appears as a non-assembly row
    in the CBOM VL sheet, cause build_aclass_parts_sheet()'s per-part MATCH() lookups to
    fail -- the actual trigger for the report's #N/A cells.

    Structural sub-assembly CPNs (a CPN that is itself used as an `assembly` value
    elsewhere in the same FG) are excluded here for the identical reason as level='0'
    rows above: A CLASS PARTS is a purchased-components-only report (per explicit
    business-rule confirmation), and a structural CPN's own row on the CBOM VL sheet
    always has "Is Assembly" (AH) = TRUE, which every formula in
    build_aclass_parts_sheet() already excludes via its own `<>TRUE` MATCH/SUMIFS filter
    -- so leaving these rows in this function's own output previously produced the same
    "-"/0/#N/A-fallback garbage rows as the level='0' case, just for intermediate
    sub-assemblies instead of the FG root.

    Uses `_effective_structural_fg_cpns()` (hence the added `cbom_df` parameter), not the
    raw `structural_fg_cpns` set -- excludes only genuine "pure container" structural
    CPNs, not "dual-role" CPNs that are structural by name but also carry their own
    genuine, directly-quoted price with no compensating children cost (see that
    function's own docstring: excluding those unconditionally silently dropped their
    entire real cost, since no rollup captures it either). A dual-role CPN gets its
    normal A CLASS PARTS row here, exactly like any other purchased part -- and its live
    formulas will correctly find it once `reports/cbom_vl.py`'s own "Is Assembly" (AH)
    formula agrees (same two-part test, kept in lockstep).

    Computed from this SAME (already level-'0'-filtered) scrub_df, before any other
    computation below, so every downstream aggregate (fg_part_qty_sums()/
    hierarchy_multiplier propagation to genuine leaf parts) is keyed off of leaf rows'
    own `assembly` field, never off of a structural CPN's own now-removed row --
    excluding it here cannot change any other CPN's quantity total.
    """
    scrub_df = scrub_df[scrub_df["level"] != "0"]
    structural_fg_cpns = _effective_structural_fg_cpns(cbom_df, scrub_df)
    scrub_df = scrub_df[~scrub_df.apply(lambda r: (r["fg"], r["cpn"]) in structural_fg_cpns, axis=1)]
    bom_details = _records(scrub_df[["cpn", "fg"]].rename(columns={"cpn": "CPN", "fg": "FG"}))
    bom_data = _records(scrub_df[["fg", "assembly", "cpn", "quantity"]].rename(
        columns={"fg": "FG", "assembly": "Assembly", "cpn": "CPN", "quantity": "Quantity"}
    ))
    # Confirmed real-data bug (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md): a flat
    # scrub_df.groupby("cpn")["quantity"].sum() is FG-blind AND hierarchy-blind -- it
    # under-counts a part inside a sub-assembly used N times by that factor, same as
    # BOM MATRIX's own now-fixed bug. fg_part_qty_sums() already applies the correct
    # hierarchy multiplier per (fg, cpn); sum its per-FG totals across every FG this CPN
    # appears in to get the CPN's grand total.
    fg_qty = fg_part_qty_sums(scrub_df)
    fg_cpn_mpn = _fg_cpn_representative_mpn(scrub_df)
    total_qty_by_cpn = {}
    for (fg, cpn), mpn in fg_cpn_mpn.items():
        total_qty_by_cpn[cpn] = total_qty_by_cpn.get(cpn, 0) + fg_qty.get((fg, cpn, mpn), 0)
    rfqs = []
    supplier_names = set()
    for r in _records(quote_df):
        supp = r.get("supp_name")
        supplier_names.add(supp)
        rfqs.append({
            "cpn": r.get("part_number"), "is_L1": True, "vol_pricing": r.get("cost_1_conv") or r.get("price_original_1"),
            "total_part_qty": total_qty_by_cpn.get(r.get("part_number")), "vol_qty": r.get("awarded_volume_1"),
            "manufacturer_name": r.get("mfg_name"), "MPN": r.get("mfg_part_number"),
            "currency": r.get("currency_original") or "USD", "supplier_id": supp,
            "package_qty": r.get("pkg_qty"), "vol_moq": r.get("moq"), "lead_times": r.get("lead_time"),
            "price_control": r.get("price_type"),
        })
    suppliers = [{"id": name, "supplier_name": name} for name in supplier_names if name]
    return {"bom_details_json_data": bom_details, "bom_data": bom_data, "rfqs": rfqs, "suppliers": suppliers}


# ------------------------------------------------------------------
# Price Control
# ------------------------------------------------------------------

def to_price_control_payload(scrub_df, selected_quote_all_df, volume_rows, detected_volumes):
    """selected_quote_all_df: see to_sum_and_count_payload()'s docstring -- same tie-
    broken, one-row-per-(part_number, volume_no) source, not raw quote_win (which fans
    out to many rows per part_number and would multiply-count each part's contribution
    into price_control()'s Centum/Customer sums). detected_volumes ensures every project-
    configured volume is still represented (a `cpn: None` placeholder for any volume with
    zero real quote coverage) -- was previously hardcoded to volume_no=1, so
    price_control()'s own `last_volume = max(vols)` could never recognize volume 2+ as
    the RFQ's actual last quoted volume.

    PROTO is deliberately excluded entirely -- price_control()/build_price_control_sheet()
    are a single-last-quoted-volume design (`last_volume = max(vols)`, a fixed CBOM VL
    sheet reference), and PROTO -- a pre-production sampling price, not a competing "most
    mature volume" -- has no coherent place there. Filtered out here, upstream of
    price_control()'s own int(volume_no) casts (which would otherwise crash on "proto").
    """
    rfqs = []
    covered_volumes = set()
    for r in _records(selected_quote_all_df):
        vol_no = r.get("volume_no")
        if vol_no is None or str(vol_no).lower() == "proto":
            continue
        vol_no = int(vol_no)
        covered_volumes.add(vol_no)
        rfqs.append({
            "cpn": r.get("part_number"), "is_L1": True, "volume_no": vol_no,
            "price_control": r.get("price_type"),
            "currency": r.get("currency_original") or "USD", "vol_pricing": r.get("price_conv"),
        })
    for vol_no in detected_volumes:
        if str(vol_no).lower() == "proto":
            continue
        vol_no = int(vol_no)
        if vol_no not in covered_volumes:
            rfqs.append({"cpn": None, "is_L1": True, "volume_no": vol_no,
                         "price_control": None, "currency": "USD", "vol_pricing": None})
    bom_data = _records(scrub_df[["fg", "assembly", "cpn", "quantity"]].rename(
        columns={"fg": "FG", "assembly": "Assembly", "cpn": "CPN", "quantity": "Quantity"}
    ))
    fgcounts = []
    for row in volume_rows:
        m = re.match(r"V(\d+)$", str(row.get("volume_name", "")), re.IGNORECASE)
        if m:
            fgcounts.append({"fg": row["fg"], "volume_no": int(m.group(1)), "count": row["batch_qty"]})
    return {"rfqs": rfqs, "fgcounts": fgcounts, "bom_data": bom_data}


# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------

def to_summary_payload(rfq_id, scrub_df, selected_quote_all_df, volume_rows, detected_volumes):
    """selected_quote_all_df: load_selected_quote_all_volumes_df()'s tie-broken, one-
    row-per-(part_number, volume_no) view -- NOT raw quote_win. Raw quote_win fans out
    to many rows per part_number (multiple supplier quotes -- confirmed up to ~12 per
    part on real data); summary()'s per-FG accumulation sums every entry it's given per
    volume, so iterating raw quote_win here used to silently inflate every dollar total
    by however many raw quote rows existed per part -- caught by cross-checking against
    BOM Matrix's CBOM-sourced (already tie-broken) Grand Total for the same RFQ/volume.

    detected_volumes (queries.detect_volumes()'s result, already computed once by the
    caller from cbom_df): summary()'s own volume sections are derived entirely from
    `rfqs`' own volume_no values (not from `fgcounts`), so every detected volume gets
    represented here -- a `cpn: None` placeholder for any volume with zero real quote
    coverage -- instead of a project-configured volume silently never appearing.
    Previously hardcoded every entry to volume_no=1 -- volume 2 (and beyond) was
    silently dropped even when quote_win had real data for it.

    PROTO translation: selected_quote_all_df now carries real volume_no=='proto' rows
    once the SQL layer populates them. summary()'s own contract (see reports/summary.py)
    represents proto internally as volume_no=None (not the string "proto") and reads
    pricing from separate "proto_pricing"/"proto_qty" payload fields, not "vol_pricing"/
    "vol_qty" -- this function is the one translation point between the SQL layer's
    "proto" string convention and summary()'s None+proto_pricing convention.

    proto_qty is a single GLOBAL scalar in summary()'s contract (used uniformly for
    every FG's proto row), unlike every numbered volume's per-FG vol_qty (sourced from
    fgcounts/the volume table). Sourced the same way numbered volumes' fgcounts are --
    a real input_db.volume row for PROTO (ingestion already tolerates "PROTO Qty"/
    "Prototype Batch Qty"-style column headers) -- falling back to the first non-null
    per-part proto ext_vol_qty from selected_quote_all_df only if no such row exists.
    """
    # Confirmed real-data bug (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md): summary()'s own
    # per-FG accumulation sums this raw per-(Assembly,CPN) Quantity across every distinct
    # sub-assembly in the FG -- structurally identical to fg_part_qty_sums()'s
    # cross-assembly accumulation, just inlined, and subject to the same
    # missing-multiplier under-count whenever a shared CPN's sub-assembly is used N
    # times. Apply the multiplier at this payload boundary, same fix as
    # to_sum_and_count_payload().
    if "hierarchy_multiplier" in scrub_df.columns:
        ext_quantity = scrub_df["quantity"] * scrub_df["hierarchy_multiplier"].fillna(1.0)
    else:
        ext_quantity = scrub_df["quantity"]
    bom_data = _records(
        scrub_df[["fg", "assembly", "cpn", "inventory_stock"]].assign(quantity=ext_quantity)
        .rename(columns={"fg": "FG", "assembly": "Assembly", "cpn": "CPN", "quantity": "Quantity"})
    )
    rfqs = []
    covered_volumes = set()
    proto_qty_fallback = 0
    for r in _records(selected_quote_all_df):
        vol_no = r.get("volume_no")
        if vol_no is None:
            continue
        if str(vol_no).lower() == "proto":
            covered_volumes.add("proto")
            ext_qty = r.get("ext_vol_qty")
            if ext_qty and not proto_qty_fallback:
                proto_qty_fallback = ext_qty
            rfqs.append({
                "cpn": r.get("part_number"), "revision_no": 0, "volume_no": None,
                "currency": r.get("currency_original") or "USD",
                "proto_pricing": r.get("price_conv"), "vol_pricing": 0,
                "package_qty": r.get("pkg_qty"), "vol_moq": 0,
                "vol_qty": 0,
            })
            continue
        vol_no = int(vol_no)
        covered_volumes.add(vol_no)
        rfqs.append({
            "cpn": r.get("part_number"), "revision_no": 0, "volume_no": vol_no,
            "currency": r.get("currency_original") or "USD",
            "proto_pricing": 0, "vol_pricing": r.get("price_conv"),
            "package_qty": r.get("pkg_qty"), "vol_moq": r.get("moq"),
            "vol_qty": r.get("ext_vol_qty"),
        })
    if "proto" in detected_volumes and "proto" not in covered_volumes:
        rfqs.append({"cpn": None, "revision_no": 0, "volume_no": None,
                     "currency": "USD", "proto_pricing": 0, "vol_pricing": 0,
                     "package_qty": None, "vol_moq": None, "vol_qty": None})
    for vol_no in detected_volumes:
        if str(vol_no).lower() == "proto":
            continue
        vol_no = int(vol_no)
        if vol_no not in covered_volumes:
            rfqs.append({"cpn": None, "revision_no": 0, "volume_no": vol_no,
                         "currency": "USD", "proto_pricing": 0, "vol_pricing": None,
                         "package_qty": None, "vol_moq": None, "vol_qty": None})
    fgcounts = []
    proto_qty_from_volume_table = None
    for row in volume_rows:
        raw_name = str(row.get("volume_name", ""))
        normalized = normalize_volume_label(raw_name)
        if normalized == "proto":
            if proto_qty_from_volume_table is None and row.get("batch_qty"):
                proto_qty_from_volume_table = row["batch_qty"]
            continue
        m = re.match(r"^\d+$", normalized)
        if m:
            fgcounts.append({"fg": row["fg"], "volume_no": int(normalized), "count": row["batch_qty"]})
    proto_qty = proto_qty_from_volume_table if proto_qty_from_volume_table is not None else proto_qty_fallback
    return {"centum_id": rfq_id, "proto_qty": proto_qty, "bom_data": bom_data, "rfqs": rfqs, "fgcounts": fgcounts}


# ------------------------------------------------------------------
# Batchwise Cashflow
# ------------------------------------------------------------------

def to_batchwise_cashflow_payload(ex_inv_report_df):
    """ex_inv_report_df: ex_inv_calc's rows, computed live at export time (has its own
    supplier_type column directly -- no need to re-join against cbom for it).

    dropna=False on the volume_no groupby: pandas defaults to dropna=True, which would
    silently discard any null-volume_no row with no fallback bucket -- inconsistent with
    the explicit null-safety already given to supplier_type (.fillna() below) one line
    down. A NaN volume key is coalesced to the same "(unspecified)" label for consistency.

    vol_no can now be the string "proto" -- str(int(...)) would crash on it, so the cast
    is conditional: proto passes through as the literal key "proto" (batchwise_cashflow.py's
    own payload contract already expects a "proto" key, processed as its own section
    before the numbered volumes), any other value keeps the existing int-then-str cast.
    """
    payload = {}
    for vol_no, gv in ex_inv_report_df.groupby("volume_no", dropna=False):
        if pd.isna(vol_no):
            vol_key = "(unspecified)"
        elif str(vol_no).lower() == "proto":
            vol_key = "proto"
        else:
            vol_key = str(int(vol_no))
        bucket = {}
        for supp_type, g in gv.groupby(gv["supplier_type"].fillna("(unspecified)")):
            bucket[str(supp_type)] = {
                "buy_after_value": float(g["buy_value_after"].sum(skipna=True) or 0),
                "final_buy_value": float(g["final_buy_value"].sum(skipna=True) or 0),
                "batch_qty": float(g["batch_qty"].sum(skipna=True) or 0),
                "cpn_count": int(g["cpn"].nunique()),
            }
        payload[vol_key] = bucket
    return payload


# ------------------------------------------------------------------
# CBOM tree (7.0 CBOM VL-{n}) + Ex Inv VL (excess_inventory)
# ------------------------------------------------------------------

def fg_part_qty_sums(scrub_df):
    """FG Part Qty: for each (FG, Part Number), the SUM across every DISTINCT sub-assembly
    containing that CPN of that sub-assembly's own local quantity (fg_assembly_part_qty_sums(),
    using a PER-ASSEMBLY representative MPN -- not a single FG-wide representative MPN).
    Returns the same (FG, Part Number, MPN)-keyed dict shape existing callers already use
    (mapping every MPN that appears anywhere for that (FG, CPN) to that (FG, CPN)'s one
    correct total), so callers that resolve one representative MPN via
    _fg_cpn_representative_mpn() and look up fg_part_qty[(fg, cpn, mpn)] keep working
    unchanged -- only the computation of the total itself changed.

    NOT simply "group by (fg, cpn, mpn) and sum, then read off one representative MPN's
    group" (an earlier version of this function) -- confirmed on real data (test_2, FG
    681H33271/CPN 631F10023) that sibling sub-assemblies can use ENTIRELY DIFFERENT,
    non-overlapping alternate-MPN sets for the same physical part (three sub-assemblies,
    three completely different MPNs, quantities 2/20/8) -- a single representative MPN
    picked FG-wide only ever captures the ONE sub-assembly that happens to use it,
    silently dropping the other two (2 instead of the true 30). Summing every
    assembly's own representative-MPN local quantity, one assembly at a time, is immune to
    this regardless of whether sibling assemblies' MPN sets overlap, don't overlap, or
    partially overlap.

    Also correctly handles the earlier-fixed cases: exact duplicate BOM lines within one
    sub-assembly (via fg_assembly_part_qty_sums()'s own dedup) and alternate-MPN rows within
    one assembly repeating the same quantity (each assembly contributes its own quantity
    exactly once, via its own representative MPN, regardless of how many alternates it
    lists).

    Each assembly's own local quantity is weighted by that assembly's own
    hierarchy_multiplier (Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md) before being summed
    into the FG total -- confirmed real-data bug: a sub-assembly used N times in its own
    parent previously contributed its local qty only once, under-counting every part
    inside it by that factor (LM1785-061226-001: 3 expected, 2 produced -- 75 of 243
    parts on one FG were wrong). fg_assembly_part_qty_sums() itself is untouched -- it's
    the intentionally LOCAL, non-rolled-up quantity (CBOM VL's "Part Qty" column I);
    only the cross-assembly FG total gets the multiplier applied here.
    """
    if "assembly" not in scrub_df.columns:
        # No assembly dimension available (e.g. a minimal synthetic DataFrame) -- fall
        # back to the simple grouped sum; cross-assembly logic isn't meaningful here.
        return scrub_df.groupby(["fg", "cpn", "mpn"])["quantity"].sum().to_dict()

    assembly_qty = fg_assembly_part_qty_sums(scrub_df)  # (fg, assembly, cpn, mpn) -> local qty
    rep_mpn_per_assembly = _fg_assembly_cpn_representative_mpn(scrub_df)  # (fg, assembly, cpn) -> mpn
    multiplier_per_assembly = _fg_assembly_hierarchy_multiplier(scrub_df)  # (fg, assembly) -> multiplier

    fg_cpn_totals = {}
    for (fg, assembly, cpn), mpn in rep_mpn_per_assembly.items():
        qty = assembly_qty.get((fg, assembly, cpn, mpn), 0)
        # `or 1.0`, not `.get(..., 1.0)`: a NULL hierarchy_multiplier in the DB (e.g. rows
        # ingested before this column existed) makes the key PRESENT but mapped to None,
        # which .get()'s default never catches -- confirmed real crash on RFQ-000003's
        # data (qty * None). Both "missing key" and "present but NULL" must fall back to
        # a no-op 1.0 multiplier per _fg_assembly_hierarchy_multiplier()'s own contract.
        multiplier = multiplier_per_assembly.get((fg, assembly)) or 1.0
        fg_cpn_totals[(fg, cpn)] = fg_cpn_totals.get((fg, cpn), 0) + qty * multiplier

    result = {}
    for fg, cpn, mpn in scrub_df.groupby(["fg", "cpn", "mpn"]).groups.keys():
        result[(fg, cpn, mpn)] = fg_cpn_totals.get((fg, cpn), 0)
    return result


def _fg_assembly_hierarchy_multiplier(scrub_df):
    """One hierarchy_multiplier value per (FG, Assembly) -- every row sharing this key
    already carries the identical value (it's a pure function of (fg, assembly), computed
    once at scrub BOM ingestion time; see scrub_bom_processing.py's
    _build_hierarchy_multipliers()), so first() is a safe pick, not an arbitrary one.
    Returns {} if the column isn't present (e.g. a scrub_bom_items row predating this
    column, or a minimal synthetic DataFrame) -- callers must treat a missing key as a
    1.0 (no-op) multiplier, not an error.
    """
    if "hierarchy_multiplier" not in scrub_df.columns:
        return {}
    return scrub_df.groupby(["fg", "assembly"])["hierarchy_multiplier"].first().to_dict()


def fg_assembly_part_qty_sums(scrub_df):
    """Part Qty (7.0 CBOM VL-x, column I): the LOCAL quantity of this CPN needed by ONE
    specific sub-assembly occurrence -- SUM of Quantity across every Scrub BOM row sharing
    (FG, Assembly, Part Number, MPN), after collapsing exact duplicate rows (same fg,
    assembly, cpn, mpn, quantity all repeated -- a confirmed data/parsing anomaly, not a
    genuine additional need; same dedup fg_part_qty_sums() above applies).

    Distinct from fg_part_qty_sums() (FG Part Qty, column AW), which aggregates across
    every sub-assembly the CPN appears in within the FG -- this function preserves the
    `assembly` dimension instead of collapsing it, so a CPN shared across two sibling
    sub-assemblies gets each sub-assembly's own local quantity here, while
    fg_part_qty_sums() gives their combined total. Guarded on 'assembly' being present for
    the same reason as fg_part_qty_sums() -- returns {} if absent (no assembly dimension to
    key on).
    """
    if "assembly" not in scrub_df.columns:
        return {}
    deduped = scrub_df.drop_duplicates(subset=["fg", "assembly", "cpn", "mpn"])
    return deduped.groupby(["fg", "assembly", "cpn", "mpn"])["quantity"].sum().to_dict()


def _fg_cpn_representative_mpn(scrub_df):
    """One representative MPN per (FG, CPN) -- first-occurrence, same convention already
    used elsewhere in this file for picking a representative row out of a group. Needed to
    complete the (fg, cpn, mpn) lookup key for fg_part_qty_sums() at call sites that only
    have (fg, cpn) in scope (the CBOM VL sheet shows one row per CPN, not one per MPN). Only
    used to pick which of fg_part_qty_sums()'s (now-identical-per-(fg,cpn)) MPN keys to read
    -- never to resolve a LOCAL, per-assembly quantity (see
    _fg_assembly_cpn_representative_mpn() below for that, which must NOT use this FG-wide
    pick, since a given sub-assembly may not even list this MPN at all).
    """
    return scrub_df.groupby(["fg", "cpn"])["mpn"].first().to_dict()


def _fg_assembly_cpn_representative_mpn(scrub_df):
    """One representative MPN per (FG, Assembly, CPN) -- first-occurrence, scoped to a
    SINGLE sub-assembly (unlike _fg_cpn_representative_mpn() above, which picks one MPN for
    the whole FG). Required to correctly resolve a LOCAL, per-sub-assembly quantity from
    fg_assembly_part_qty_sums(): sibling sub-assemblies can use non-overlapping alternate-MPN
    sets for the same CPN (confirmed real case, see fg_part_qty_sums()'s docstring), so a
    single FG-wide representative MPN can silently fail to match THIS assembly's own rows at
    all, returning 0 instead of this assembly's real local quantity.
    """
    return scrub_df.groupby(["fg", "assembly", "cpn"])["mpn"].first().to_dict()


def _cpn_representative_bom_item_id(scrub_df):
    """One representative bom_item_id per CPN (first-occurrence, same convention as
    _fg_cpn_representative_mpn() above) -- CPN-level, not (FG, CPN)-level, matching the
    granularity to_bom_matrix_payload()'s unit_prices actually operates at (one price per
    CPN per volume, applied uniformly across every FG that CPN appears in). Used to pick
    the exact same source row for price that fg_part_qty_sums()/_fg_cpn_representative_mpn()
    already resolved to for quantity -- matched via bom_item_id (the real, unambiguous key
    tying a cbom row back to its source scrub_bom_items row) rather than the MPN string,
    since cbom.mfg_part_number can diverge from scrub_bom_items.mpn (case-normalization,
    corrected_mpn substitutions -- confirmed on real data).
    """
    return scrub_df.groupby("cpn")["bom_item_id"].first().to_dict()


def _norm_vol(v):
    """volume_no is now a string that may be "proto" or a numeric-looking string ("1",
    "2") -- normalize numeric strings to real int (matching this tree's existing
    int-keyed "volume" contract that cbom_vl.py/ex_inv_vl.py's _find_volume()
    equality-matches against), but leave "proto" as the literal string "proto" (also
    matched by equality, per those same modules' volume="proto" support) -- never
    int("proto").
    """
    return "proto" if str(v).lower() == "proto" else int(v)


def to_cbom_tree_payload(cbom_df, scrub_df, project_name):
    data = cbom_df[cbom_df["is_data"] == True].sort_values("display_order")  # noqa: E712
    tree = {"project_name": project_name, "summary": []}
    fg_assembly_part_qty = fg_assembly_part_qty_sums(scrub_df)  # Part Qty (I) -- local to one sub-assembly
    fg_assembly_cpn_mpn = _fg_assembly_cpn_representative_mpn(scrub_df)
    cpn_bom_item_id = _cpn_representative_bom_item_id(scrub_df)
    # Two corrections so the Assembly Summary block's Ext Price total (below) agrees
    # with to_bom_matrix_payload()'s FG Total Cost for the same FG -- confirmed real
    # discrepancy (Test_fixes/validation_files_2, RFQ-000028): both already apply to
    # to_bom_matrix_payload() (from the earlier BOM_MATRIX_QTY_ROLLUP_BUG.md fix) but
    # were never propagated here, since that fix's own validation only checked BOM
    # MATRIX against the reference workbook -- it never cross-checked BOM MATRIX
    # against this sheet's own Assembly Summary for self-consistency.
    #   1. multiplier_per_assembly: fg_part_qty_sums() (BOM MATRIX's own FG-quantity
    #      total) weights each sub-assembly's local quantity by its own
    #      hierarchy_multiplier before summing across assemblies -- this loop's own
    #      per-assembly part_qty (below) does not, so a sub-assembly used N times in
    #      its own parent silently under-multiplies this sheet's Assembly Summary
    #      Ext Price by that same factor.
    #   2. structural_fg_cpns: to_bom_matrix_payload() excludes CPNs that are
    #      themselves used as an `assembly` value elsewhere in the same FG (they're
    #      structural sub-assembly identifiers, not purchasable parts -- their own
    #      cost is already fully represented by their child parts). This loop's
    #      Assembly Summary accumulation has no equivalent exclusion, so a
    #      structural CPN's own price x quantity leaks into the FG total on top of
    #      everything nested inside it.
    # Both corrections apply ONLY to the FG-level summary accumulation
    # (fg_vol_ext_price_sum/fg_vol_ext_part_vol_price_sum) below, not to each
    # item's own per-row ext_price_conv/ext_part_vol_price_conv value -- those feed
    # cbom_vl.py's column N/O, which are immediately overwritten by that sheet's own
    # live $I*$K formula for every real data row, so the static Python value here is
    # already inert for is_data rows and must stay exactly as before.
    multiplier_per_assembly = _fg_assembly_hierarchy_multiplier(scrub_df)
    structural_fg_cpns = set(zip(scrub_df["fg"], scrub_df["assembly"])) if "assembly" in scrub_df.columns else set()

    # Ext Price / Ext Part Vol Price (Assembly Summary block, Part 5 correction): the
    # reference workbook's own per-FG summary formulas are
    #   E{r} = SUMPRODUCT($N:$N, --($A:$A=$C{r}), --($AE:$AE=$AI:$AI))   [Ext Price]
    #   G{r} = F{r}*E{r}                                                  [Ext Part Vol Price]
    # i.e. E = the SUM of the per-part-row Ext Price (Splits) column across every leaf row
    # in this FG, and G = this row's own Ext Vol Qty (F) times that same E. Column N (the
    # per-part-row Ext Price) is itself `Part Qty x Price` ($I*$K, already a correct live
    # formula on the exported sheet since the Part Qty / Ext Vol Qty fixes). So the
    # backend equivalent of E for one part is `part_qty x price_conv`, and of G is
    # `ext_vol_qty_corrected x price_conv` -- NOT r.get("ext_price_conv")/
    # r.get("ext_part_vol_price_conv") (the raw cbom columns), which are NULL for every
    # row in the real dataset because they were computed from cbom.ext_vol_qty
    # (quote_win.awarded_volume_{n}, never populated) at CBOM-generation time -- the same
    # root cause already fixed for the per-part-row Ext Vol Qty display, but not yet
    # propagated to these two derived columns until now.
    #
    # This E{r} accumulation is also exactly why `part_qty` below must be the LOCAL,
    # (FG, Assembly, CPN)-scoped quantity (fg_assembly_part_qty_sums()) and not the
    # FG-wide aggregate (fg_part_qty_sums()): E{r} sums this column across every leaf row
    # in the FG, so if `part_qty` were the FG-wide total on every row, a CPN appearing in
    # N sibling sub-assemblies would get summed N times instead of once -- confirmed as a
    # real defect (Assembly Summary overcounting a shared CPN's Ext Price once per extra
    # sub-assembly occurrence) before this fix.
    fg_vol_ext_price_sum = {}
    fg_vol_ext_part_vol_price_sum = {}

    fg_summary = {}
    for (assembly, fg), g in data.groupby(["assembly", "fg"], sort=False):
        tree.setdefault(assembly, {})
        items = []
        for cpn, gi in g.groupby("cpn", sort=False):
            row0 = gi.sort_values("display_order").iloc[0]
            # Part Qty (I) -- local to THIS (assembly, fg, cpn) row. Must use THIS
            # assembly's OWN representative MPN, not the FG-wide one above -- sibling
            # sub-assemblies can use non-overlapping alternate-MPN sets for the same CPN
            # (confirmed real case, see fg_part_qty_sums()'s docstring), so looking this
            # assembly's local quantity up under the FG-wide MPN can silently miss it
            # entirely (0) when this assembly never listed that particular MPN. Every
            # downstream use of `part_qty` below (Ext Vol Qty, Ext Price, Ext Part Vol
            # Price, Batch Qty, and this item's own "part_qty" field) intentionally keeps
            # using this local value -- that's what makes the Assembly Summary's
            # SUMPRODUCT-based Ext Price correctly sum each sub-assembly's own contribution
            # once, instead of the old FG-wide aggregate being multiplied in on every
            # occurrence row.
            local_mpn = fg_assembly_cpn_mpn.get((fg, assembly, cpn))
            part_qty = fg_assembly_part_qty.get((fg, assembly, cpn, local_mpn), 0)
            # `or 1.0`, not `.get(..., 1.0)` -- a present-but-NULL hierarchy_multiplier
            # (rows predating that column) must also fall back to a no-op multiplier, not
            # propagate None into every multiplication below.
            multiplier = multiplier_per_assembly.get((fg, assembly)) or 1.0
            # FG Part Qty (AW): Part Qty x this assembly's own hierarchy_multiplier -- NOT
            # a blind copy of Part Qty. Confirmed against the Lam Research reference
            # workbook (Test_fixes/validation_files): equal to Part Qty whenever this
            # assembly's multiplier is 1 (the common case, and what an earlier pass at
            # this fix mistook for "always equal"), but for FG=LM2853-A93171-002,
            # Assembly=LM2910-A66420-001 (hierarchy_multiplier=2.0), the reference shows
            # Part Qty=1 but FG Part Qty=2 -- exactly Part Qty x multiplier. Also what
            # makes A CLASS PARTS' own SUMIFS-over-AW total (I1/K1, matched by Part Number
            # only, across every FG/assembly) agree with this sheet's own Assembly Summary
            # TOTAL (E.../G... rows), which already applies this same multiplier per
            # assembly when accumulating fg_vol_ext_price_sum above.
            fg_part_qty_value = part_qty * multiplier
            rep_bom_item_id = cpn_bom_item_id.get(cpn)
            volumes = []
            # One representative cbom row per DISTINCT volume_no, not one per raw
            # iterrows() row: `gi` holds one cbom row per (raw Scrub BOM occurrence x
            # volume_no) -- a CPN recurring N times within this FG+assembly in Scrub BOM
            # (verified up to 54x in real data) produces N duplicate cbom rows per volume,
            # all sharing the same (already-correct, LOCAL-to-this-assembly) part_qty.
            # Iterating every raw row here would sum part_qty*price_conv N times instead
            # of once per volume --
            # a real over-counting bug caught by comparing this backend total against an
            # independent manual simulation of the exported sheet's own SUMPRODUCT formula
            # (which only ever sees one row per CPN per volume, via _find_volume()'s
            # first-match semantics -- the discrepancy is what surfaced this).
            for vol_no_raw, giv in gi.groupby("volume_no", sort=False):
                # Same fix as to_bom_matrix_payload(): `giv` can still hold multiple
                # approved-alternate-MPN rows for this CPN+volume, and .iloc[0] alone
                # would pick pandas' arbitrary row order -- not necessarily the same
                # MPN that part_qty (above) already resolved to. Match on bom_item_id
                # so this sheet's price is consistent with its own quantity, and with
                # BOM Matrix's already-fixed price for the same CPN.
                rep_rows = giv[giv["bom_item_id"] == rep_bom_item_id] if rep_bom_item_id is not None else giv.iloc[0:0]
                r = rep_rows.iloc[0] if not rep_rows.empty else giv.iloc[0]
                price_conv = r.get("final_price_conv") or 0
                # Ext Vol Qty (per-part row): reference-workbook business logic (same
                # mechanism as Batch Qty just below) -- Part Qty (this row's local,
                # (FG, Assembly, CPN)-scoped SUM(quantity) from Scrub BOM) x this
                # assembly's own hierarchy_multiplier x this FG's own Volume Qty input.
                # Confirmed against the Lam Research reference workbook
                # (Test_fixes/validation_files): for FG=LM2853-A93171-002,
                # Assembly=LM2910-A66420-001 (hierarchy_multiplier=2.0, Part Qty=1,
                # demand=608), the reference's own Ext Vol Qty is 1216 = 1 x 2 x 608, not
                # 608 -- same multiplier fix as FG Part Qty (AW) above, for the same
                # reason (A CLASS PARTS' own Ext Vol (Splits)/Ext Vol Cost totals are
                # summed from this sheet's J column across every FG/assembly, so J must
                # already be multiplier-correct for that cross-sheet total to agree with
                # this sheet's own Assembly Summary).
                # NOT r.get("ext_vol_qty") (cbom.ext_vol_qty, sourced from
                # quote_win.awarded_volume_{n}) -- that column is NULL for every row in
                # the real loaded dataset (QuoteWin export never populated Awarded
                # Volume), which is exactly why this column was blank before this fix.
                # The correct FG-level input is cbom.volume_qty (sourced from the
                # `volume` table), already fully populated.
                ext_vol_qty = part_qty * multiplier * (r.get("volume_qty") or 0)
                # Ext Price / Ext Part Vol Price: Part Qty x Price / Ext Vol Qty x Price
                # -- backend equivalent of the per-part-row live formulas ($I*$K, $J*$K)
                # already on the exported sheet; see note above the outer loop. Ext Price
                # stays local/unmultiplied (Part Qty, I, is deliberately local -- see
                # above); Ext Part Vol Price is already multiplier-adjusted via the new
                # ext_vol_qty above, so it must NOT be multiplied again below.
                ext_price_conv = part_qty * price_conv
                ext_part_vol_price_conv = ext_vol_qty * price_conv
                vol_no = _norm_vol(r["volume_no"])
                # FG-level summary accumulation only (see the two corrections noted
                # above the outer loop): skip structural CPNs entirely (their cost is
                # already represented by their own child parts). ext_price_conv is
                # local/unmultiplied so needs `* multiplier` applied here;
                # ext_part_vol_price_conv already carries the multiplier via ext_vol_qty,
                # so it must NOT be multiplied again.
                if (fg, cpn) not in structural_fg_cpns:
                    fg_vol_ext_price_sum[(fg, vol_no)] = fg_vol_ext_price_sum.get((fg, vol_no), 0) + ext_price_conv * multiplier
                    fg_vol_ext_part_vol_price_sum[(fg, vol_no)] = fg_vol_ext_part_vol_price_sum.get((fg, vol_no), 0) + ext_part_vol_price_conv
                volumes.append({
                    "volume": vol_no, "manufacturerName": r.get("final_mfg_name"), "MPN": r.get("mfg_part_number"),
                    "UOM": r.get("final_unit_of_measure"),
                    "ext_vol_qty": ext_vol_qty,
                    "price_conv": r.get("final_price_conv"),
                    "price_original": r.get("final_price_original"), "currency": r.get("final_currency_original"),
                    "ext_price_conv": ext_price_conv, "ext_part_vol_price_conv": ext_part_vol_price_conv,
                    "supplierName": r.get("final_supp_name"), "packageQty": r.get("final_pkg_qty"), "MOQ": r.get("final_moq"),
                    "leadTime": r.get("final_lead_time"), "nre_charge": r.get("nre_charge"), "nre_charge_conv": r.get("nre_charge"),
                    "NCNR": r.get("ncnr"), "price_control": r.get("price_control"), "long_comment": r.get("long_comment"),
                    "price_type": r.get("price_type"), "expiry_date": str(r.get("exp_date")) if r.get("exp_date") else "",
                    "MFRinScrubBOM": r.get("mfr_in_customer_bom"), "corrected_mpn": r.get("corrected_mpn"),
                    "supplierType": r.get("supplier_type"), "isData": True,
                    # Batch Qty (per-part row): reference-workbook business logic (verified
                    # against the real formula, see reports/cbom_vl.py's build_cbom_vl_sheet
                    # docstring) -- Part Qty (this row's local, (FG, Assembly, CPN)-scoped
                    # SUM(quantity) from Scrub BOM) x this assembly's own hierarchy_multiplier
                    # x the FG-level Batch Qty (this row's raw cbom.batch_qty, itself sourced
                    # from the `batch` input table for this fg/volume) -- same multiplier fix
                    # as Ext Vol Qty above, same reason (mirrors the identical
                    # "$I * INDEX($H:$H,...)" formula pattern in cbom_vl.py, just against the
                    # Assembly Summary's Batch Qty column instead of its Ext Vol Qty column).
                    "batch_qty": part_qty * multiplier * (r.get("batch_qty") or 0),
                    "ABC_classification": r.get("abc_classification"), "scrap_percent": r.get("scrap_percent"),
                    "isCosted": bool(r.get("is_costed")), "isMoqPresent": bool(r.get("moq_qty_present")),
                    "isPkgQtyPresent": bool(r.get("pkg_qty_present")),
                    "pckQtyVsMoq": bool(r.get("pkg_qty_lte_moq")),
                    "new_supplier": _to_bool(r.get("new_supplier")), "isPriceSame": r.get("is_price_same"),
                    "isMPNSame": r.get("is_mpn_same"), "isMFGpartNumberInScrubBOM": _to_bool(r.get("mfg_part_num_in_scrub_bom")),
                })
            items.append({
                "FG": fg, "CPN": cpn, "part_description": row0.get("description"), "commodity": row0.get("commodity"),
                # FG Part Qty (AW): per explicit business-rule confirmation against the Lam
                # Research reference workbook (Test_fixes/validation_files,
                # CE-005603...Internal...xlsx, CBOM VL-1 col AZ) -- Part Qty (I) x this
                # assembly's own hierarchy_multiplier (see fg_part_qty_value above), NOT a
                # sum of this CPN's quantity across every sub-assembly in the FG
                # (fg_part_qty_sums()) as previously implemented, and NOT a blind copy of
                # Part Qty either. BOM MATRIX's own "FG Counts"/"Grand Total"
                # (to_bom_matrix_payload(), a DIFFERENT, FG-wide-aggregate concept) is
                # unaffected by this change.
                "part_qty": part_qty, "fg_part_qty": fg_part_qty_value, "line_no": row0.get("line_no"), "isAssembly": False,
                "assembly_group_path": None, "recurring_count": row0.get("recurring_count"),
                "isMFGpartNumberInScrubBOM": _to_bool(row0.get("mfg_part_num_in_scrub_bom")),
                "isPriceSame": row0.get("is_price_same"), "isMPNSame": row0.get("is_mpn_same"),
                "new_supplier": _to_bool(row0.get("new_supplier")),
                "volumes": volumes,
            })
        tree[assembly][fg] = items

    # Structural CPN price rollup: confirmed against the Lam Research reference
    # workbook (Test_fixes/validation_files) that a structural CPN's own row (a
    # sub-assembly identifier used as an `assembly` value elsewhere in the same FG --
    # never priced by QuoteWin, since it isn't a real purchasable part) is expected to
    # show a real, nonzero price: the SUM of every purchasable descendant's
    # ext_price_conv nested underneath it (recursively, if a descendant is itself
    # structural). Verified numerically for CPN "LM2810-141736-005" (FG
    # "LM2853-243695-006", nested 4 levels deep via _SS/_TH/_SMT child sub-assemblies):
    # summing ext_price_conv across every leaf item nested underneath gives
    # 244.37299256280414, matching the reference's own cached price for that exact row
    # (244.37299256280426, differing only in floating-point noise). Without this, every
    # structural CPN's own row is left with NO price at all, incorrectly marking it
    # "Uncosted" (confirmed: all 46 of RFQ-000032's Is-Costed mismatches against the
    # reference were structural CPNs missing exactly this rollup).
    #
    # This must run as a POST-PROCESSING pass after every (assembly, fg) group above has
    # already built its own items -- a structural CPN's rollup needs its children's
    # OWN final prices already resolved (which may themselves be rollups, for a
    # multi-level-nested structural CPN), so it can't be computed inline during the
    # single top-down pass above.
    _rollup_cache = {}

    def _structural_rollup(fg, cpn, vol_no):
        """Cost of ONE UNIT of structural CPN `cpn` in FG `fg`, in both the quote
        currency (K, Price Splits) and the original currency (L, Price Original) --
        the sum of every purchasable descendant's own ext_price_conv/ext_price_original
        nested under assembly==cpn, recursing into any descendant that is itself
        structural. Memoized per (fg, cpn, vol_no) since the same structural CPN can be
        reused under multiple parents within one FG. `_rollup_cache` also acts as a
        cycle guard (seeded before recursing) -- a malformed BOM with a circular
        assembly reference must not infinite-loop.

        Returns (converted_total, original_total, original_currency). original_currency
        is the single currency every descendant shares, or None if descendants are
        priced in more than one currency (a real case in this data -- confirmed both
        USD and INR appear across RFQ-000032's priced rows) -- an "original price"
        summed across mixed currencies isn't a meaningful number, so callers must treat
        a None currency as "no valid original-currency total available" and fall back
        to displaying the converted total under the quote currency instead.
        """
        key = (fg, cpn, vol_no)
        if key in _rollup_cache:
            return _rollup_cache[key]
        _rollup_cache[key] = (0.0, 0.0, False)  # False sentinel = cycle guard, not a real currency
        total_conv, total_orig = 0.0, 0.0
        currency = False
        for child_item in tree.get(cpn, {}).get(fg, []):
            child_cpn = child_item.get("CPN")
            child_v = next((vv for vv in child_item.get("volumes", []) if vv.get("volume") == vol_no), None)
            if child_v is None:
                continue
            if (fg, child_cpn) in structural_fg_cpns:
                child_conv, child_orig, child_currency = _structural_rollup(fg, child_cpn, vol_no)
            else:
                child_conv = child_v.get("ext_price_conv") or 0
                # Ext price in the ORIGINAL currency: this child's own local part_qty x
                # its own (unconverted) unit price -- parallel to ext_price_conv, just
                # using price_original instead of price_conv.
                child_part_qty = child_item.get("part_qty") or 0
                child_orig = child_part_qty * (child_v.get("price_original") or 0)
                child_currency = child_v.get("currency")
            total_conv += child_conv
            total_orig += child_orig
            if currency is False:
                currency = child_currency
            elif currency != child_currency:
                currency = None  # mixed currencies among descendants -- no single valid total
        result = (total_conv, total_orig, currency if currency is not False else None)
        _rollup_cache[key] = result
        return result

    _quote_currency = get_default_quote_currency()
    for assembly, fgs in tree.items():
        if assembly in ("project_name", "summary"):
            continue
        for fg, items in fgs.items():
            for item in items:
                cpn = item.get("CPN")
                if (fg, cpn) not in structural_fg_cpns:
                    continue
                part_qty = item.get("part_qty") or 0
                for v in item.get("volumes", []):
                    if v.get("price_conv"):
                        continue  # already genuinely priced -- leave untouched
                    rolled_price, rolled_original, rolled_currency = _structural_rollup(fg, cpn, v.get("volume"))
                    if not rolled_price:
                        continue
                    v["price_conv"] = rolled_price
                    v["ext_price_conv"] = part_qty * rolled_price
                    v["ext_part_vol_price_conv"] = (v.get("ext_vol_qty") or 0) * rolled_price
                    v["isCosted"] = True
                    # Price (Splits) (K) on the exported sheet is a live currency-
                    # conversion formula computed from price_original (L) and currency
                    # (M), NOT from price_conv directly -- price_conv alone (set above)
                    # never reaches the real cell. L and M must independently be a
                    # correct (price, currency) pair such that converting L from M into
                    # the quote currency reproduces price_conv exactly -- confirmed real
                    # business requirement: L must be the genuinely-summed original-
                    # currency total (mirroring K's own summation), not a copy of K.
                    #
                    # This is only mathematically valid when every descendant nested
                    # under this structural CPN shares ONE original currency (summing
                    # raw amounts across different currencies is meaningless) --
                    # confirmed a real case in this data (both USD and INR appear across
                    # RFQ-000032's priced rows). When descendants are uniform,
                    # rolled_currency carries that shared currency and L/M correctly
                    # reproduce K via the live conversion formula. When they're mixed,
                    # _structural_rollup() returns rolled_currency=None -- fall back to
                    # expressing the rollup directly in the quote currency (same value
                    # as K, conversion becomes a no-op), since there's no single
                    # meaningful "original" figure to show in that case.
                    if rolled_currency is not None:
                        v["price_original"] = rolled_original
                        v["currency"] = rolled_currency
                    else:
                        v["price_original"] = rolled_price
                        v["currency"] = _quote_currency

    # fg_summary is built in a SEPARATE pass, grouped by (fg, volume_no) directly -- not
    # nested inside the (assembly, fg) loop above. An FG can span multiple Assemblies
    # (verified in real data: up to 8 distinct assemblies feeding one FG), so building
    # this per-(assembly, fg) iteration would append multiple duplicate volume entries
    # for the same (fg, volume_no) -- one per assembly -- each reading
    # fg_vol_ext_price_sum mid-accumulation (before assemblies processed later in
    # iteration order had contributed), silently under-counting. Grouping by (fg,
    # volume_no) here, after the accumulator above is fully populated across every
    # assembly, gives exactly one summary entry per (fg, volume_no) with the complete sum.
    for (fg, vol_no), gfv in data.groupby(["fg", "volume_no"], sort=False):
        vol_no = _norm_vol(vol_no)
        # Description: intentionally always blank on the CBOM VL Assembly Summary block
        # (per explicit business requirement) -- not derived from the scrub BOM row.
        fg_summary.setdefault(fg, {"FG": fg, "Description": "", "volumes": []})
        fg_summary[fg]["volumes"].append({
            "volume": vol_no,
            "ext_price_conv": fg_vol_ext_price_sum.get((fg, vol_no), 0),
            "ext_vol_qty": gfv.iloc[0].get("volume_qty"),
            "ext_part_vol_price_conv": fg_vol_ext_part_vol_price_sum.get((fg, vol_no), 0),
            # Assembly Summary's own Batch Qty stays the RAW per-FG value (unmultiplied)
            # -- it's the input the per-part-row Batch Qty formula looks up FROM, not
            # itself derived from Part Qty.
            "batch_qty": gfv.iloc[0].get("batch_qty"),
        })
    tree["summary"] = list(fg_summary.values())
    return tree


def to_excess_inventory_payload(cbom_df, scrub_df):
    """excess_in_stk is real inventory data (scrub_bom_items.inventory_stock), not a
    placeholder -- resolved via the same (cpn -> inventory_stock) mapping Ex Inv VL's own
    SQL (ex_inv_calc) already uses, kept in sync with it rather than re-derived differently.
    """
    inv_by_cpn = scrub_df.groupby("cpn")["inventory_stock"].max().to_dict()
    data = cbom_df[cbom_df["is_data"] == True]  # noqa: E712
    out = []
    for cpn, g in data.groupby("cpn", sort=False):
        row0 = g.iloc[0]
        excess_in_stk = inv_by_cpn.get(cpn) or 0
        volumes = [
            {"volume": _norm_vol(r["volume_no"]), "excess_in_stk": excess_in_stk}
            for _, r in g.iterrows()
        ]
        out.append({
            "CPN": cpn, "commodity": row0.get("commodity"), "part_description": row0.get("description"),
            "part_qty": row0.get("part_qty"), "volumes": volumes,
        })
    return out


def _demo():
    # Ticket's own example table: same (FG, CPN, MPN) rows from DIFFERENT sub-assemblies
    # get summed together for the FG-wide total (fg_part_qty_sums / FG Part Qty); a
    # different MPN under the same (FG, CPN) forms a separate group and must not merge.
    # CPN "ABC123"/MPN-A appears in two distinct sub-assemblies (SUB-A qty=2, SUB-B
    # qty=3) -- the regression fixture this ticket asked for: one FG, multiple
    # sub-assemblies, a shared CPN, different local quantities per sub-assembly.
    scrub_df = pd.DataFrame([
        {"fg": "ASM-1", "assembly": "SUB-A", "cpn": "ABC123", "mpn": "MPN-A", "quantity": 2},
        {"fg": "ASM-1", "assembly": "SUB-B", "cpn": "ABC123", "mpn": "MPN-A", "quantity": 3},
        {"fg": "ASM-1", "assembly": "SUB-A", "cpn": "ABC123", "mpn": "MPN-B", "quantity": 5},
        {"fg": "ASM-1", "assembly": "SUB-A", "cpn": "XYZ999", "mpn": "MPN-C", "quantity": 4},
    ])
    sums = fg_part_qty_sums(scrub_df)
    assert sums[("ASM-1", "ABC123", "MPN-A")] == 5  # SUB-A(2) + SUB-B(3), summed across sub-assemblies
    assert sums[("ASM-1", "ABC123", "MPN-B")] == 5
    assert sums[("ASM-1", "XYZ999", "MPN-C")] == 4
    print("fg_part_qty_sums() (fg, cpn, mpn) grouping self-check passed")

    rep_mpn = _fg_cpn_representative_mpn(scrub_df)
    assert rep_mpn[("ASM-1", "ABC123")] == "MPN-A"  # first occurrence
    part_qty = sums.get(("ASM-1", "ABC123", rep_mpn.get(("ASM-1", "ABC123"))), 0)
    assert part_qty == 5  # not 10 -- must not merge MPN-A and MPN-B together
    print("representative-MPN lookup self-check passed")

    # Part Qty (local to one sub-assembly) must differ per sub-assembly, even though FG
    # Part Qty (above) correctly aggregates them -- this is the ticket's core assertion:
    # Part Qty differs per occurrence row; FG Part Qty equals the summed quantity.
    assembly_sums = fg_assembly_part_qty_sums(scrub_df)
    assert assembly_sums[("ASM-1", "SUB-A", "ABC123", "MPN-A")] == 2
    assert assembly_sums[("ASM-1", "SUB-B", "ABC123", "MPN-A")] == 3
    assert assembly_sums[("ASM-1", "SUB-A", "ABC123", "MPN-A")] != sums[("ASM-1", "ABC123", "MPN-A")]
    print("fg_assembly_part_qty_sums() local-vs-aggregate self-check passed")

    # Exact duplicate BOM line within a single sub-assembly (same fg, assembly, cpn, mpn,
    # AND quantity all repeated) -- confirmed real-data anomaly, must be counted once, not
    # summed twice, at both the local and FG-wide level.
    dup_df = pd.DataFrame([
        {"fg": "ASM-2", "assembly": "SUB-C", "cpn": "DUP001", "mpn": "MPN-D", "quantity": 3},
        {"fg": "ASM-2", "assembly": "SUB-C", "cpn": "DUP001", "mpn": "MPN-D", "quantity": 3},
    ])
    assert fg_part_qty_sums(dup_df)[("ASM-2", "DUP001", "MPN-D")] == 3  # not 6
    assert fg_assembly_part_qty_sums(dup_df)[("ASM-2", "SUB-C", "DUP001", "MPN-D")] == 3  # not 6
    print("exact-duplicate-row dedup self-check passed")

    # Sibling sub-assemblies using COMPLETELY NON-OVERLAPPING alternate-MPN sets for the
    # same CPN -- confirmed real case (test_2, FG 681H33271/CPN 631F10023: three
    # sub-assemblies, three entirely different MPNs, quantities 2/20/8). A single
    # FG-wide representative MPN can only ever match ONE of these sub-assemblies, so the
    # FG-wide total must come from summing each assembly's OWN representative MPN's local
    # quantity, not from grouping by one shared MPN across the whole FG.
    no_overlap_df = pd.DataFrame([
        {"fg": "ASM-3", "assembly": "SUB-D", "cpn": "SHARED1", "mpn": "MPN-X", "quantity": 2},
        {"fg": "ASM-3", "assembly": "SUB-E", "cpn": "SHARED1", "mpn": "MPN-Y", "quantity": 20},
        {"fg": "ASM-3", "assembly": "SUB-F", "cpn": "SHARED1", "mpn": "MPN-Z", "quantity": 8},
    ])
    no_overlap_sums = fg_part_qty_sums(no_overlap_df)
    assert no_overlap_sums[("ASM-3", "SHARED1", "MPN-X")] == 30  # 2 + 20 + 8, not just 2
    assert no_overlap_sums[("ASM-3", "SHARED1", "MPN-Y")] == 30  # same total under every MPN key
    assert no_overlap_sums[("ASM-3", "SHARED1", "MPN-Z")] == 30
    no_overlap_local = fg_assembly_part_qty_sums(no_overlap_df)
    assert no_overlap_local[("ASM-3", "SUB-D", "SHARED1", "MPN-X")] == 2
    assert no_overlap_local[("ASM-3", "SUB-E", "SHARED1", "MPN-Y")] == 20
    assert no_overlap_local[("ASM-3", "SUB-F", "SHARED1", "MPN-Z")] == 8
    print("non-overlapping-alternate-MPN-sets self-check passed")

    # Lead Time payloads must exclude the FG's own assembly-header row (is_data=False)
    # and any other-volume rows -- the exact bug this fixed (a phantom quote-less "part
    # number" per FG that inflated the blank-Lead-Time bucket by +1 per FG).
    cbom_df = pd.DataFrame([
        {"cpn": "ASM-1", "fg": "ASM-1", "final_lead_time": None, "is_data": False, "volume_no": 1},  # header row
        {"cpn": "ABC123", "fg": "ASM-1", "final_lead_time": 8.0, "is_data": True, "volume_no": 1},
        {"cpn": "XYZ999", "fg": "ASM-1", "final_lead_time": None, "is_data": True, "volume_no": 1},
        {"cpn": "ABC123", "fg": "ASM-1", "final_lead_time": 8.0, "is_data": True, "volume_no": 2},  # other volume
    ])
    fg_payload = to_lead_time_fg_payload(cbom_df)
    assert len(fg_payload["bom_details_json_data"]) == 2  # header row + other-volume row excluded
    assert {d["CPN"] for d in fg_payload["bom_details_json_data"]} == {"ABC123", "XYZ999"}
    cons_payload = to_lead_time_consolidated_payload(cbom_df)
    assert len(cons_payload["bom_details_json_data"]) == 2
    print("to_lead_time_fg_payload() / to_lead_time_consolidated_payload() cbom-filter self-check passed")

    # PROTO rows are included alongside volume 1 -- mapped to volume_no=0 (sorts before
    # volume 1's volume_no=1 in lead_time_fg_blocks()'s "earliest lead time wins" logic).
    cbom_df_proto = pd.DataFrame([
        {"cpn": "ABC123", "fg": "ASM-1", "final_lead_time": 3.0, "is_data": True, "volume_no": "proto"},
        {"cpn": "ABC123", "fg": "ASM-1", "final_lead_time": 8.0, "is_data": True, "volume_no": "1"},
        {"cpn": "XYZ999", "fg": "ASM-1", "final_lead_time": None, "is_data": True, "volume_no": "1"},
        {"cpn": "ABC123", "fg": "ASM-1", "final_lead_time": 8.0, "is_data": True, "volume_no": "2"},  # excluded
    ])
    fg_payload_proto = to_lead_time_fg_payload(cbom_df_proto)
    assert len(fg_payload_proto["bom_details_json_data"]) == 3  # proto + V1 rows, V2 excluded
    proto_rfq = next(r for r in fg_payload_proto["rfqs"] if r["lead_times"] == 3.0)
    assert proto_rfq["volume_no"] == 0
    print("to_lead_time_fg_payload() PROTO-inclusion self-check passed")


if __name__ == "__main__":
    _demo()
