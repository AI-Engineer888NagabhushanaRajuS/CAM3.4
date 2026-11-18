"""The Drills input-echo sheets CAM builds from its own data, in Drills' layout: Supplier, Currency, Batch Qty and Scrub BOM (the
lookup sheets are hidden, as in Drills), then the CBOM Checklist, Sales Checklist and PCB Spec templates.

Where CAM holds no data for a cell it is yellow and marked to fill. The Drills 'Raw CBOM VL-1' tab is not built here: the CBOM tab
already carries the same lines with the full provenance model.
"""
from openpyxl.styles import Font

from reports.drills_common import BORDER, YELLOW, add_sheet, mark_to_fill, rfq_number, set_widths, style_range
from reports.drills_masters import build_batch_qty_sheet, build_currency_sheet, build_supplier_sheet
from reports.drills_scrub_bom import build_scrub_bom_sheet
from reports.drills_templates import CBOM_CHECKLIST_COLUMNS, CBOM_CHECKLIST_ITEMS, SALES_CHECKLIST_ITEMS


def _scrub_keys(con, rfq_id):
    """The stored scrub keys of other customer RFQs (CE-numbered), so the commonality column compares against Drills' RFQs. Test
    fixtures (RFQ-CENTUM-PROOF-nn and generic parts such as PAR-01) are left out, and so is every copy of this RFQ's own CE number
    (T02-/C02- copies of the same input). ponytail: Drills lists the ACTIVE versions only; the active lookup lives in Postgres, so
    this uses every stored version of those RFQs until that lookup is wired in."""
    keys = [r[0] for r in con.execute("SELECT DISTINCT rfq_id FROM input_db.scrub_bom_items").fetchall()]
    own = rfq_number(rfq_id)
    return [k for k in keys if "CE-" in k and rfq_number(k) != own]


def _scrub_labels(keys):
    """{RFQ id: 'CE-005570'}: the label Drills prints for each RFQ in the commonality column."""
    return {k.split("__")[0]: rfq_number(k) for k in keys}


def _checklist_title(ws, rfq_id):
    ws["A2"] = f"RFQ Number : {rfq_number(rfq_id)}"
    for row, label in ((3, "Account Name : "), (4, "Opportunity Name :"), (5, "Type : New / Rework :"), (6, "CBOM Rollout Date :")):
        ws.cell(row=row, column=1, value=label)
        mark_to_fill(ws.cell(row=row, column=2))


def build_cbom_checklist_sheet(wb, rfq_id, hidden=False):
    ws = add_sheet(wb, "CBOM Checklist", hidden)
    ws["A1"] = "CHECKLIST FOR CBOM VALIDATION"
    ws["A1"].font = Font(bold=True)
    _checklist_title(ws, rfq_id)
    header_row = 8
    headers = ["Sl.No", "Category", *CBOM_CHECKLIST_COLUMNS, "Remarks", "Action"]
    for col, label in enumerate(headers, start=1):
        ws.cell(row=header_row, column=col, value=label)
    for i, (category, who, remarks) in enumerate(CBOM_CHECKLIST_ITEMS, start=1):
        row = header_row + i
        ws.cell(row=row, column=1, value=i)
        ws.cell(row=row, column=2, value=category)
        for col, flag in enumerate(who, start=3):
            ws.cell(row=row, column=col, value=flag)
        ws.cell(row=row, column=3 + len(CBOM_CHECKLIST_COLUMNS), value=remarks)
        mark_to_fill(ws.cell(row=row, column=4 + len(CBOM_CHECKLIST_COLUMNS)), text=False)
    style_range(ws, header_row, header_row, 1, len(headers), border=BORDER)
    set_widths(ws, {"A": 7, "B": 44, "C": 9, "D": 9, "E": 16, "F": 16, "G": 12, "H": 12, "I": 9, "J": 70, "K": 22})
    return ws


