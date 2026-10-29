"""SQL-building functions for the CBOM insert, the erp/costing_sheet enrichment updates,
the QuoteWin tie-break view, the Ex Inv VL calculation view, and all 16 report inserts.
Every function returns a SQL string (or a list/dict of them); nothing here executes a
query directly -- that's database.py's/cbom_generator.py's/enrichment.py's/
report_generator.py's job. Keeping the SQL text itself in one place makes it easy to
audit exactly what each report/column computes without wading through control-flow code.

cbom_insert_sql() populates structure + _qw columns only (from scrub_bom_items/volume/
batch/quote_win) -- _costing/_erp columns are left NULL there, same as final_*.
erp_enrichment_sql()/costing_enrichment_sql() fill those in afterward, as a separate
UPDATE-based stage against already-existing cbom rows (see enrichment.py). This 3-stage
split (cbom -> enrich_erp -> enrich_costing_sheet, each its own MCP tool) replaces the
single do-everything INSERT this module originally used, and replaces the retired
cbom_enrichment.py script -- see deprecated/cbom_enrichment.py.deprecated for why that
script was retired instead of kept.

All quote_win/costing_sheet part-number joins are case-insensitive (UPPER() on both
sides) -- real data has shown casing drift between sources (e.g. costing_sheet.part_number
arriving all-uppercase while scrub_bom_items.cpn keeps its original mixed case), and an
exact-case join silently drops matching rows with no error.
"""

import re

from currency import build_rate_case_sql
from scrap_factor import build_scrap_class_case_sql, build_scrap_percent_case_sql


def normalize_volume_label(raw):
    """Case/whitespace-insensitive volume-label normalization, applied once before any
    report generation, shared by both the SQL layer (_normalize_volume_sql() below) and
    the Python payload-builder layer (templates/excel_mappings.py imports this directly
    -- do not reimplement). PROTO/Prototype/prototype/'Prototype Build' -> 'proto';
    'V1'/'v1' -> '1', 'V2' -> '2', etc; anything else is passed through as str(raw)
    (trimmed), so an already-normalized value ("1", "proto") round-trips unchanged."""
    s = str(raw).strip().lower()
    if s == "proto" or s.startswith("prototype"):
        return "proto"
    m = re.match(r"^v(\d+)$", s)
    return m.group(1) if m else str(raw).strip()


def _normalize_volume_sql(column):
    """SQL mirror of normalize_volume_label(), for use inside queries that read a raw
    volume label straight from input_db.volume/batch (e.g. 'PROTO', 'Prototype Build',
    'V1') and need to compare it against an already-normalized identifier."""
    trimmed = f"TRIM({column})"
    return (
        f"CASE WHEN LOWER({trimmed}) = 'proto' OR LOWER({trimmed}) LIKE 'prototype%' THEN 'proto' "
        f"WHEN REGEXP_MATCHES(LOWER({trimmed}), '^v[0-9]+$') THEN REGEXP_REPLACE(LOWER({trimmed}), '^v', '') "
        f"ELSE {trimmed} END"
    )


def _normalize_mpn_sql(column):
    """SQL mirror of a leading-zero-insensitive MPN comparison key: confirmed against
    the Lam Research reference workbook (Test_fixes/validation_files) that
    "Wrong MPNs w.r.t Scrub BOM" must treat e.g. QuoteWin's "13" and Scrub BOM's
    "000013" as the SAME MPN -- Excel silently strips leading zeros from a numeric-
    looking cell on entry/export, so the same physical part number can arrive with or
    without them depending on which system last touched it, and a bare string
    comparison flags this as a genuine mismatch when it isn't one.

    Only affects PURELY NUMERIC MPNs (every character 0-9) -- an alphanumeric MPN
    (e.g. "A013") is compared exactly as before (trimmed + uppercased, no numeric
    reinterpretation), since stripping leading zeros only makes sense once a value is
    known to be a plain integer, not an arbitrary part-number string that merely
    contains digits.
    """
    trimmed = f"TRIM({column})"
    return (
        f"CASE WHEN REGEXP_MATCHES({trimmed}, '^[0-9]+$') "
        f"THEN CAST(TRY_CAST({trimmed} AS BIGINT) AS VARCHAR) "
        f"ELSE UPPER({trimmed}) END"
    )


def _order_volumes(vols):
    """proto first (if present), then ascending numeric order for every numbered
    volume -- the shared "proto-first" ordering every consumer of detect_volumes()'s
    result relies on (CBOM/Ex Inv VL tab order, Summary/BOM Matrix column order)."""
    def key(v):
        if v == "proto":
            return (0, 0)
        try:
            return (1, int(v))
        except ValueError:
            return (2, str(v))
    return sorted(vols, key=key)


def volume_quote_win_slots(volumes):
    """Positional slot mapping onto quote_win's fixed cost_N_conv-style columns:
    quote_win has no PROTO-specific columns, so PROTO's pricing is read from whichever
    slot it physically occupies. volumes must already be proto-first ordered (see
    _order_volumes()) -- when PROTO is present it occupies slot 1 and every numbered
    volume's slot shifts right by one (e.g. ["proto","1","2"] -> {"proto":1,"1":2,"2":3});
    when PROTO is absent, slot N == volume N unchanged (["1","2"] -> {"1":1,"2":2})."""
    return {vol: i + 1 for i, vol in enumerate(volumes)}


def build_volume_tie_break_cte(volumes, slot_map, quote_win_ref="input_db.quote_win"):
    """One UNION ALL branch per detected volume: prefer the awarded quote for that
    volume, else the lowest resolved cost -- the confirmed CBOM build tie-break rule.

    `volumes` are physical volume identifiers ("proto", "1", "2", ...); `slot_map`
    (see volume_quote_win_slots()) resolves each to the quote_win column suffix it
    should actually read from -- these are no longer the same number once PROTO can
    occupy slot 1.

    Selects every original quote_win column (via q.*) plus the resolved
    volume-specific fields, so ANY report needing "the" quote for a part (the
    functional equivalent of an is_L1-filtered rfqs row -- there is no such flag in the
    quote_win schema) can join this view instead of raw quote_win directly. Joining raw
    quote_win directly fans out badly on real data (up to 262 supplier quotes for one
    part observed in testing) -- every report uses this view for exactly that reason.
    """
    branches = []
    for vol in volumes:
        slot = slot_map[vol]
        vol_lit = str(vol).replace("'", "''")
        branches.append(f"""
        SELECT
            q.*,
            '{vol_lit}' AS volume_no,
            price_original_{slot} AS price_original,
            COALESCE(cost_{slot}_conv, price_original_{slot} / NULLIF({build_rate_case_sql()}, 0)) AS price_conv,
            awarded_volume_{slot} AS ext_vol_qty,
            ROW_NUMBER() OVER (
                PARTITION BY part_number
                ORDER BY (award_{slot} IS NULL) ASC,
                         COALESCE(cost_{slot}_conv, price_original_{slot} / NULLIF({build_rate_case_sql()}, 0)) ASC NULLS LAST
            ) AS rn
        FROM {quote_win_ref} q
        WHERE cost_{slot}_conv IS NOT NULL OR price_original_{slot} IS NOT NULL OR award_{slot} IS NOT NULL
        """)
    return " UNION ALL ".join(branches)


