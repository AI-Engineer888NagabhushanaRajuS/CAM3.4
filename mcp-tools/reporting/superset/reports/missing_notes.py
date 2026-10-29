"""Python port of the Missing Notes report (Laravel PHP).

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
"""

import re
from datetime import datetime, timedelta

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

_STATUS_CONFIGS = {
    "NRFND": ("NRFND", "Part Status is NRFND in Scrub BOM or QW/RFQ"),
    "DISCONTINUED": ("Discontinued", "Part Status is Discontinued in Scrub BOM or QW/RFQ"),
    "EOL": ("EOL", "Part Status is EOL in Scrub BOM or QW/RFQ"),
}


def _is_numeric(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except ValueError:
            return False
    return False


def _normalize_status(status):
    text = str(status or "").strip()
    return text.upper() if text else ""


def _normalize_commodity(value):
    return str(value or "").strip().lower()


_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _commodity_variants(value):
    """Naming-convention-tolerant equivalence set for one commodity string: strips a
    trailing parenthetical annotation (verified against real data: quote_win says
    "PASSIVE (D&A)" where scrub_bom_items says "PASSIVE") and adds both the naive
    singular and plural form (quote_win says "PASSIVES"/"FASTENERS", scrub_bom_items
    says "passive"/"Fastener") -- confirmed these two differences account for 100% of
    the real Commodity Mismatch noise once orphan CPNs are excluded.
    """
    key = _TRAILING_PAREN_RE.sub("", str(value or "").strip().upper()).strip()
    variants = {key}
    if key.endswith("S") and len(key) > 1:
        variants.add(key[:-1])
    else:
        variants.add(key + "S")
    return variants


def _mk_row(r, bom_mfr_by_cpn_mpn):
    cpn = r.get("cpn") or ""
    mpn = r.get("MPN") or ""
    bom_mfr = bom_mfr_by_cpn_mpn.get(f"{cpn}||{mpn}", "")
    return {
        "id": r.get("id"),
        "partNumber": r.get("cpn"),
        "description": r.get("part_description") or "",
        "commodity": r.get("commodity") or "",
        "mfgName": bom_mfr if bom_mfr != "" else "-",
        "mfgPartNumber": r.get("MPN") or "",
        "x": "",
        "quotedMfr": r.get("manufacturer_name") or "",
        "quotedMpn": "",
        "remarks": "",
    }


def _fallback_row(bom_row):
    return {
        "id": None,
        "partNumber": bom_row.get("CPN") or "",
        "description": bom_row.get("Description") or "",
        "commodity": bom_row.get("Commodity") or "",
        "mfgName": bom_row.get("MFR") or "-",
        "mfgPartNumber": bom_row.get("MPN") or "",
        "x": "",
        "quotedMfr": "",
        "quotedMpn": "",
        "remarks": "",
    }


def _min_id_by_cpn(rows):
    """First-occurrence-ordered list of one row per cpn (the smallest-id row)."""
    best = {}
    order = []
    for r in rows:
        cpn = r.get("cpn")
        if cpn not in best:
            order.append(cpn)
            best[cpn] = r
        elif (r.get("id") or 0) < (best[cpn].get("id") or 0):
            best[cpn] = r
    return [best[cpn] for cpn in order]


def _section_uncosted_parts(uncosted_rows):
    """Rows are supplied ready-made by the adapter (templates/excel_mappings.py),
    built directly from cbom.is_costed==FALSE -- the authoritative, already-tie-broken
    signal. Replaces the old "no is_L1 quote_win row" check, which both missed real
    uncosted parts (a quote can exist but never resolve a price -- e.g. GBP-quoted
    parts, since currency.py only defines USD/INR/EUR rates) and wrongly included the
    FG's own assembly-header row (cbom.is_data already excludes it upstream).
    """
    return list(uncosted_rows)


def _section_customer_price_control(rfq_base, bom_mfr_by_cpn_mpn):
    matches = [r for r in rfq_base if str(r.get("price_control") or "").lower() == "customer"]
    return [_mk_row(r, bom_mfr_by_cpn_mpn) for r in _min_id_by_cpn(matches)]


def _section_ncnr_mentioned(rfq_base, bom_mfr_by_cpn_mpn):
    mpns_with_ncnr = []
    seen_mpns = set()
    for r in rfq_base:
        if str(r.get("ncnr") or "").lower() == "yes":
            mpn = r.get("MPN")
            if mpn not in seen_mpns:
                seen_mpns.add(mpn)
                mpns_with_ncnr.append(mpn)
    if not mpns_with_ncnr:
        return []

    mpns_with_ncnr_set = set(mpns_with_ncnr)
    by_mpn = {}
    order = []
    for r in rfq_base:
        mpn = r.get("MPN")
        if mpn not in mpns_with_ncnr_set:
            continue
        if mpn not in by_mpn:
            order.append(mpn)
            by_mpn[mpn] = r
        elif (r.get("id") or 0) < (by_mpn[mpn].get("id") or 0):
            by_mpn[mpn] = r
    return [_mk_row(by_mpn[mpn], bom_mfr_by_cpn_mpn) for mpn in order]


def _section_corrected_mpn(rfq_base, bom_mfr_by_cpn_mpn):
    seen = set()
    rows = []
    for r in rfq_base:
        corrected = r.get("corrected_MPN")
        if not corrected:
            continue
        key = f"{r.get('cpn')}_{corrected}"
        if key in seen:
            continue
        seen.add(key)
        row = _mk_row(r, bom_mfr_by_cpn_mpn)
        row["correctedMpn"] = corrected
        row["quotedMpn"] = corrected
        rows.append(row)
    return rows


def _section_supplier_type_advance(rfq_base, bom_mfr_by_cpn_mpn):
    matches = [r for r in rfq_base if str(r.get("supplier_type") or "").lower() == "advance"]
    return [_mk_row(r, bom_mfr_by_cpn_mpn) for r in _min_id_by_cpn(matches)]


def _section_proto_pricing_no_cost(bom_by_cpn, rfqs, bom_mfr_by_cpn_mpn):
    vol1_by_cpn = {}
    for r in rfqs:
        if r.get("volume_no") != 1:
            continue
        cpn = r.get("cpn")
        if cpn is None:
            continue
        vol1_by_cpn.setdefault(cpn, []).append(r)

    rows = []
    for cpn, bom_row in bom_by_cpn.items():
        rfq_rows = vol1_by_cpn.get(cpn, [])
        if not rfq_rows:
            row = _fallback_row(bom_row)
            row["vol_moq"] = None
            rows.append(row)
            continue

        has_valid_price = False
        picked = None
        for rfq_row in rfq_rows:
            vol_pricing = rfq_row.get("vol_pricing")
            if vol_pricing is not None and _is_numeric(vol_pricing) and float(vol_pricing) != 0.0:
                has_valid_price = True
                break
            if picked is None and (vol_pricing is None or (_is_numeric(vol_pricing) and float(vol_pricing) == 0.0)):
                picked = rfq_row
        if has_valid_price:
            continue
        if picked is not None:
            row = _mk_row(picked, bom_mfr_by_cpn_mpn)
            row["vol_moq"] = picked.get("vol_moq")
            rows.append(row)
    return rows


def _section_price_validity(rfq_base, bom_mfr_by_cpn_mpn, as_of):
    today = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    end = today + timedelta(days=30, hours=23, minutes=59, seconds=59)

    seen_ids = set()
    rows = []
    for r in rfq_base:
        expiry = r.get("expiry_date")
        if not expiry:
            continue
        expiry_dt = expiry if isinstance(expiry, datetime) else datetime.fromisoformat(str(expiry))
        if not (today <= expiry_dt <= end):
            continue
        rid = r.get("id")
        if rid in seen_ids:
            continue
        seen_ids.add(rid)
        rows.append(_mk_row(r, bom_mfr_by_cpn_mpn))
    return rows


def _section_cpn_mismatch(rfq_base, bom_cpn_set, bom_mfr_by_cpn_mpn):
    ordered_unique_cpns = []
    seen = set()
    for r in rfq_base:
        cpn = r.get("cpn")
        if cpn not in seen:
            seen.add(cpn)
            ordered_unique_cpns.append(cpn)
    mismatched = {cpn for cpn in ordered_unique_cpns if cpn not in bom_cpn_set}
    if not mismatched:
        return []

    rows = []
    picked = set()
    for r in rfq_base:
        cpn = r.get("cpn")
        if cpn in mismatched and cpn not in picked:
            picked.add(cpn)
            rows.append(_mk_row(r, bom_mfr_by_cpn_mpn))
    return rows


def _section_commodity_mismatch(rfq_base, bom_data, bom_cpn_set, bom_commodity_by_cpn, bom_mfr_by_cpn_mpn):
    bom_commodities_by_cpn = {}
    for row in bom_data:
        cpn = row.get("CPN")
        if cpn is None:
            continue
        bom_commodities_by_cpn.setdefault(cpn, set()).update(_commodity_variants(row.get("Commodity")))

    seen = set()
    rows = []
    for r in rfq_base:
        cpn = r.get("cpn")
        if cpn not in bom_cpn_set:
            continue  # already flagged by MPN Mismatch with BOM -- don't double-report
        if _commodity_variants(r.get("commodity")) & bom_commodities_by_cpn.get(cpn, set()):
            continue
        key = (cpn, r.get("commodity"))
        if key in seen:
            continue
        seen.add(key)
        row = _mk_row(r, bom_mfr_by_cpn_mpn)
        row["remarks"] = f"Scrub BOM commodity: {bom_commodity_by_cpn.get(cpn, '')}"
        rows.append(row)
    return rows


def _section_manufacturer_mismatch(rfq_base, smtp_manufacturer_by_mpn, bom_mfr_by_cpn_mpn):
    rows = []
    for r in rfq_base:
        smtp_man = smtp_manufacturer_by_mpn.get(r.get("MPN"))
        if not smtp_man:
            continue
        rfq_man = str(r.get("manufacturer_name") or "").strip().lower()
        if rfq_man != str(smtp_man).strip().lower():
            row = _mk_row(r, bom_mfr_by_cpn_mpn)
            row["smtpManufacturer"] = smtp_man
            rows.append(row)
    return rows


def _section_mpn_subset_mismatch(rfq_base, bom_data, bom_cpn_set, bom_mfr_by_cpn_mpn):
    bom_mpns_by_cpn = {}
    for row in bom_data:
        cpn = row.get("CPN")
        if cpn is None:
            continue
        bom_mpns_by_cpn.setdefault(cpn, set()).add(row.get("MPN"))

    seen = set()
    rows = []
    for r in rfq_base:
        cpn = r.get("cpn")
        mpn = r.get("MPN")
        if cpn not in bom_cpn_set:
            continue  # already flagged by MPN Mismatch with BOM -- don't double-report
        valid_set = bom_mpns_by_cpn.get(cpn)
        if valid_set and mpn in valid_set:
            continue
        key = (cpn, mpn)
        if key in seen:
            continue
        seen.add(key)
        row = _mk_row(r, bom_mfr_by_cpn_mpn)
        row["remarks"] = "MPN not in BOM subset for this CPN"
        rows.append(row)
    return rows


def _section_part_status(bom_data, rfq_base, bom_mfr_by_cpn_mpn):
    """Deduped by CPN alone (not CPN||MPN): a part status (NRFND/Discontinued/EOL) is a
    property of the physical part, not of any one approved-alternate MPN row for it --
    keying on CPN||MPN counted the same CPN once per alternate MPN (verified against
    real data: a CPN with several approved alternates in Scrub BOM was appearing 2-6x
    in this section under the old key, inflating Discontinued from a true 161 to 254).

    bom_status_by_key is a set of every matching status seen for that CPN (not just the
    first one found): a CPN's raw rows can genuinely carry more than one status across
    its approved alternates (verified: CPN 99219836 has both EOL and Discontinued rows)
    -- taking only the first-seen status silently dropped the part from every other
    status section it also belongs to.
    """
    bom_row_by_key = {}
    bom_status_by_key = {}
    for row in bom_data:
        cpn = row.get("CPN") or ""
        if cpn == "":
            continue
        key = cpn
        if key not in bom_row_by_key:
            bom_row_by_key[key] = row
        status = _normalize_status(row.get("Part Status"))
        if status in _STATUS_CONFIGS:
            bom_status_by_key.setdefault(key, set()).add(status)

    rfq_row_by_key = {}
    rfq_status_by_key = {}
    for r in rfq_base:
        cpn = r.get("cpn") or ""
        if cpn == "":
            continue
        key = cpn
        if key not in rfq_row_by_key:
            rfq_row_by_key[key] = r
        status = _normalize_status(r.get("part_status"))
        if status in _STATUS_CONFIGS:
            rfq_status_by_key.setdefault(key, set()).add(status)

    status_rows = {"NRFND": [], "DISCONTINUED": [], "EOL": []}
    seen_status_keys = {"NRFND": set(), "DISCONTINUED": set(), "EOL": set()}
    all_keys = list(dict.fromkeys(list(bom_row_by_key.keys()) + list(rfq_status_by_key.keys())))

    for key in all_keys:
        if key in bom_status_by_key:
            status_list = list(bom_status_by_key[key])
        elif key in rfq_status_by_key:
            status_list = list(rfq_status_by_key[key])
        else:
            continue

        for status_key in status_list:
            if key in seen_status_keys[status_key]:
                continue
            seen_status_keys[status_key].add(key)

            if key in rfq_row_by_key:
                status_rows[status_key].append(_mk_row(rfq_row_by_key[key], bom_mfr_by_cpn_mpn))
                continue

            bom_row = bom_row_by_key.get(key)
            if bom_row:
                status_rows[status_key].append(_fallback_row(bom_row))

    return status_rows


def missing_notes(payload, as_of=None):
    """Port of MissingNotesController::missingNotes(): the 14-section computation.

    payload: {"bom_data": [...], "smtp_details": [...], "rfqs": [...], "include_proto": bool,
        "uncosted_rows": [...]} -- uncosted_rows is built by the adapter directly from
        cbom.is_costed==FALSE (see templates/excel_mappings.py::to_missing_notes_payload).
    as_of: stands in for PHP's Carbon::now() in section 7 (Price Validity);
        defaults to the real current time so behavior matches the original
        unless the caller wants a deterministic value (e.g. for tests).
    returns: list of {"heading", "description", "data"} — only for sections
        that found at least one match, in heading_id order 1-14.
    """
    bom_data = payload.get("bom_data", [])
    smtp_details = payload.get("smtp_details", [])
    rfqs = payload.get("rfqs", [])
    include_proto = payload.get("include_proto", False)
    uncosted_rows = payload.get("uncosted_rows", [])
    as_of = as_of or datetime.now()

    bom_cpn_set = {row.get("CPN") for row in bom_data if row.get("CPN")}

    bom_commodity_by_cpn = {}
    for row in bom_data:
        cpn = row.get("CPN")
        if cpn is not None:
            bom_commodity_by_cpn[cpn] = row.get("Commodity", "")

    bom_mfr_by_cpn_mpn = {}
    for row in bom_data:
        cpn = row.get("CPN") or ""
        mpn = row.get("MPN") or ""
        bom_mfr_by_cpn_mpn[f"{cpn}||{mpn}"] = row.get("MFR", "")

    smtp_manufacturer_by_mpn = {
        row.get("mpn"): row.get("manufacturer") for row in smtp_details if row.get("manufacturer")
    }

    bom_by_cpn = {}
    for row in bom_data:
        cpn = row.get("CPN")
        if cpn and cpn not in bom_by_cpn:
            bom_by_cpn[cpn] = row

    rfq_base = sorted((r for r in rfqs if r.get("is_L1") is True), key=lambda r: r.get("id") or 0)

    sections = []

    def add(heading, description, data):
        if data:
            sections.append({"heading": heading, "description": description, "data": data})

    add("Uncosted Parts", "CPNs missing in RFQ or without L1 entries",
        _section_uncosted_parts(uncosted_rows))
    add("Customer Price Control", "Price Control Mentioned customer",
        _section_customer_price_control(rfq_base, bom_mfr_by_cpn_mpn))
    add("NCNR Mentioned", "NCNR is mentioned as Yes in RFQ",
        _section_ncnr_mentioned(rfq_base, bom_mfr_by_cpn_mpn))
    add("Corrected MPN Mentioned", "Corrected MPN is mentioned in RFQ",
        _section_corrected_mpn(rfq_base, bom_mfr_by_cpn_mpn))
    add("Supplier Type Contains Advance", "Supplier Type contains 'advance' in RFQ",
        _section_supplier_type_advance(rfq_base, bom_mfr_by_cpn_mpn))
    if include_proto:
        add("Proto Pricing No Cost", "Proto pricing has no cost in RFQ",
            _section_proto_pricing_no_cost(bom_by_cpn, rfqs, bom_mfr_by_cpn_mpn))
    add("Price Validity < 30 Days", "Expiry date is within 30 days from today",
        _section_price_validity(rfq_base, bom_mfr_by_cpn_mpn, as_of))
    add("MPN Mismatch with BOM", "MPN in RFQ not aligned with BOM Data",
        _section_cpn_mismatch(rfq_base, bom_cpn_set, bom_mfr_by_cpn_mpn))
    add("Commodity Mismatch", "Commodity in RFQ not aligned with Scrub BOM",
        _section_commodity_mismatch(rfq_base, bom_data, bom_cpn_set, bom_commodity_by_cpn, bom_mfr_by_cpn_mpn))
    add("Manufacturer Name Mismatch", "Manufacturer name in RFQ does not match smtp_details for same MPN",
        _section_manufacturer_mismatch(rfq_base, smtp_manufacturer_by_mpn, bom_mfr_by_cpn_mpn))
    add("MPNs in RFQ not matching BOM Subset", "MPNs in RFQ not part of BOM-defined MPN set for that CPN",
        _section_mpn_subset_mismatch(rfq_base, bom_data, bom_cpn_set, bom_mfr_by_cpn_mpn))

    status_rows = _section_part_status(bom_data, rfq_base, bom_mfr_by_cpn_mpn)
    for status_key in ("NRFND", "DISCONTINUED", "EOL"):
        heading, description = _STATUS_CONFIGS[status_key]
        add(heading, description, status_rows[status_key])

    return sections


def flatten_missing_notes(sections):
    """Port of exportAllMissingNotes()'s flattening into the Excel-ready 2D array."""
    header = ["Sl.no", "Part Number", "Description", "Commodity", "Mfg Name",
              "Mfg Part Number", "x", "Quoted MFR", "Quoted MPN", "Remarks"]
    excel_data = []
    section_no = 1
    for section in sections:
        excel_data.append([f"{section_no}. {section['heading']}"])
        section_no += 1
        excel_data.append(list(header))
        for sl, part in enumerate(section["data"], start=1):
            quoted_mpn = part.get("quotedMpn") or part.get("correctedMpn") or ""
            excel_data.append([
                sl,
                part.get("partNumber", ""),
                part.get("description", ""),
                part.get("commodity", ""),
                part.get("mfgName", ""),
                part.get("mfgPartNumber", ""),
                part.get("x", ""),
                part.get("quotedMfr", ""),
                quoted_mpn,
                part.get("remarks", ""),
            ])
        excel_data.append([""])
        excel_data.append([""])
    return excel_data


_HEADING_FILL = PatternFill("solid", fgColor="2F5496")
_HEADING_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="D9E2F3")
_HEADER_FONT = Font(bold=True)
_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")
_WRAP_CENTER = Alignment(wrapText=True, vertical="center")
_THIN_SIDE = Side(style="thin", color="000000")
_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)

