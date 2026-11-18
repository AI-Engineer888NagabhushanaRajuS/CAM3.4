"""Drills 'Scrub BOM' sheet: the RFQ's scrub BOM with the three "common with" columns, plus the CPN&MPN key list (columns Q:U).

Columns A:N are Drills' own (Scrub BOM!A1:N1 of CE-005864 Rev0). Where each comes from:
  Assembly Name, CPN, Description, Manufacture, MPN, Commodity, Qty, UOM, Part Status, LTB Date
      input_db.scrub_bom_items (assembly, cpn, description, manufacturer, mpn, commodity, quantity, unit_of_measure, part_status,
      ltb_date). Drills prints 'NA' for a part with no status (documents, packing); so does this sheet.
  Common with AML(MPN)   scrub_bom_items.common_aml. Checked on RFQ B25-CE-005864 against the Drills sheet: the 45 rows CAM flags are
                         exactly the 45 rows Drills has 'Match' in this column.
  Common with AML(CPN)   no CAM data (needs Centum's AML dump): yellow, to fill.
  Common with Other RFQ  the other RFQs' scrub rows of their ACTIVE versions that carry the same CPN, as 'RFQ | RFQ | ...'
                         (see common_with_other_rfq). In the Drills sheet every row of one CPN shows one identical list, two rows
                         with the same MPN under different CPNs show different lists: the key is the CPN.
  Package Code           no CAM data: yellow, to fill.
Columns Q:U are Drills' helper block: the distinct (CPN, MPN) pairs in order of first appearance, and U = Q&T as a live formula
('=Q2&T2' in Drills).
"""
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font

from reports.drills_common import BORDER, YELLOW, add_sheet, base_rfq, fill, set_widths, style_range, val

HEADERS = [
    "Assembly Name", "CPN", "Description", "Manufacture", "MPN", "Commodity", "Qty", "UOM", "Part Status", "LTB Date",
    "Common with AML(MPN)", "Common with AML(CPN)", "Common with Other RFQ", "Package Code",
]
HELPER_HEADERS = ["CPN", "Description", "Manufacture", "MPN", "a"]  # Q:U
HELPER_FIRST_COL = 17  # Q
NOT_IN_CAM = {12: "Needs Centum's AML dump: not in CAM data. To fill.", 14: "Not in CAM data. To fill."}  # column -> why
LEGEND = "Yellow = to fill: Drills inputs CAM holds no data for (Common with AML(CPN), Package Code)."
CELL_LIMIT = 32000  # Excel holds at most 32,767 characters in a cell
_WIDTHS = {"A": 17.4, "B": 8.6, "C": 13.2, "D": 14.6, "E": 28.1, "F": 13.4, "G": 8.6, "H": 8.6, "I": 12.9, "J": 11.0,
           "K": 25.4, "L": 25.2, "M": 25.4, "N": 15.8, "Q": 28.1, "R": 28.1, "S": 20.0, "T": 28.1, "U": 40.0}
_HEADER_FONT = Font(bold=True, color="1F3864")  # Drills prints this white on a pale blue; dark text is readable on it


def scrub_rows(con, rfq_id):
    return [tuple(val(x) for x in r) for r in con.execute(
        "SELECT assembly, cpn, description, manufacturer, mpn, commodity, quantity, unit_of_measure, part_status, ltb_date, "
        "common_aml FROM input_db.scrub_bom_items WHERE rfq_id = ? ORDER BY display_order", [rfq_id]).fetchall()]