def selected_quote_sql(rfq_lit, volumes, con=None):
    """volumes: every physical volume detect_volumes() found ("proto", "1", "2", ...),
    proto-first ordered. QuoteWin's schema only ever defines a fixed set of
    volume-suffixed columns (currently cost_1_conv/cost_2_conv) -- an RFQ can have more
    physical volumes than that (confirmed on real data: V1/V2/V3 in volume/batch, but
    quote_win schema capped at 2), which would make build_volume_tie_break_cte()
    reference a cost_N_conv column that doesn't exist and error. When `con` is given,
    volumes whose positional slot (see volume_quote_win_slots()) has no corresponding
    quote_win columns are silently dropped from this view -- cbom_insert_sql()'s own
    LEFT JOIN against this view already degrades a missing volume to NULL pricing
    gracefully, which is the honest answer for a volume QuoteWin was never able to
    quote in the first place.
    """
    slot_map = volume_quote_win_slots(volumes)
    quote_win_volumes = volumes
    if con is not None:
        available = _quote_win_volume_suffixes(con)
        filtered = [v for v in volumes if slot_map[v] in available]
        # Degenerate fallback (quote_win schema has no cost/award columns at all, which
        # shouldn't happen in practice) -- keep the original list rather than building an
        # empty, invalid VALUES clause.
        quote_win_volumes = filtered or volumes
    tie_break_sql = build_volume_tie_break_cte(
        quote_win_volumes, slot_map,
        quote_win_ref=f"(SELECT * FROM input_db.quote_win WHERE rfq_id = {rfq_lit})",
    )
    return f"CREATE OR REPLACE TEMP VIEW selected_quote AS SELECT * FROM ({tie_break_sql}) t WHERE rn = 1;"


_QUOTE_WIN_VOLUME_COL_RE = re.compile(r"^(?:cost_(\d+)_conv|price_original_(\d+)|awarded_volume_(\d+)|award_(\d+))$")


def _quote_win_volume_suffixes(con):
    """Discovers every volume-suffixed quote_win column (cost_N_conv/price_original_N/
    awarded_volume_N/award_N) that actually exists right now, via DESCRIBE -- the same
    column-introspection convention already used by database.py's _column_type() and
    migrations.py -- instead of a hardcoded range. build_volume_tie_break_cte()/
    cbom_insert_sql()/selected_quote_sql() are already fully parametric over however many
    volume numbers detect_volumes() returns, so this is the one place that needs to keep
    up automatically if quote_win ever grows past its current 2 volume-suffixed columns.
    """
    suffixes = set()
    for row in con.execute("DESCRIBE input_db.quote_win").fetchall():
        m = _QUOTE_WIN_VOLUME_COL_RE.match(str(row[0]))
        if m:
            suffixes.add(int(next(g for g in m.groups() if g is not None)))
    return suffixes


def detect_volumes(con, rfq_lit):
    """Pure-SQL volume detection against the existing input tables -- no Excel access,
    consistent with this module never reading source Excel files (see migrations.py).

    Returns physical volume identifiers ("proto", "1", "2", ...), normalized via
    normalize_volume_label() and proto-first ordered via _order_volumes() -- every
    downstream consumer (cbom_insert_sql's CROSS JOIN, exporter.py's CBOM/Ex Inv VL
    sheet loop, every payload builder) depends on this exact ordering.

    Sourced only from input_db.volume/batch (never from quote_win's own populated
    columns) -- now that quote_win's numbered columns are read as POSITIONAL SLOTS
    (see volume_quote_win_slots()) rather than direct volume identifiers, assigning a
    physical identifier to each slot requires already knowing the physical volume set
    first. A volume known only through quote_win, with no corresponding volume/batch
    row, can therefore no longer be auto-discovered here -- a deliberate, documented
    narrowing (see the PROTO design plan); real RFQ data always has volume/batch rows
    whenever multi-volume detection matters.
    """
    vols = set()
    for row in con.execute(f"SELECT DISTINCT volume_name FROM input_db.volume WHERE rfq_id = {rfq_lit}").fetchall():
        if row[0] is not None:
            vols.add(normalize_volume_label(row[0]))
    for row in con.execute(f"SELECT DISTINCT volume FROM input_db.batch WHERE rfq_id = {rfq_lit}").fetchall():
        if row[0] is not None:
            vols.add(normalize_volume_label(row[0]))
    return _order_volumes(vols) or ["1"]


def _rate_case(column):
    """Same DB-backed rate table as currency.build_rate_case_sql()'s default (bare
    `currency_original`), just qualified to a specific column reference -- needed once
    costing_sheet/erp are also joined in (each has their own currency column, so an
    unqualified `currency_original` would be ambiguous)."""
    return build_rate_case_sql(column)


