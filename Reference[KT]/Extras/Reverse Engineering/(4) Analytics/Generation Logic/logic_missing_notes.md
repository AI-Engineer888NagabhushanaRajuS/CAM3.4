# Generation logic: missing_notes

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/missing_notes.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the Missing Notes report (Laravel PHP).

Three layers, mirroring the PHP pipeline:
  1. missing_notes() — port of MissingNotesController::missingNotes(): computes
     the 14 sections (heading_id 1-14) from bom_data/rfqs/smtp_details, matching
     the input/output JSON documented in missing_notes.md. A section is only
     included if it found at least one match (mirrors the PHP's per-section
     `if (!empty($array))` guard before persisting).
  2. flatten_missing_notes() — port of exportAllMissingNotes()'s flattening:
     turns the structured sections into the flat 2D array MissingNotesExport
     actually renders.
  3. build_missing_notes_sheet() — port of app/Exports/MissingNotesExport.php:
     styles that flat array into a 'Missing Notes' worksheet.

No live-formula variant exists for this report (unlike Sum & Count / BOM
Matrix), and no DB access happens here — bom_data/rfqs/smtp_details are
supplied by the caller, and the PHP's bulk `rfqs.missing_note_flag`/
`missing_note_refId` side-effect update is out of scope (DB write, not
part of the JSON transform).

## Module constants

- `_STATUS_CONFIGS = {     "NRFND": ("NRFND", "Part Status is NRFND in Scrub BOM or QW/RFQ"),     "DISCONTINUED": ("Discontinued", "Part Status is Discontinued in Scrub BOM or QW/RFQ"),     "EOL": ("EOL"`
- `_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")`
- `_HEADING_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADING_FONT = Font(bold=True, color="FFFFFF")`
- `_HEADER_FILL = PatternFill("solid", fgColor="D9E2F3")`
- `_HEADER_FONT = Font(bold=True)`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_WRAP_CENTER = Alignment(wrapText=True, vertical="center")`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`
- `_HEADING_RE = re.compile(r"^\d+\.\s+")`

## Functions (line, name, first docstring line)

- L35 `_is_numeric(value)` 
- L49 `_normalize_status(status)` 
- L54 `_normalize_commodity(value)` 
- L61 `_commodity_variants(value)` Naming-convention-tolerant equivalence set for one commodity string: strips a
- L78 `_mk_row(r, bom_mfr_by_cpn_mpn)` 
- L96 `_fallback_row(bom_row)` 
- L111 `_min_id_by_cpn(rows)` First-occurrence-ordered list of one row per cpn (the smallest-id row).
- L125 `_section_uncosted_parts(uncosted_rows)` Rows are supplied ready-made by the adapter (templates/excel_mappings.py),
- L136 `_section_customer_price_control(rfq_base, bom_mfr_by_cpn_mpn)` 
- L141 `_section_ncnr_mentioned(rfq_base, bom_mfr_by_cpn_mpn)` 
- L168 `_section_corrected_mpn(rfq_base, bom_mfr_by_cpn_mpn)` 
- L186 `_section_supplier_type_advance(rfq_base, bom_mfr_by_cpn_mpn)` 
- L191 `_section_proto_pricing_no_cost(bom_by_cpn, rfqs, bom_mfr_by_cpn_mpn)` 
- L228 `_section_price_validity(rfq_base, bom_mfr_by_cpn_mpn, as_of)` 
- L249 `_section_cpn_mismatch(rfq_base, bom_cpn_set, bom_mfr_by_cpn_mpn)` 
- L271 `_section_commodity_mismatch(rfq_base, bom_data, bom_cpn_set, bom_commodity_by_cpn, bom_mfr_by_cpn_mpn)` 
- L297 `_section_manufacturer_mismatch(rfq_base, smtp_manufacturer_by_mpn, bom_mfr_by_cpn_mpn)` 
- L311 `_section_mpn_subset_mismatch(rfq_base, bom_data, bom_cpn_set, bom_mfr_by_cpn_mpn)` 
- L339 `_section_part_status(bom_data, rfq_base, bom_mfr_by_cpn_mpn)` Deduped by CPN alone (not CPN||MPN): a part status (NRFND/Discontinued/EOL) is a
- L406 `missing_notes(payload, as_of)` Port of MissingNotesController::missingNotes(): the 14-section computation.
- L489 `flatten_missing_notes(sections)` Port of exportAllMissingNotes()'s flattening into the Excel-ready 2D array.
- L530 `build_missing_notes_sheet(wb, rows)` Port of MissingNotesExport: styles the flattened Missing Notes rows.
- L573 `_style_row(ws, row_num, last_col, fill, font)` 
- L582 `_demo()` 
- L630 `_demo_full_pipeline(wb)` 
- L453 `add(heading, description, data)` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)


## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