def build_sales_checklist_sheet(wb, rfq_id, hidden=False):
    ws = add_sheet(wb, "Sales Checklist", hidden)
    ws["A1"] = "This is doc. which needs to be filled by Sourcing and send with each CBOM"
    ws["A2"] = "Quote (RFQ)No :"
    ws["B2"] = rfq_number(rfq_id)
    for row, label in ((3, "Customer Name:"), (4, "Project Name :"), (5, "Checked By:"), (6, "Date:")):
        ws.cell(row=row, column=1, value=label)
        mark_to_fill(ws.cell(row=row, column=2))
    ws["A8"] = "Checklist"
    for col, label in enumerate(["SN", "Action", "Status", "Sourcing Remarks"], start=1):
        ws.cell(row=9, column=col, value=label)
    for i, question in enumerate(SALES_CHECKLIST_ITEMS, start=1):
        row = 9 + i
        ws.cell(row=row, column=1, value=i)
        ws.cell(row=row, column=2, value=question)
        mark_to_fill(ws.cell(row=row, column=3), text=False)
        mark_to_fill(ws.cell(row=row, column=4), text=False)
    set_widths(ws, {"A": 16, "B": 90, "C": 12, "D": 40})
    return ws


_PCB_SPEC_HEADERS = ["MODEL", "Material", "Maker", "Thick.", "Inner\ncopper", "Out\nCopper\n(Base)", "Size", "Lay", "NRE Cost",
                     "Standard NPI Leadtime (days)", "Material Leadtime (days)", "PCS Size"]


def _pcb_models(con, rfq_id):
    """The PCB lines of the RFQ's scrub BOM, one model per distinct CPN (the spec columns are not in CAM's data)."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT cpn FROM input_db.scrub_bom_items WHERE rfq_id = ? AND upper(trim(commodity)) = 'PCB' ORDER BY cpn",
        [rfq_id]).fetchall()]


def build_pcb_spec_sheet(wb, con, rfq_id, hidden=False):
    ws = add_sheet(wb, "PCB Spec", hidden)
    ws["A1"] = "SPECIFICATIONS"
    ws["A2"] = "Material Staus"
    ws["B2"] = "Size Staus"
    for col, label in enumerate(_PCB_SPEC_HEADERS, start=1):
        ws.cell(row=3, column=col, value=label)
    for r, model in enumerate(_pcb_models(con, rfq_id), start=4):
        ws.cell(row=r, column=1, value=model)
        for col in range(2, len(_PCB_SPEC_HEADERS) + 1):
            mark_to_fill(ws.cell(row=r, column=col), text=False)
    style_range(ws, 3, 3, 1, len(_PCB_SPEC_HEADERS), border=BORDER)
    set_widths(ws, {"A": 26, "B": 14, "C": 14, "D": 10, "E": 12, "F": 12, "G": 10, "H": 8, "I": 12, "J": 16, "K": 16, "L": 12})
    return ws


def build_drills_sheets(wb, con, rfq_id, rates, supplier_master_rows=None):
    """Adds the Drills input-echo sheets to wb. rates: {'USD': 1.0, 'INR': ...} from currency.get_currency_rates() (None if unreadable)."""
    build_supplier_sheet(wb, con, rfq_id, master_rows=supplier_master_rows, hidden=True)
    build_currency_sheet(wb, rates, hidden=True)
    build_batch_qty_sheet(wb, con, rfq_id, hidden=True)
    keys = _scrub_keys(con, rfq_id)
    build_scrub_bom_sheet(wb, con, rfq_id, active_keys=keys, labels=_scrub_labels(keys))
    build_cbom_checklist_sheet(wb, rfq_id)
    build_sales_checklist_sheet(wb, rfq_id)
    build_pcb_spec_sheet(wb, con, rfq_id)
    return ["Supplier", "Currency", "Batch Qty", "Scrub BOM", "CBOM Checklist", "Sales Checklist", "PCB Spec"]