def cbom_insert_sql(rfq_lit, volumes):
    """Reuses the `selected_quote` TEMP VIEW already created (via selected_quote_sql())
    for this rfq_id -- does not rebuild the tie-break logic inline.

    `resolved` builds structure + _qw columns only, from scrub_bom_items/volume/batch/
    selected_quote. _costing/_erp columns are explicit NULL here -- filled in afterward
    by the enrich_erp/enrich_costing_sheet stages (enrichment.py), each their own MCP
    tool, run after this one. final_* stay NULL too -- those are user-controlled, set
    later by a separate UI workflow, never computed by this pipeline. (A one-off test
    temporarily set final_*=_qw to verify the derived-flag/report wiring below actually
    responds to final_* when populated -- confirmed working, then reverted.)

    `outer` -- derived flags (is_costed, scrap_percent, abc_classification, etc.), all
    genuinely reading `resolved.final_*` (not the raw per-source columns) -- this is the
    "use the final columns wherever there's an option" wiring; today it's numerically
    identical to reading _qw directly only because the one-off test above set
    final_* = _qw.
    """
    volumes_list_sql = ", ".join(f"('{str(n).replace(chr(39), chr(39) * 2)}')" for n in volumes)
    return f"""
    -- Explicit column list (not a bare INSERT INTO cbom_db.cbom relying on positional
    -- match against the live table) -- confirmed necessary: database.py's migration for
    -- a NEW column (hierarchy_multiplier) on an ALREADY-EXISTING table uses ALTER TABLE
    -- ADD COLUMN, which always appends at the physical end, while CREATE TABLE IF NOT
    -- EXISTS (a fresh install) places it wherever schema.py's CBOM_DDL text says -- the
    -- two disagree on physical column order for any table migrated in place, breaking a
    -- positional INSERT the moment a new column is added mid-DDL.
    INSERT INTO cbom_db.cbom (
        cbom_item_id, rfq_id, bom_item_id, volume_no, fg, assembly, cpn, description, commodity,
        unit_of_measure_costing, unit_of_measure_erp, unit_of_measure_qw, final_unit_of_measure,
        part_qty, hierarchy_multiplier, line_no, display_order, mfr_in_customer_bom,
        mfg_name_costing, mfg_name_erp, mfg_name_qw, final_mfg_name, mfg_part_number, ext_vol_qty,
        price_conv_costing, price_conv_erp, price_conv_qw, final_price_conv,
        price_original_costing, price_original_erp, price_original_qw, final_price_original,
        currency_original_costing, currency_original_erp, currency_original_qw, final_currency_original,
        supp_name_costing, supp_name_erp, supp_name_qw, final_supp_name,
        pkg_qty_costing, pkg_qty_erp, pkg_qty_qw, final_pkg_qty,
        moq_costing, moq_erp, moq_qw, final_moq,
        lead_time_costing, lead_time_erp, lead_time_qw, final_lead_time,
        ncnr, long_comment, price_type, exp_date, corrected_mpn, supplier_type,
        batch_qty, volume_qty, nre_charge, end_use_statement, scrap_percent,
        ext_price_conv, ext_part_vol_price_conv, price_control,
        is_costed, moq_qty_present, pkg_qty_present, pkg_qty_lte_moq, is_data, is_assembly,
        parent_line_no, abc_classification, recurring_count, mfg_part_num_in_scrub_bom,
        new_supplier, is_price_same, is_mpn_same
    )
    WITH resolved AS (
        SELECT
            s.bom_item_id, v.volume_no, s.fg, s.assembly, s.cpn, s.description, s.commodity,
            s.quantity AS part_qty,
            s.hierarchy_multiplier,
            -- Line No.: one value per FG ("Assembly" in this codebase's Assembly Summary
            -- block is FG-keyed, not the finer scrub_bom_items.assembly column -- confirmed
            -- there's no per-assembly header row to anchor a value to at that finer grain),
            -- shared by every row (part rows and the FG's own header row alike) -- not the
            -- old per-row s.item_number, which gave every part its own independent number.
            -- Sequential, ordered by each FG's first appearance in Scrub BOM (display_order),
            -- so it's fully dynamic per rfq_id, never hardcoded.
            fln.assembly_line_no AS line_no,
            s.display_order,
            s.manufacturer AS mfr_in_customer_bom,
            -- Uncosted parts have no selected_quote match, so q.mfg_name/q.mfg_part_number
            -- are NULL -- fall back to the Scrub BOM's own manufacturer/mpn so descriptive
            -- info survives even when pricing doesn't. Costed rows are unaffected (COALESCE
            -- only engages when the QuoteWin value is NULL).
            COALESCE(q.mfg_name, s.manufacturer) AS mfg_name_qw,
            COALESCE(q.mfg_part_number, s.mpn) AS mfg_part_number,
            q.ext_vol_qty,
            s.unit_of_measure AS unit_of_measure_qw,
            q.price_conv AS price_conv_qw, q.price_original AS price_original_qw,
            q.currency_original AS currency_original_qw, q.supp_name AS supp_name_qw,
            q.pkg_qty AS pkg_qty_qw,
            q.moq AS moq_qw,
            q.lead_time AS lead_time_qw,
            q.ncnr, q.long_comment, q.price_type, q.exp_date, q.corrected_mpn, q.supplier_type,
            b.batch_qty, vol.batch_qty AS volume_qty, s.level,
            -- _costing/_erp: filled in later by enrich_costing_sheet/enrich_erp, not here.
            CAST(NULL AS VARCHAR) AS unit_of_measure_costing,
            CAST(NULL AS VARCHAR) AS unit_of_measure_erp,
            CAST(NULL AS VARCHAR) AS mfg_name_costing,
            CAST(NULL AS VARCHAR) AS mfg_name_erp,
            CAST(NULL AS DOUBLE) AS price_conv_costing,
            CAST(NULL AS DOUBLE) AS price_conv_erp,
            CAST(NULL AS DOUBLE) AS price_original_costing,
            CAST(NULL AS DOUBLE) AS price_original_erp,
            CAST(NULL AS VARCHAR) AS currency_original_costing,
            CAST(NULL AS VARCHAR) AS currency_original_erp,
            CAST(NULL AS VARCHAR) AS supp_name_costing,
            CAST(NULL AS VARCHAR) AS supp_name_erp,
            CAST(NULL AS DOUBLE) AS pkg_qty_costing,
            CAST(NULL AS DOUBLE) AS pkg_qty_erp,   -- erp has no pkg_qty column -- see enrichment.py docstring
            CAST(NULL AS DOUBLE) AS moq_costing,
            CAST(NULL AS DOUBLE) AS moq_erp,       -- erp has no moq column
            CAST(NULL AS INTEGER) AS lead_time_costing,
            CAST(NULL AS INTEGER) AS lead_time_erp, -- erp has no lead_time column
            -- final_* are user-controlled -- populated later via a separate UI workflow,
            -- not resolved automatically here. See migrations.py / schema.py docstrings.
            CAST(NULL AS DOUBLE) AS final_price_conv,
            CAST(NULL AS DOUBLE) AS final_price_original,
            CAST(NULL AS DOUBLE) AS final_pkg_qty,
            CAST(NULL AS DOUBLE) AS final_moq,
            CAST(NULL AS INTEGER) AS final_lead_time,
            CAST(NULL AS VARCHAR) AS final_unit_of_measure,
            CAST(NULL AS VARCHAR) AS final_mfg_name,
            CAST(NULL AS VARCHAR) AS final_currency_original,
            CAST(NULL AS VARCHAR) AS final_supp_name
        FROM input_db.scrub_bom_items s
        CROSS JOIN (SELECT * FROM (VALUES {volumes_list_sql}) AS t(volume_no)) v
        -- Case-insensitive: real data has shown quote_win.part_number arriving with
        -- different casing than scrub_bom_items.cpn for the same physical part (e.g.
        -- 188/203 exact-case matches vs 201/203 case-insensitive, observed on real data)
        -- -- an exact-case join silently drops matching rows with no error.
        LEFT JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn) AND q.volume_no = v.volume_no
        LEFT JOIN (
            SELECT fg, 'Line_' || CAST(DENSE_RANK() OVER (ORDER BY MIN(display_order)) AS VARCHAR) AS assembly_line_no
            FROM input_db.scrub_bom_items WHERE rfq_id = {rfq_lit} GROUP BY fg
        ) fln ON fln.fg = s.fg
        LEFT JOIN input_db.batch  b   ON b.fg = s.fg   AND {_normalize_volume_sql('b.volume')} = v.volume_no AND b.rfq_id = {rfq_lit}
        LEFT JOIN input_db.volume vol ON vol.fg = s.fg AND {_normalize_volume_sql('vol.volume_name')} = v.volume_no AND vol.rfq_id = {rfq_lit}
        WHERE s.rfq_id = {rfq_lit}
    )
    SELECT
        uuid() AS cbom_item_id,
        {rfq_lit} AS rfq_id,
        resolved.bom_item_id, resolved.volume_no, resolved.fg, resolved.assembly, resolved.cpn,
        resolved.description, resolved.commodity,
        resolved.unit_of_measure_costing, resolved.unit_of_measure_erp, resolved.unit_of_measure_qw, resolved.final_unit_of_measure,
        resolved.part_qty,
        resolved.hierarchy_multiplier,
        resolved.line_no, resolved.display_order, resolved.mfr_in_customer_bom,
        resolved.mfg_name_costing, resolved.mfg_name_erp, resolved.mfg_name_qw, resolved.final_mfg_name,
        resolved.mfg_part_number, resolved.ext_vol_qty,
        resolved.price_conv_costing, resolved.price_conv_erp, resolved.price_conv_qw, resolved.final_price_conv,
        resolved.price_original_costing, resolved.price_original_erp, resolved.price_original_qw, resolved.final_price_original,
        resolved.currency_original_costing, resolved.currency_original_erp, resolved.currency_original_qw, resolved.final_currency_original,
        resolved.supp_name_costing, resolved.supp_name_erp, resolved.supp_name_qw, resolved.final_supp_name,
        resolved.pkg_qty_costing, resolved.pkg_qty_erp, resolved.pkg_qty_qw, resolved.final_pkg_qty,
        resolved.moq_costing, resolved.moq_erp, resolved.moq_qw, resolved.final_moq,
        resolved.lead_time_costing, resolved.lead_time_erp, resolved.lead_time_qw, resolved.final_lead_time,
        resolved.ncnr, resolved.long_comment, resolved.price_type, resolved.exp_date,
        resolved.corrected_mpn, resolved.supplier_type,
        resolved.batch_qty, resolved.volume_qty,
        NULL AS nre_charge,
        NULL AS end_use_statement,
        -- Scrap Factor classification -- tiers/percentages sourced from
        -- logic_db.scrap_factor_settings (see scrap_factor.py), not hardcoded here.
        -- Min-inclusive/Max-exclusive boundaries; a missing or non-positive price is
        -- NOT eligible for scrap calculation and gets NULL, not a silent default class
        -- (the old `ELSE 0.05` branch used to assign Class C to every uncosted row).
        {build_scrap_percent_case_sql('resolved.final_price_conv')} AS scrap_percent,
        resolved.final_price_conv * resolved.ext_vol_qty AS ext_price_conv,
        resolved.final_price_conv * resolved.part_qty * resolved.ext_vol_qty AS ext_part_vol_price_conv,
        CASE
            WHEN resolved.price_type ILIKE 'customer%' THEN 'Customer'
            WHEN resolved.price_type ILIKE 'cnp%' THEN 'CNP'
            WHEN resolved.price_type IS NULL OR resolved.price_type = '' THEN 'Centum'
            -- Business rule: "No Contract" means no separate customer/CNP contract
            -- applies, so standard Centum terms apply -- normalized here (not in the
            -- reporting layer alone) so every consumer of cbom.price_control (raw CBOM
            -- tab, every CBOM VL sheet's own column, BOM Matrix, A-Class Parts, Price
            -- Control report) sees "Centum" consistently instead of some seeing the raw
            -- "No Contract" string and others not.
            WHEN resolved.price_type ILIKE 'no contract%' THEN 'Centum'
            ELSE resolved.price_type
        END AS price_control,
        (resolved.final_price_conv IS NOT NULL AND resolved.final_price_conv > 0) AS is_costed,
        -- MOQ/Pkg Qty Present: confirmed against the Lam Research reference workbook
        -- (Test_fixes/validation_files) that these must be forced TRUE ("not a real
        -- issue") for the FG's own root row (level='0') and for any UNCOSTED row
        -- (final_price_conv missing/<=0) -- checking MOQ/Pkg Qty on a part with no
        -- price data at all isn't meaningful. Reference formula:
        -- IF(IsAssembly OR NOT(IsCosted), TRUE, AND(value<>"", value<>0)). Without
        -- this exemption, every uncosted row (108 of 1589 on RFQ-000032) was flagged
        -- as "MOQ missing"/"SPQ missing", none of which the reference counts as an
        -- issue -- confirmed a 1:1 correlation between moq_qty_present=FALSE rows and
        -- is_costed=FALSE rows before this fix.
        (resolved.level = '0'
            OR NOT (resolved.final_price_conv IS NOT NULL AND resolved.final_price_conv > 0)
            OR (resolved.final_moq IS NOT NULL AND resolved.final_moq <> 0)) AS moq_qty_present,
        (resolved.level = '0'
            OR NOT (resolved.final_price_conv IS NOT NULL AND resolved.final_price_conv > 0)
            OR (resolved.final_pkg_qty IS NOT NULL AND resolved.final_pkg_qty <> 0)) AS pkg_qty_present,
        -- PKg Qty <= MOQ ("PKG > MOQ" validation, inverted): per explicit business-rule
        -- confirmation, this comparison must only run when BOTH Pkg Qty and MOQ are
        -- genuinely present -- if either is missing, the row is exempt (treated as
        -- compliant/TRUE, not flagged) rather than defaulting a missing side to 0 and
        -- risking a false "exceeds MOQ" flag purely because MOQ (or Pkg Qty) wasn't
        -- populated at all.
        (resolved.final_pkg_qty IS NULL OR resolved.final_moq IS NULL
            OR resolved.final_pkg_qty <= resolved.final_moq) AS pkg_qty_lte_moq,
        (resolved.level <> '0') AS is_data,
        (resolved.level = '0') AS is_assembly,
        NULL AS parent_line_no,
        -- Scrap Class ("ABC Classification") -- same logic_db.scrap_factor_settings
        -- source as scrap_percent above; see that column's own comment.
        {build_scrap_class_case_sql('resolved.final_price_conv')} AS abc_classification,
        -- Recurring Count: running count of this CPN within this volume, in display_order,
        -- counting only is_data rows -- backend equivalent of the live Excel formula
        -- reproduced verbatim in reports/cbom_vl.py.
        CASE WHEN (resolved.level <> '0') THEN
            SUM(CASE WHEN (resolved.level <> '0') THEN 1 ELSE 0 END) OVER (
                PARTITION BY resolved.volume_no, resolved.cpn ORDER BY resolved.display_order
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
        ELSE NULL END AS recurring_count,
        -- Mfg Part Number in Scrub BOM: normalized (CPN, MPN) set-membership check
        -- against the ORIGINAL scrub_bom_items, not the same row's own mpn column (that
        -- would be MFR in Customer BOM's job, a different field). Cast to VARCHAR to
        -- match the column's new type -- the Excel export layer casts this back to a
        -- real boolean before it reaches openpyxl, so existing formulas are unaffected.
        -- MPN comparison is leading-zero-insensitive for purely numeric values (see
        -- _normalize_mpn_sql()) -- confirmed against the Lam Research reference that
        -- e.g. "13" (QuoteWin) and "000013" (Scrub BOM) are the same MPN, not a
        -- genuine mismatch.
        CASE WHEN EXISTS (
            SELECT 1 FROM input_db.scrub_bom_items s2
            WHERE s2.rfq_id = {rfq_lit}
              AND UPPER(TRIM(s2.cpn)) = UPPER(TRIM(resolved.cpn))
              AND {_normalize_mpn_sql('s2.mpn')} = {_normalize_mpn_sql('resolved.mfg_part_number')}
        ) THEN 'TRUE' ELSE 'FALSE' END AS mfg_part_num_in_scrub_bom,
        -- New Supplier: reference workbook has no formula here -- a static TRUE stub for
        -- every data row, no real "supplier changed" comparison anywhere in the reference
        -- system. Preserved verbatim (now VARCHAR per the new schema).
        CASE WHEN (resolved.level <> '0') THEN 'TRUE' ELSE NULL END AS new_supplier,
        -- Is Price Same: this row's price vs. the average price across every row sharing
        -- this CPN within this volume, both rounded to 3 decimals -- backend equivalent
        -- of the live Excel formula reproduced verbatim in reports/cbom_vl.py.
        CASE WHEN (resolved.level <> '0') THEN
            ROUND(AVG(resolved.final_price_conv) OVER (PARTITION BY resolved.volume_no, resolved.cpn), 3) = ROUND(resolved.final_price_conv, 3)
        ELSE NULL END AS is_price_same,
        -- Is MPN Same: TRUE iff exactly one distinct MPN exists across this CPN's rows in
        -- this volume -- backend equivalent of the live Excel formula reproduced verbatim
        -- in reports/cbom_vl.py.
        CASE WHEN (resolved.level <> '0') THEN
            COUNT(DISTINCT resolved.mfg_part_number) OVER (PARTITION BY resolved.volume_no, resolved.cpn) <= 1
        ELSE NULL END AS is_mpn_same
    FROM resolved
    """