_HEADING_RE = re.compile(r"^\d+\.\s+")


def build_missing_notes_sheet(wb, rows):
    """Port of MissingNotesExport: styles the flattened Missing Notes rows.

    wb: an openpyxl.Workbook to append the sheet to.
    rows: the flattened 2D array from missing_notes.md — section-title
        rows (single cell matching '<n>. <heading>'), 'Sl.no' header
        rows, data rows, and blank ('') gap rows between sections.
    """
    ws = wb.create_sheet(title="Missing Notes")
    if not rows:
        return ws

    for row in rows:
        ws.append(row)

    last_row = len(rows)
    last_col = max((len(row) for row in rows), default=0)

    for r, row in enumerate(rows, start=1):
        if len(row) == 1 and isinstance(row[0], str) and _HEADING_RE.match(row[0]):
            _style_row(ws, r, last_col, fill=_HEADING_FILL, font=_HEADING_FONT)
        elif row and isinstance(row[0], str) and row[0].strip().lower() == "sl.no":
            _style_row(ws, r, last_col, fill=_HEADER_FILL, font=_HEADER_FONT)
        elif any(str(cell).strip() != "" for cell in row):
            _style_row(ws, r, last_col, fill=_DATA_FILL)
        # else: blank gap row — no style, matching the original.

    if last_row and last_col:
        for r in range(1, last_row + 1):
            for c in range(1, last_col + 1):
                cell = ws.cell(row=r, column=c)
                cell.alignment = _WRAP_CENTER
                cell.border = _THIN_BORDER

    # ponytail: no native auto-size in openpyxl; approximate from content length
    for col_index in range(1, last_col + 1):
        letter = get_column_letter(col_index)
        max_len = max((len(str(row[col_index - 1])) for row in rows if col_index - 1 < len(row)), default=0)
        ws.column_dimensions[letter].width = max_len + 2

    return ws