def common_with_other_rfq(con, rfq_id, cpns, active_keys, labels=None):
    """{CPN: 'label | label | ...'} for each CPN that also appears in another RFQ's scrub BOM.

    active_keys: the scrub rfq_id key (<RFQ> or <RFQ>__v<n>) of every RFQ's ACTIVE version. Every version of this RFQ itself is left
    out, and several active keys of one RFQ show once. labels: {RFQ id: 'CE-005697-Project name'}; an RFQ without a label shows
    its id. Sorted by label so the cell is reproducible. A list too long for an Excel cell (a database full of test RFQs) is cut
    and says how many it left out.
    """
    labels = labels or {}
    own = base_rfq(rfq_id)
    others = [k for k in active_keys or [] if base_rfq(k) != own]
    wanted = sorted({str(c).strip().upper() for c in cpns if c})
    if not others or not wanted:
        return {}
    rows = con.execute(
        "SELECT DISTINCT upper(trim(cpn)), rfq_id FROM input_db.scrub_bom_items "
        "WHERE list_contains(?, rfq_id) AND list_contains(?, upper(trim(cpn)))", [others, wanted]).fetchall()
    found = {}
    for cpn, key in rows:
        base = base_rfq(key)
        found.setdefault(cpn, set()).add(labels.get(base) or base)
    out = {}
    for cpn, names in found.items():
        text, shown = "", 0
        for name in sorted(names):
            piece = name if not text else " | " + name
            if len(text) + len(piece) > CELL_LIMIT:
                text += f" | ... (+{len(names) - shown} more)"
                break
            text += piece
            shown += 1
        out[cpn] = text
    return out


def build_scrub_bom_sheet(wb, con, rfq_id, active_keys=None, labels=None, hidden=False):
    rows = scrub_rows(con, rfq_id)
    common = common_with_other_rfq(con, rfq_id, [r[1] for r in rows], active_keys, labels)
    ws = add_sheet(wb, "Scrub BOM", hidden)
    ws.append(HEADERS)
    for assembly, cpn, description, mfr, mpn, commodity, qty, uom, status, ltb, aml in rows:
        ws.append([assembly, cpn, description, mfr, mpn, commodity, qty, uom, status or "NA", ltb, aml or None, None,
                   common.get(str(cpn).strip().upper()) if cpn else None, None])
    # Q:U helper block: distinct (CPN, MPN) in order of first appearance; U is Drills' live '=Q2&T2'
    seen = set()
    helper = []
    for assembly, cpn, description, mfr, mpn, *_ in rows:
        if (cpn, mpn) not in seen:
            seen.add((cpn, mpn))
            helper.append((cpn, description, mfr, mpn))
    for i, h in enumerate(HELPER_HEADERS):
        ws.cell(row=1, column=HELPER_FIRST_COL + i, value=h)
    for r, (cpn, description, mfr, mpn) in enumerate(helper, start=2):
        for i, v in enumerate((cpn, description, mfr, mpn)):
            ws.cell(row=r, column=HELPER_FIRST_COL + i, value=v)
        ws.cell(row=r, column=21, value=f"=Q{r}&T{r}")
    ws.cell(row=1, column=23, value=LEGEND)  # W1
    style_scrub_bom(ws)
    return ws


def style_scrub_bom(ws):
    """Idempotent: also called again after the workbook-wide presentation pass (drills_sheets.restyle_drills_sheets)."""
    last = max(ws.max_row, 2)
    # General alignment, never wrapped: a Common-with-Other-RFQ cell can hold thousands of characters (the workbook-wide pass wraps
    # any text over 40 characters, which would stretch every such row to the maximum height)
    style_range(ws, 2, last, 1, 21, align=Alignment(vertical="center"))
    style_range(ws, 1, 1, 1, len(HEADERS), font=_HEADER_FONT, fill_=fill("DBE9F7"), align=Alignment(horizontal="left", vertical="center"))
    style_range(ws, 1, 1, HELPER_FIRST_COL, 21, font=_HEADER_FONT, fill_=fill("DBE9F7"), border=BORDER)
    for col, why in NOT_IN_CAM.items():
        ws.cell(row=1, column=col).fill = YELLOW
        ws.cell(row=1, column=col).comment = Comment(why, "CAM")
        style_range(ws, 2, last, col, col, fill_=YELLOW)
    style_range(ws, 2, last, 10, 10, number_format="D/M/YYYY")
    ws.cell(row=1, column=23).font = Font(italic=True)
    set_widths(ws, _WIDTHS)
    ws.freeze_panes = "A2"