def _to_usd_sql(amount_col, currency_col):
    """USD-converted amount for a raw (amount, currency) column pair, using the same
    DB-backed rate table as _rate_case()/currency.build_rate_case_sql(). Any currency
    outside the active set converts to NULL rather than silently passing the original
    amount through.
    """
    return f"{amount_col} / NULLIF({_rate_case(currency_col)}, 0)"


def erp_enrichment_sql(rfq_lit):
    """Two UPDATE statements that fill in the _erp columns on cbom rows that already
    exist for this rfq_id (see enrichment.py -- this is the enrich_erp stage, run after
    the cbom stage). erp is global master data with no guaranteed-unique key per
    (mpn, mfr) (e.g. repeat purchases of the same part logged as separate rows), so the
    match source is deduped first -- most-recently-imported row wins, same tie-break the
    retired cbom_enrichment.py used (there scoped to mpn alone; here scoped to mpn+mfr
    together, matching cbom's own, stricter match key). Both sides of the match are
    case-insensitive (UPPER()) for the same reason as the quote_win join in
    cbom_insert_sql -- real part-number/manufacturer-name casing is not guaranteed
    consistent across sources.

    Two separate statements because price_conv_erp depends on price_original_erp/
    currency_original_erp already being set by the first one.
    """
    return [
        f"""
        UPDATE cbom_db.cbom
        SET
            mfg_name_erp = matched.mfr,
            unit_of_measure_erp = matched.uom,
            currency_original_erp = matched.currency,
            supp_name_erp = matched.supplier_name,
            price_original_erp = matched.last_purchase_price
        FROM (
            SELECT * FROM input_db.erp
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY mpn, mfr
                ORDER BY imported_at DESC
            ) = 1
        ) AS matched
        WHERE cbom_db.cbom.rfq_id = {rfq_lit}
          AND UPPER(cbom_db.cbom.mfg_part_number) = UPPER(matched.mpn)
          AND UPPER(cbom_db.cbom.mfg_name_qw) = UPPER(matched.mfr)
        """,
        f"""
        UPDATE cbom_db.cbom
        SET price_conv_erp = {_to_usd_sql('price_original_erp', 'currency_original_erp')}
        WHERE rfq_id = {rfq_lit}
        """,
    ]