def _style_row(ws, row_num, last_col, fill, font=None):
    for c in range(1, last_col + 1):
        cell = ws.cell(row=row_num, column=c)
        cell.fill = fill
        if font is not None:
            cell.font = font
        cell.alignment = _WRAP_CENTER


def _demo():
    rows = [
        ["1. Uncosted Parts"],
        ["Sl.no", "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "x", "Quoted MFR", "Quoted MPN", "Remarks"],
        [1, "CPN-1001", "Resistor 10k", "Passive", "ACME", "MPN-1001", "", "", "", ""],
        [""],
        [""],
        ["2. Customer Price Control"],
        ["Sl.no", "Part Number", "Description", "Commodity", "Mfg Name", "Mfg Part Number", "x", "Quoted MFR", "Quoted MPN", "Remarks"],
        [1, "CPN-1002", "Capacitor 1uF", "Passive", "ACME", "MPN-1002", "", "ACME", "", ""],
        [""],
        [""],
    ]

    from openpyxl import Workbook

    wb = Workbook()
    ws = build_missing_notes_sheet(wb, rows)

    assert ws.title == "Missing Notes"

    # Heading row (row 1): navy fill, white bold font.
    heading_cell = ws.cell(row=1, column=1)
    assert heading_cell.fill.fgColor.rgb.endswith("2F5496")
    assert heading_cell.font.bold is True
    assert heading_cell.font.color.rgb.endswith("FFFFFF")

    # 'Sl.no' header row (row 2): light blue-grey fill, bold font.
    header_cell = ws.cell(row=2, column=1)
    assert header_cell.fill.fgColor.rgb.endswith("D9E2F3")
    assert header_cell.font.bold is True

    # Data row (row 3): light-blue fill.
    data_cell = ws.cell(row=3, column=2)
    assert data_cell.fill.fgColor.rgb.endswith("F2F6FC")

    # Gap row (row 4, [""]) gets no fill.
    gap_cell = ws.cell(row=4, column=1)
    assert gap_cell.fill.fgColor.rgb in (None, "00000000")

    # Global border pass applied to every cell in the used range.
    assert data_cell.border.left.style == "thin"

    print("build_missing_notes_sheet self-check passed")

    _demo_full_pipeline(wb)


def _demo_full_pipeline(wb):
    # Same 13-CPN sample dataset documented in missing_notes.md, engineered
    # so every one of the 14 sections has at least one match.
    payload = {
        "bom_upload_id": 123,
        "include_proto": True,
        "bom_data": [
            {"CPN": "CPN-1001", "MPN": "MPN-1001", "Description": "Resistor 10k", "Commodity": "Passive", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1002", "MPN": "MPN-1002", "Description": "Capacitor 1uF", "Commodity": "Passive", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1003", "MPN": "MPN-1003", "Description": "Diode", "Commodity": "Semiconductor", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1004", "MPN": "MPN-1004", "Description": "Transistor", "Commodity": "Semiconductor", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1005", "MPN": "MPN-1005", "Description": "Connector", "Commodity": "Electromechanical", "MFR": "Vendor-Y", "Part Status": "Active"},
            {"CPN": "CPN-1006", "MPN": "MPN-1006", "Description": "Inductor", "Commodity": "Passive", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1007", "MPN": "MPN-1007", "Description": "IC Regulator", "Commodity": "Semiconductor", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1009", "MPN": "MPN-1009", "Description": "Relay", "Commodity": "Mechanical", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1010", "MPN": "MPN-1010", "Description": "Crystal Osc", "Commodity": "Passive", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1011", "MPN": "MPN-1011-A", "Description": "Switch", "Commodity": "Electromechanical", "MFR": "ACME", "Part Status": "Active"},
            {"CPN": "CPN-1012", "MPN": "MPN-1012", "Description": "Old Chip", "Commodity": "Semiconductor", "MFR": "ACME", "Part Status": "NRFND"},
            {"CPN": "CPN-1013", "MPN": "MPN-1013", "Description": "Legacy Part", "Commodity": "Semiconductor", "MFR": "ACME", "Part Status": "Discontinued"},
            {"CPN": "CPN-1014", "MPN": "MPN-1014", "Description": "End-of-Life Part", "Commodity": "Semiconductor", "MFR": "ACME", "Part Status": "EOL"},
        ],
        "smtp_details": [
            {"mpn": "MPN-1010", "manufacturer": "ACME Real"},
        ],
        # Supplied ready-made by the adapter in production (built from cbom.is_costed
        # ==FALSE) -- CPN-1001/1012/1013/1014 are the ones with no rfqs entry below.
        "uncosted_rows": [
            {"id": None, "partNumber": "CPN-1001", "description": "Resistor 10k", "commodity": "Passive",
             "mfgName": "ACME", "mfgPartNumber": "MPN-1001", "x": "", "quotedMfr": "", "quotedMpn": "", "remarks": ""},
            {"id": None, "partNumber": "CPN-1012", "description": "Old Chip", "commodity": "Semiconductor",
             "mfgName": "ACME", "mfgPartNumber": "MPN-1012", "x": "", "quotedMfr": "", "quotedMpn": "", "remarks": ""},
            {"id": None, "partNumber": "CPN-1013", "description": "Legacy Part", "commodity": "Semiconductor",
             "mfgName": "ACME", "mfgPartNumber": "MPN-1013", "x": "", "quotedMfr": "", "quotedMpn": "", "remarks": ""},
            {"id": None, "partNumber": "CPN-1014", "description": "End-of-Life Part", "commodity": "Semiconductor",
             "mfgName": "ACME", "mfgPartNumber": "MPN-1014", "x": "", "quotedMfr": "", "quotedMpn": "", "remarks": ""},
        ],
        "rfqs": [
            {"id": 502, "cpn": "CPN-1002", "MPN": "MPN-1002", "is_L1": True, "part_description": "Capacitor 1uF", "commodity": "Passive", "manufacturer_name": "ACME", "price_control": "customer"},
            {"id": 503, "cpn": "CPN-1003", "MPN": "MPN-1003", "is_L1": True, "part_description": "Diode", "commodity": "Semiconductor", "manufacturer_name": "ACME", "ncnr": "yes"},
            {"id": 504, "cpn": "CPN-1004", "MPN": "MPN-1004", "is_L1": True, "part_description": "Transistor", "commodity": "Semiconductor", "manufacturer_name": "ACME", "corrected_MPN": "MPN-1004A"},
            {"id": 505, "cpn": "CPN-1005", "MPN": "MPN-1005", "is_L1": True, "part_description": "Connector", "commodity": "Electromechanical", "manufacturer_name": "Vendor-Y", "supplier_type": "advance"},
            {"id": 506, "cpn": "CPN-1006", "MPN": "MPN-1006", "is_L1": True, "volume_no": 1, "part_description": "Inductor", "commodity": "Passive", "manufacturer_name": "ACME", "vol_pricing": 0, "vol_moq": 250},
            {"id": 507, "cpn": "CPN-1007", "MPN": "MPN-1007", "is_L1": True, "part_description": "IC Regulator", "commodity": "Semiconductor", "manufacturer_name": "ACME", "expiry_date": "2026-07-20"},
            {"id": 508, "cpn": "CPN-1008", "MPN": "MPN-1008", "is_L1": True, "part_description": "Ghost Part", "commodity": "Unknown", "manufacturer_name": "Nobody"},
            {"id": 509, "cpn": "CPN-1009", "MPN": "MPN-1009", "is_L1": True, "part_description": "Relay", "commodity": "Electrical", "manufacturer_name": "ACME"},
            {"id": 510, "cpn": "CPN-1010", "MPN": "MPN-1010", "is_L1": True, "part_description": "Crystal Osc", "commodity": "Passive", "manufacturer_name": "Generic Corp"},
            {"id": 511, "cpn": "CPN-1011", "MPN": "MPN-1011-B", "is_L1": True, "part_description": "Switch", "commodity": "Electromechanical", "manufacturer_name": "ACME"},
        ],
    }

    as_of = datetime(2026, 7, 10)
    sections = missing_notes(payload, as_of=as_of)

    expected_headings = [
        ("Uncosted Parts", "CPNs missing in RFQ or without L1 entries"),
        ("Customer Price Control", "Price Control Mentioned customer"),
        ("NCNR Mentioned", "NCNR is mentioned as Yes in RFQ"),
        ("Corrected MPN Mentioned", "Corrected MPN is mentioned in RFQ"),
        ("Supplier Type Contains Advance", "Supplier Type contains 'advance' in RFQ"),
        ("Proto Pricing No Cost", "Proto pricing has no cost in RFQ"),
        ("Price Validity < 30 Days", "Expiry date is within 30 days from today"),
        ("MPN Mismatch with BOM", "MPN in RFQ not aligned with BOM Data"),
        ("Commodity Mismatch", "Commodity in RFQ not aligned with Scrub BOM"),
        ("Manufacturer Name Mismatch", "Manufacturer name in RFQ does not match smtp_details for same MPN"),
        ("MPNs in RFQ not matching BOM Subset", "MPNs in RFQ not part of BOM-defined MPN set for that CPN"),
        ("NRFND", "Part Status is NRFND in Scrub BOM or QW/RFQ"),
        ("Discontinued", "Part Status is Discontinued in Scrub BOM or QW/RFQ"),
        ("EOL", "Part Status is EOL in Scrub BOM or QW/RFQ"),
    ]
    actual_headings = [(s["heading"], s["description"]) for s in sections]
    assert actual_headings == expected_headings, actual_headings

    by_heading = {s["heading"]: s["data"] for s in sections}

    # Uncosted Parts is now a pure passthrough of the adapter-supplied uncosted_rows.
    uncosted = {r["partNumber"]: r for r in by_heading["Uncosted Parts"]}
    assert set(uncosted) == {"CPN-1001", "CPN-1012", "CPN-1013", "CPN-1014"}
    assert uncosted["CPN-1001"]["id"] is None

    corrected = by_heading["Corrected MPN Mentioned"][0]
    assert corrected["correctedMpn"] == "MPN-1004A"
    assert corrected["quotedMpn"] == "MPN-1004A"

    proto_rows = {r["partNumber"]: r for r in by_heading["Proto Pricing No Cost"]}
    assert proto_rows["CPN-1006"]["vol_moq"] == 250

    # CPN-1008 has no bom_data row at all -- it's now excluded here (only flagged
    # under "MPN Mismatch with BOM"), fixing the old double-report of the same fact
    # under two headings. Only CPN-1009 (a real commodity discrepancy) remains.
    commodity_mismatch_by_cpn = {r["partNumber"]: r for r in by_heading["Commodity Mismatch"]}
    assert set(commodity_mismatch_by_cpn) == {"CPN-1009"}
    assert commodity_mismatch_by_cpn["CPN-1009"]["remarks"] == "Scrub BOM commodity: Mechanical"

    manufacturer_row = by_heading["Manufacturer Name Mismatch"][0]
    assert manufacturer_row["smtpManufacturer"] == "ACME Real"

    # Same double-report fix: CPN-1008 no longer appears here either -- CPN-1011 (a
    # real MPN discrepancy, quoted MPN-1011-B vs BOM's MPN-1011-A) is the only row.
    mpn_subset_rows = by_heading["MPNs in RFQ not matching BOM Subset"]
    assert {r["partNumber"] for r in mpn_subset_rows} == {"CPN-1011"}
    assert mpn_subset_rows[0]["remarks"] == "MPN not in BOM subset for this CPN"

    nrfnd_row = by_heading["NRFND"][0]
    assert nrfnd_row["partNumber"] == "CPN-1012"
    assert nrfnd_row["id"] is None  # no matching RFQ row — fallback from bom_data

    print("missing_notes() self-check passed (all 14 headings present)")

    flat_rows = flatten_missing_notes(sections)
    assert flat_rows[0] == ["1. Uncosted Parts"]
    assert flat_rows[1][0] == "Sl.no"
    assert flat_rows[2][1] == "CPN-1001"
    # Uncosted Parts has 4 rows here (CPN-1001/1012/1013/1014 all lack any RFQ),
    # so find the next section's title dynamically rather than assume 1 data row.
    next_title_index = next(i for i, row in enumerate(flat_rows) if row == ["2. Customer Price Control"])
    assert flat_rows[next_title_index - 1] == [""] and flat_rows[next_title_index - 2] == [""]
    assert flat_rows[-1] == [""] and flat_rows[-2] == [""]

    print("flatten_missing_notes() self-check passed")

    ws2 = build_missing_notes_sheet(wb, flat_rows)
    assert ws2.cell(row=1, column=1).value == "1. Uncosted Parts"
    print("full pipeline (compute -> flatten -> style) self-check passed")


if __name__ == "__main__":
    _demo()