def costing_enrichment_sql(rfq_lit):
    """Two UPDATE statements that fill in the _costing columns on cbom rows that already
    exist for this rfq_id (see enrichment.py -- this is the enrich_costing_sheet stage,
    run after the cbom stage). Matched on rfq_id + part number ONLY, case-insensitively --
    costing_sheet.assembly was investigated and found to hold the RFQ id on every row,
    not a real sub-assembly value (the source Excel file has no assembly/sub-BOM column
    at all), so it is deliberately excluded from the match key; including it would match
    zero rows. costing_sheet has no guaranteed-unique key per (rfq_id, part_number)
    either, so the match source is deduped first -- first-inserted row wins, same
    tie-break the retired cbom_enrichment.py used.

    Only fills _costing-suffixed columns -- deliberately does NOT touch shared metadata
    fields (description, commodity, ncnr, long_comment, price_type, exp_date,
    price_control, nre_charge) the way the retired cbom_enrichment.py did; those stay
    exactly as cbom_insert_sql set them from quote_win/scrub_bom_items.

    Two separate statements because price_conv_costing depends on price_original_costing/
    currency_original_costing already being set by the first one.
    """
    return [
        f"""
        UPDATE cbom_db.cbom
        SET
            mfg_name_costing = matched.mfg_name,
            unit_of_measure_costing = matched.unit,
            currency_original_costing = matched.currency_original,
            supp_name_costing = matched.supp_name,
            pkg_qty_costing = matched.pkg_qty,
            moq_costing = matched.moq,
            lead_time_costing = matched.lead_time,
            price_original_costing = matched.price_original
        FROM (
            SELECT * FROM input_db.costing_sheet
            WHERE rfq_id = {rfq_lit}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY rfq_id, part_number
                ORDER BY rowid
            ) = 1
        ) AS matched
        WHERE cbom_db.cbom.rfq_id = {rfq_lit}
          AND UPPER(cbom_db.cbom.cpn) = UPPER(matched.part_number)
        """,
        f"""
        UPDATE cbom_db.cbom
        SET price_conv_costing = {_to_usd_sql('price_original_costing', 'currency_original_costing')}
        WHERE rfq_id = {rfq_lit}
        """,
    ]


def _has_source_sql(source):
    """A source counts as 'has data' for a row if it contributed a price OR
    at least descriptive fields -- matches how base cbom rows with no price
    anywhere still carry mfg_name/unit_of_measure from scrub_bom/quote_win."""
    return (
        f"(price_conv_{source} IS NOT NULL "
        f"OR mfg_name_{source} IS NOT NULL "
        f"OR unit_of_measure_{source} IS NOT NULL)"
    )


def _has_price_sql(source):
    """Narrower than _has_source_sql: true only when this source actually
    carries a price. Used to tell a genuine pricing decision (2+ sources
    both quoting a price) apart from a multi-"has data"-source row where
    only one side actually priced the part -- see
    final_selection_auto_resolve_sql/final_selection_conflict_query_sql."""
    return f"(price_conv_{source} IS NOT NULL)"


_FINAL_SOURCE_COLUMN_MAP = {
    "final_price_conv": "price_conv",
    "final_price_original": "price_original",
    "final_currency_original": "currency_original",
    "final_mfg_name": "mfg_name",
    "final_supp_name": "supp_name",
    "final_pkg_qty": "pkg_qty",
    "final_moq": "moq",
    "final_lead_time": "lead_time",
    "final_unit_of_measure": "unit_of_measure",
}


def final_selection_auto_resolve_sql(rfq_lit):
    """UPDATE that auto-populates final_* for cbom rows where the pricing
    decision is unambiguous:
      - exactly one of _costing/_erp/_qw has any usable data at all, or
      - 2+ sources have data but only one of them actually carries a valid
        price (e.g. QuoteWin has mfg_name/unit_of_measure but no price,
        Costing Sheet has the price) -- there's only one real price to pick,
        so this shouldn't require a human decision just because 2 "sources"
        are technically present.
    Rows with zero sources have nothing to select (left NULL); rows with 2+
    sources where either none or 2+ of them actually have a price are
    genuine conflicts left untouched here for
    final_selection_conflict_query_sql()/human review -- see
    resolve_final_selection in enrichment.py's sibling, final_selection.py.
    """
    set_clauses = ",\n        ".join(
        f"{final_col} = CASE w.winner "
        f"WHEN 'costing' THEN c.{source_field}_costing "
        f"WHEN 'erp' THEN c.{source_field}_erp "
        f"WHEN 'qw' THEN c.{source_field}_qw "
        f"ELSE NULL END"
        for final_col, source_field in _FINAL_SOURCE_COLUMN_MAP.items()
    )
    return f"""
    UPDATE cbom_db.cbom AS c
    SET
        {set_clauses}
    FROM (
        SELECT
            cbom_item_id,
            CASE
                WHEN (has_costing::INT + has_erp::INT + has_qw::INT) = 1 AND has_costing THEN 'costing'
                WHEN (has_costing::INT + has_erp::INT + has_qw::INT) = 1 AND has_erp THEN 'erp'
                WHEN (has_costing::INT + has_erp::INT + has_qw::INT) = 1 AND has_qw THEN 'qw'
                WHEN (has_costing::INT + has_erp::INT + has_qw::INT) >= 2
                     AND (has_price_costing::INT + has_price_erp::INT + has_price_qw::INT) = 1
                     AND has_price_costing THEN 'costing'
                WHEN (has_costing::INT + has_erp::INT + has_qw::INT) >= 2
                     AND (has_price_costing::INT + has_price_erp::INT + has_price_qw::INT) = 1
                     AND has_price_erp THEN 'erp'
                WHEN (has_costing::INT + has_erp::INT + has_qw::INT) >= 2
                     AND (has_price_costing::INT + has_price_erp::INT + has_price_qw::INT) = 1
                     AND has_price_qw THEN 'qw'
                ELSE NULL
            END AS winner
        FROM (
            SELECT
                cbom_item_id,
                {_has_source_sql('costing')} AS has_costing,
                {_has_source_sql('erp')} AS has_erp,
                {_has_source_sql('qw')} AS has_qw,
                {_has_price_sql('costing')} AS has_price_costing,
                {_has_price_sql('erp')} AS has_price_erp,
                {_has_price_sql('qw')} AS has_price_qw
            FROM cbom_db.cbom
            WHERE rfq_id = {rfq_lit}
        ) src
    ) w
    WHERE c.cbom_item_id = w.cbom_item_id AND c.rfq_id = {rfq_lit} AND w.winner IS NOT NULL
    """


def final_selection_recompute_derived_sql(rfq_lit):
    """Two statements that recompute the cbom columns derived from
    final_price_conv/final_moq/final_pkg_qty (is_costed, scrap_percent,
    ext_price_conv, ext_part_vol_price_conv, abc_classification,
    moq_qty_present, pkg_qty_present, pkg_qty_lte_moq, is_price_same) for
    this rfq_id. These are stored columns computed once at cbom build time
    (see cbom_insert_sql), not live views, so they never update on their own
    just because final_* changed underneath them -- this is the same
    recompute already validated against real data during this session's
    testing, reused here (and by hitl_router.py after each human batch
    resolution) instead of being duplicated.
    """
    return [
        f"""
        UPDATE cbom_db.cbom
        SET
            is_costed = (final_price_conv IS NOT NULL AND final_price_conv > 0),
            -- Same exemption/blank-coercion logic as cbom_insert_sql's initial
            -- computation of these three columns -- see that comment for why.
            moq_qty_present = (is_assembly
                OR NOT (final_price_conv IS NOT NULL AND final_price_conv > 0)
                OR (final_moq IS NOT NULL AND final_moq <> 0)),
            pkg_qty_present = (is_assembly
                OR NOT (final_price_conv IS NOT NULL AND final_price_conv > 0)
                OR (final_pkg_qty IS NOT NULL AND final_pkg_qty <> 0)),
            pkg_qty_lte_moq = (final_pkg_qty IS NULL OR final_moq IS NULL
                OR final_pkg_qty <= final_moq),
            -- Scrap Class/Percentage -- same logic_db.scrap_factor_settings source as
            -- cbom_insert_sql's initial computation; see that module's own comment.
            scrap_percent = {build_scrap_percent_case_sql('final_price_conv')},
            ext_price_conv = final_price_conv * ext_vol_qty,
            ext_part_vol_price_conv = final_price_conv * part_qty * ext_vol_qty,
            abc_classification = {build_scrap_class_case_sql('final_price_conv')}
        WHERE rfq_id = {rfq_lit}
        """,
        f"""
        UPDATE cbom_db.cbom AS c
        SET is_price_same = w.is_price_same
        FROM (
            SELECT cbom_item_id,
                CASE WHEN is_data THEN
                    ROUND(AVG(final_price_conv) OVER (PARTITION BY volume_no, cpn), 3) = ROUND(final_price_conv, 3)
                ELSE NULL END AS is_price_same
            FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}
        ) AS w
        WHERE c.cbom_item_id = w.cbom_item_id AND c.rfq_id = {rfq_lit}
        """,
    ]


def final_selection_conflict_query_sql(rfq_lit):
    """Rows where 2+ of _costing/_erp/_qw have usable data AND the pricing
    decision is still genuinely ambiguous -- either none of those sources
    actually priced the part, or 2+ of them did. Rows where 2+ sources have
    data but only one of them has a valid price are excluded here (they're
    auto-resolved instead -- see final_selection_auto_resolve_sql); there's
    no real decision to make when only one side quoted a price. Returns
    every raw per-source field needed to build each conflict's
    available_sources payload (see
    final_selection.py::resolve_final_selection). Never returned through the
    MCP tool response itself -- only persisted to Postgres
    logic_db.final_selection_conflicts, since an RFQ can have thousands of
    these and the MCP -> FastAPI -> Dify chain cannot carry that as one
    payload.
    """
    return f"""
    SELECT
        cbom_item_id, bom_item_id, volume_no, cpn,
        price_conv_costing, price_original_costing, currency_original_costing,
        mfg_name_costing, supp_name_costing, pkg_qty_costing, moq_costing,
        lead_time_costing, unit_of_measure_costing,
        price_conv_erp, price_original_erp, currency_original_erp,
        mfg_name_erp, supp_name_erp, pkg_qty_erp, moq_erp,
        lead_time_erp, unit_of_measure_erp,
        price_conv_qw, price_original_qw, currency_original_qw,
        mfg_name_qw, supp_name_qw, pkg_qty_qw, moq_qw,
        lead_time_qw, unit_of_measure_qw
    FROM (
        SELECT *,
            {_has_source_sql('costing')} AS has_costing,
            {_has_source_sql('erp')} AS has_erp,
            {_has_source_sql('qw')} AS has_qw,
            {_has_price_sql('costing')} AS has_price_costing,
            {_has_price_sql('erp')} AS has_price_erp,
            {_has_price_sql('qw')} AS has_price_qw
        FROM cbom_db.cbom
        WHERE rfq_id = {rfq_lit}
    ) t
    WHERE (has_costing::INT + has_erp::INT + has_qw::INT) >= 2
      AND (has_price_costing::INT + has_price_erp::INT + has_price_qw::INT) != 1
    """


def ex_inv_calc_sql(rfq_lit):
    return f"""
    CREATE OR REPLACE TEMP VIEW ex_inv_base AS
    SELECT
        c.cpn, c.volume_no,
        MAX(c.description) AS description, MAX(c.commodity) AS commodity,
        MAX(c.final_mfg_name) AS mfg_name, MAX(c.mfg_part_number) AS mfg_part_number,
        SUM(c.part_qty) AS part_qty, SUM(c.ext_vol_qty) AS ext_vol_qty_sum,
        MAX(s.inventory_stock) AS excess_in_stk, MAX(c.scrap_percent) AS scrap_percent,
        SUM(c.batch_qty) AS batch_qty, MAX(c.final_price_conv) AS cost,
        MAX(c.final_supp_name) AS supp_name, MAX(c.final_pkg_qty) AS pkg_qty, MAX(c.final_moq) AS moq,
        MAX(c.final_lead_time) AS lead_time, MAX(c.supplier_type) AS supplier_type,
        BOOL_AND(c.part_qty = FLOOR(c.part_qty)) AS part_qty_is_whole
    FROM cbom_db.cbom c
    JOIN input_db.scrub_bom_items s ON s.bom_item_id = c.bom_item_id
    WHERE COALESCE(c.is_assembly, FALSE) = FALSE AND c.rfq_id = {rfq_lit}
    GROUP BY c.cpn, c.volume_no;

    CREATE OR REPLACE TEMP VIEW ex_inv_calc AS
    WITH step1 AS (
        SELECT *,
            GREATEST(COALESCE(excess_in_stk, 0) - COALESCE(ext_vol_qty_sum, 0), 0) AS excess_after_demand,
            GREATEST(COALESCE(ext_vol_qty_sum, 0) - COALESCE(excess_in_stk, 0), 0) AS shortage_qty
        FROM ex_inv_base
    ),
    step2 AS (
        SELECT *,
            CASE WHEN part_qty_is_whole THEN CEIL(shortage_qty * (1 + COALESCE(scrap_percent, 0)))
                 ELSE shortage_qty * (1 + COALESCE(scrap_percent, 0)) END AS scrap_factor,
            CASE WHEN part_qty_is_whole THEN CEIL(COALESCE(batch_qty, 0) * (1 + COALESCE(scrap_percent, 0)))
                 ELSE COALESCE(batch_qty, 0) * (1 + COALESCE(scrap_percent, 0)) END AS batch_scrap_factor
        FROM step1
    ),
    step3 AS (
        SELECT *,
            COALESCE(cost * ext_vol_qty_sum, 0) AS ext_vol_cost,
            CASE WHEN moq IS NOT NULL AND moq > 0 THEN GREATEST(batch_scrap_factor - COALESCE(excess_in_stk, 0), 0)
                 ELSE 0 END AS partial_qty
        FROM step2
    ),
    step4 AS (
        SELECT *,
            CASE WHEN partial_qty = 0 THEN 0
                 ELSE COALESCE(CEIL(GREATEST(partial_qty, moq) / NULLIF(pkg_qty, 0)) * pkg_qty, 0)
            END AS ordering_qty
        FROM step3
    ),
    step5 AS (
        SELECT *,
            CASE WHEN moq IS NOT NULL AND moq > 0 THEN COALESCE(excess_in_stk, 0) + ordering_qty - batch_scrap_factor
                 ELSE 0 END AS excess_qty
        FROM step4
    ),
    step6 AS (
        SELECT *,
            excess_qty * cost AS excess_cost,
            ordering_qty * cost AS buy_value_after,
            CASE WHEN scrap_factor <= moq THEN moq
                 ELSE COALESCE(CEIL(scrap_factor / NULLIF(pkg_qty, 0)) * pkg_qty, 0) END AS net_ordering_qty
        FROM step5
    )
    SELECT *,
        GREATEST(net_ordering_qty + excess_after_demand - scrap_factor, 0) AS net_excess_qty,
        GREATEST(net_ordering_qty + excess_after_demand - scrap_factor, 0) * cost AS net_excess_cost,
        net_ordering_qty * cost AS final_buy_value,
        LAG(cost) OVER (PARTITION BY cpn ORDER BY volume_no) - cost AS price_delta_vs_prior,
        LAG(moq) OVER (PARTITION BY cpn ORDER BY volume_no) - moq AS moq_delta_vs_prior
    FROM step6;
    """


def _first_numbered_volume_sql(rfq_lit, table="cbom_db.cbom", extra_where=""):
    """Smallest numeric volume_no for this RFQ, never 'proto' -- numeric-aware (via
    TRY_CAST), not lexicographic, so this stays correct once volume_no is VARCHAR
    and/or there are 10+ numbered volumes. Used only by report_insert_sqls()'s
    dead-output 16-report tables (never read by exporter.py/the real Excel export), as
    a stand-in for the old hardcoded "volume_no = 1" now that PROTO can occupy that
    position -- this only needs to not crash and be a sensible substitute, since
    nothing consumes these tables' real output."""
    where = f"AND {extra_where} " if extra_where else ""
    return (
        f"(SELECT volume_no FROM {table} WHERE rfq_id = {rfq_lit} {where}"
        f"AND TRY_CAST(volume_no AS INTEGER) IS NOT NULL "
        f"ORDER BY TRY_CAST(volume_no AS INTEGER) ASC LIMIT 1)"
    )


def _last_numbered_volume_sql(rfq_lit, table="cbom_db.cbom", extra_where=""):
    """Largest numeric volume_no for this RFQ, never 'proto' -- see
    _first_numbered_volume_sql()'s docstring; same numeric-aware/dead-output caveats,
    used to replace price_control_report's old MAX(volume_no) (which would otherwise
    do a lexicographic string MAX once volume_no is VARCHAR, always incorrectly
    selecting 'proto' since 'p' > any digit)."""
    where = f"AND {extra_where} " if extra_where else ""
    return (
        f"(SELECT volume_no FROM {table} WHERE rfq_id = {rfq_lit} {where}"
        f"AND TRY_CAST(volume_no AS INTEGER) IS NOT NULL "
        f"ORDER BY TRY_CAST(volume_no AS INTEGER) DESC LIMIT 1)"
    )


def report_insert_sqls(rfq_lit):
    return {
        "bom_matrix_report": f"""
            INSERT INTO bom_matrix_report
            SELECT
                {rfq_lit} AS rfq_id, s.cpn, s.fg, c.volume_no,
                COUNT(*) OVER (PARTITION BY s.cpn, s.fg) AS fg_count,
                COUNT(*) OVER (PARTITION BY s.cpn) AS grand_total,
                vol.batch_qty AS volume_qty,
                c.description, c.commodity, c.final_mfg_name, c.mfg_part_number, c.final_price_conv,
                c.final_price_conv * COUNT(*) OVER (PARTITION BY s.cpn, s.fg) AS fg_total_cost,
                c.final_price_conv * COUNT(*) OVER (PARTITION BY s.cpn) AS fg_grand_total,
                c.final_pkg_qty, c.final_moq, c.final_lead_time, c.long_comment, c.price_control, c.ncnr,
                c.final_supp_name, c.corrected_mpn, ex.net_excess_cost,
                q.quote_validity AS price_validity, q.eff_date AS effective_date
            FROM input_db.scrub_bom_items s
            JOIN cbom_db.cbom c ON c.bom_item_id = s.bom_item_id AND c.rfq_id = {rfq_lit}
            LEFT JOIN input_db.volume vol ON vol.fg = s.fg AND {_normalize_volume_sql('vol.volume_name')} = c.volume_no AND vol.rfq_id = {rfq_lit}
            LEFT JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn) AND q.volume_no = c.volume_no
            LEFT JOIN ex_inv_calc ex ON ex.cpn = s.cpn AND ex.volume_no = c.volume_no
            WHERE s.rfq_id = {rfq_lit}
        """,
        "part_num_vs_mfg_num_report": f"""
            INSERT INTO part_num_vs_mfg_num_report
            SELECT DISTINCT {rfq_lit} AS rfq_id, s.cpn AS part_number, q.mfg_part_number AS mpn,
                (q.mfg_part_number IN (SELECT s2.mpn FROM input_db.scrub_bom_items s2 WHERE s2.cpn = s.cpn AND s2.rfq_id = {rfq_lit})) AS in_scrub_bom
            FROM input_db.scrub_bom_items s
            JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn)
            WHERE s.rfq_id = {rfq_lit}
        """,
        "pcb_nre_fai_charge_report": f"""
            INSERT INTO pcb_nre_fai_charge_report
            -- QUALIFY dedups to one row per CPN -- a CPN recurring across multiple
            -- assemblies otherwise duplicates this report's declared cpn PRIMARY KEY.
            SELECT {rfq_lit} AS rfq_id, s.cpn, c.description, c.commodity, c.final_mfg_name, c.mfg_part_number, c.nre_charge
            FROM input_db.scrub_bom_items s
            JOIN cbom_db.cbom c ON c.bom_item_id = s.bom_item_id AND c.volume_no = {_first_numbered_volume_sql(rfq_lit)} AND c.rfq_id = {rfq_lit}
            WHERE s.commodity = 'PCB' AND s.rfq_id = {rfq_lit}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY s.cpn ORDER BY s.bom_item_id) = 1
        """,
        "mech_em_nre_report": f"""
            INSERT INTO mech_em_nre_report
            SELECT {rfq_lit} AS rfq_id, s.cpn, c.description, c.commodity, c.final_mfg_name, c.mfg_part_number, c.nre_charge
            FROM input_db.scrub_bom_items s
            JOIN cbom_db.cbom c ON c.bom_item_id = s.bom_item_id AND c.volume_no = {_first_numbered_volume_sql(rfq_lit)} AND c.rfq_id = {rfq_lit}
            WHERE UPPER(s.commodity) IN ('MECHANICAL', 'ELECTROMECHANICAL') AND s.rfq_id = {rfq_lit}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY s.cpn ORDER BY s.bom_item_id) = 1
        """,
        "missing_notes_report": f"""
            INSERT INTO missing_notes_report
            SELECT
                {rfq_lit} AS rfq_id, s.cpn, s.mpn, s.description, s.commodity, s.manufacturer, s.part_status,
                q.mfg_part_number, q.commodity AS quoted_commodity, q.mfg_name AS quoted_manufacturer,
                q.price_type, q.ncnr, q.corrected_mpn, q.no_bid_reason, q.exp_date, q.part_status AS quoted_part_status,
                (q.mfg_part_number IS DISTINCT FROM s.mpn) AS mpn_mismatch,
                (q.commodity IS DISTINCT FROM s.commodity) AS commodity_mismatch,
                (q.exp_date IS NOT NULL AND q.exp_date <= CURRENT_DATE + INTERVAL 30 DAY) AS quote_expiring_soon
            FROM input_db.scrub_bom_items s
            LEFT JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn)
            WHERE s.rfq_id = {rfq_lit}
        """,
        "lead_time_fg_report": f"""
            INSERT INTO lead_time_fg_report
            SELECT {rfq_lit} AS rfq_id, s.fg, q.lead_time, COUNT(*) AS cpn_count
            FROM input_db.scrub_bom_items s
            JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn)
            WHERE s.rfq_id = {rfq_lit}
            GROUP BY s.fg, q.lead_time
        """,
        "lead_time_consolidated_report": f"""
            INSERT INTO lead_time_consolidated_report
            SELECT {rfq_lit} AS rfq_id, q.lead_time, COUNT(*) AS cpn_count,
                COUNT(*)::DOUBLE / SUM(COUNT(*)) OVER () AS percentage
            FROM input_db.scrub_bom_items s
            JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn)
            WHERE s.rfq_id = {rfq_lit}
            GROUP BY q.lead_time
        """,
        "sum_and_count_report": f"""
            INSERT INTO sum_and_count_report
            SELECT {rfq_lit} AS rfq_id, s.assembly,
                SUM(s.quantity) AS scrub_bom_sum, COUNT(*) AS scrub_bom_count,
                SUM(s.quantity) FILTER (WHERE q.awarded_volume_1 IS NOT NULL) AS v1_sum,
                COUNT(*) FILTER (WHERE q.awarded_volume_1 IS NOT NULL) AS v1_count
            FROM input_db.scrub_bom_items s
            LEFT JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn)
            WHERE s.rfq_id = {rfq_lit}
            GROUP BY s.assembly
        """,
        "sum_and_count_detailed_report": f"""
            INSERT INTO sum_and_count_detailed_report
            SELECT {rfq_lit} AS rfq_id, s.assembly, s.cpn,
                SUM(s.quantity) AS scrub_bom_sum, COUNT(*) AS scrub_bom_count,
                SUM(s.quantity) FILTER (WHERE q.awarded_volume_1 IS NOT NULL) AS v1_sum,
                COUNT(*) FILTER (WHERE q.awarded_volume_1 IS NOT NULL) AS v1_count
            FROM input_db.scrub_bom_items s
            LEFT JOIN selected_quote q ON UPPER(q.part_number) = UPPER(s.cpn)
            WHERE s.rfq_id = {rfq_lit}
            GROUP BY s.assembly, s.cpn
        """,
        "revision_history_report": f"""
            INSERT INTO revision_history_report
            SELECT
                {rfq_lit} AS rfq_id, s.cpn, c.volume_no, s.assembly, s.description, s.mpn,
                c.ext_vol_qty AS new_system_qty, c.final_price_conv AS new_unit_price, c.ext_price_conv AS new_system_price,
                CAST(NULL AS DOUBLE) AS old_system_qty, CAST(NULL AS DOUBLE) AS old_unit_price, CAST(NULL AS DOUBLE) AS old_system_price
            FROM input_db.scrub_bom_items s
            JOIN cbom_db.cbom c ON c.bom_item_id = s.bom_item_id AND c.rfq_id = {rfq_lit}
            WHERE s.rfq_id = {rfq_lit}
        """,
        "aclass_parts_report": f"""
            INSERT INTO aclass_parts_report
            WITH deduped AS (
                SELECT
                    s.cpn, s.fg, c.description, c.commodity, c.final_mfg_name, c.mfg_part_number,
                    c.final_price_conv AS unit_cost, c.ext_vol_qty AS awarded_volume, c.ext_price_conv, c.abc_classification,
                    ROW_NUMBER() OVER (PARTITION BY s.cpn ORDER BY s.bom_item_id) AS rn
                FROM input_db.scrub_bom_items s
                JOIN cbom_db.cbom c ON c.bom_item_id = s.bom_item_id AND c.volume_no = {_first_numbered_volume_sql(rfq_lit)} AND c.rfq_id = {rfq_lit}
                WHERE s.rfq_id = {rfq_lit}
            )
            SELECT {rfq_lit} AS rfq_id, cpn, fg, description, commodity, final_mfg_name AS mfg_name, mfg_part_number, unit_cost,
                awarded_volume, ext_price_conv, abc_classification,
                ext_price_conv / NULLIF(SUM(ext_price_conv) OVER (), 0) AS pct_of_total
            FROM deduped WHERE rn = 1
        """,
        "price_control_report": f"""
            INSERT INTO price_control_report
            SELECT {rfq_lit} AS rfq_id, c.price_control, SUM(c.final_price_conv * vol.batch_qty) AS bucket_total
            FROM cbom_db.cbom c
            JOIN input_db.scrub_bom_items s ON s.bom_item_id = c.bom_item_id
            JOIN input_db.volume vol ON vol.fg = s.fg AND {_normalize_volume_sql('vol.volume_name')} = c.volume_no AND vol.rfq_id = {rfq_lit}
            WHERE c.rfq_id = {rfq_lit}
              AND c.volume_no = {_last_numbered_volume_sql(rfq_lit, extra_where="is_data")}
              AND c.is_data
            GROUP BY c.price_control
        """,
        "summary_report": f"""
            INSERT INTO summary_report
            SELECT
                {rfq_lit} AS rfq_id, s.fg, c.volume_no,
                SUM(s.quantity) AS bom_qty, SUM(s.inventory_stock) AS inventory_stock,
                SUM(c.ext_price_conv) AS ext_vol_conv_price, vol.batch_qty AS volume_qty,
                ex.total_excess_cost AS moq_cost,
                ex.total_excess_cost / NULLIF(SUM(c.ext_price_conv), 0) AS pct_moq_of_cost
            FROM input_db.scrub_bom_items s
            JOIN cbom_db.cbom c ON c.bom_item_id = s.bom_item_id AND c.rfq_id = {rfq_lit}
            JOIN input_db.volume vol ON vol.fg = s.fg AND {_normalize_volume_sql('vol.volume_name')} = c.volume_no AND vol.rfq_id = {rfq_lit}
            LEFT JOIN (SELECT volume_no, SUM(net_excess_cost) AS total_excess_cost FROM ex_inv_calc GROUP BY volume_no) ex
                ON ex.volume_no = c.volume_no
            WHERE s.rfq_id = {rfq_lit}
            GROUP BY s.fg, c.volume_no, vol.batch_qty, ex.total_excess_cost
        """,
        "batchwise_cashflow_report": f"""
            INSERT INTO batchwise_cashflow_report
            SELECT {rfq_lit} AS rfq_id, c.supplier_type, ex.volume_no,
                SUM(ex.final_buy_value) AS sum_final_buy_value, SUM(ex.buy_value_after) AS sum_buy_value_after
            FROM ex_inv_calc ex
            JOIN cbom_db.cbom c ON c.cpn = ex.cpn AND c.volume_no = ex.volume_no AND c.rfq_id = {rfq_lit}
            GROUP BY c.supplier_type, ex.volume_no
        """,
        "cbom_vl_report": f"""
            INSERT INTO cbom_vl_report SELECT * FROM cbom_db.cbom WHERE rfq_id = {rfq_lit}
        """,
        "ex_inv_vl_report": f"""
            INSERT INTO ex_inv_vl_report SELECT {rfq_lit} AS rfq_id, * FROM ex_inv_calc
        """,
    }
