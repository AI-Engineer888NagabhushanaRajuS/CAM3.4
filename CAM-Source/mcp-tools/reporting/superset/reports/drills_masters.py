"""Drills' three small lookup sheets: 'Supplier', 'Currency' and 'Batch Qty' (Drills hides all three; hidden=True does the same).

Supplier   Drills' sheet is Centum's supplier master (2,145 rows from the ERP, 17 columns). CAM keeps no supplier master: the one
           source is the file CAM_SUPPLIER_MASTER points at (the same file reports/new_suppliers.py reads) or a master given by the
           caller. With a master, its rows are copied unchanged. Without one the sheet lists only the RFQ's awarded suppliers
           (cbom.final_supp_name) in the Name column and every other column is yellow, to fill. Nothing is guessed.
Currency   Currency | Value: units of the currency per 1 USD, from Postgres logic_db_2.currency_conversion_rates (is_active), the
           table every CAM conversion reads (currency.get_currency_rates()). Drills' sheet reads INR 95, USD 1 the same way.
Batch Qty  Assembly | <volume> Qty | <volume> Batch Qty | <volume> Batch Count, one block per volume. Qty = input_db.volume
           (volume_name, batch_qty: the table's batch_qty column holds the volume's quantity), Batch Qty = input_db.batch.batch_qty,
           Batch Count = how many batch rows the FG has for that volume. The meaning of Batch Count is inferred: Drills shows 1 for
           640 pieces in batches of 160, so it is not Qty/Batch Qty; it matches the count of batch rows (unverified beyond that sample).
"""
import openpyxl
from openpyxl.styles import Font

from reports.drills_common import BORDER, CENTER, YELLOW, add_sheet, fill, mark_to_fill, order_volumes, set_widths, style_range, val, \
    volume_label

SUPPLIER_HEADERS = ["Region", "Supplier ID", "Name", "Phone", "Fax", "Address #1", "Address #2", "City", "State", "Postal Code",
                    "Country", "Supplier Type", "Currency", "RFQ Method", "RFQ Email(s)", "Notes", "Time Stamp"]
SUPPLIER_NAME_COL = 3
SUPPLIER_LEGEND = ("No supplier master (CAM_SUPPLIER_MASTER unset): only the RFQ's awarded suppliers are listed, from the CBOM. "
                   "Yellow = to fill.")


def read_supplier_master(path):
    """The supplier master workbook as rows in SUPPLIER_HEADERS order (a column the file lacks is empty); None if there is no file."""
    import os
    if not path or not os.path.exists(path):
        return None
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Supplier"] if "Supplier" in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [str(h).strip().lower() if h is not None else "" for h in next(it)]
        at = [header.index(h.lower()) if h.lower() in header else None for h in SUPPLIER_HEADERS]
        return [[row[i] if i is not None and i < len(row) else None for i in at] for row in it if any(c is not None for c in row)]
    finally:
        wb.close()


def build_supplier_sheet(wb, con, rfq_id, master_rows=None, hidden=False):
    ws = add_sheet(wb, "Supplier", hidden)
    ws.append(SUPPLIER_HEADERS)
    if master_rows:
        for row in master_rows:
            ws.append([val(c) for c in row])
        has_master = True
    else:
        for (name,) in con.execute(
                "SELECT min(trim(final_supp_name)) FROM cbom_db.cbom WHERE rfq_id = ? AND final_supp_name IS NOT NULL "
                "AND trim(final_supp_name) NOT IN ('', '-') GROUP BY upper(trim(final_supp_name)) ORDER BY 1", [rfq_id]).fetchall():
            ws.append([None, None, name] + [None] * (len(SUPPLIER_HEADERS) - 3))
        has_master = False
        ws.cell(row=1, column=len(SUPPLIER_HEADERS) + 2, value=SUPPLIER_LEGEND)
    style_supplier(ws, has_master)
    return ws


def style_supplier(ws, has_master=None):
    if has_master is None:  # restyle: the legend cell exists only without a master
        has_master = ws.cell(row=1, column=len(SUPPLIER_HEADERS) + 2).value is None
    n = len(SUPPLIER_HEADERS)
    last = max(ws.max_row, 1)
    style_range(ws, 1, 1, 1, n, font=Font(name="Arial", size=10, bold=True, color="000000"), fill_=fill("75923C"),
                align=CENTER, border=BORDER)
    if last > 1:
        style_range(ws, 2, last, 1, n, font=Font(name="Arial", size=9), align=None)
        for r in range(2, last + 1):
            for c in range(1, n + 1):
                ws.cell(row=r, column=c).alignment = openpyxl.styles.Alignment(horizontal="left", vertical="center")
        if not has_master:
            for r in range(2, last + 1):
                for c in range(1, n + 1):
                    if c != SUPPLIER_NAME_COL:
                        ws.cell(row=r, column=c).fill = YELLOW
    ws.column_dimensions["A"].width = 21.1
    ws.column_dimensions["C"].width = 40
    ws.freeze_panes = "A2"


def build_currency_sheet(wb, rates, hidden=False):
    """rates: {'USD': 1.0, 'INR': 95.0}; None when the rate table could not be read (the sheet then says so, it does not guess)."""
    ws = add_sheet(wb, "Currency", hidden)
    ws.append(["Currency", "Value"])
    if rates:
        for code in sorted(rates):
            ws.append([code, rates[code]])
    else:
        ws.append([None, None])
        mark_to_fill(ws["A2"])
        mark_to_fill(ws["B2"])
    style_currency(ws)
    return ws


def style_currency(ws):
    style_range(ws, 1, 1, 1, 2, font=Font(bold=True))
    set_widths(ws, {"A": 11.4, "B": 8.6})
    ws.freeze_panes = "A2"


def batch_rows(con, rfq_id):
    """([volumes proto-first], {fg: {volume: (qty, batch_qty, batch_count)}} in order of appearance)."""
    from queries import normalize_volume_label  # not at import time: queries needs the Postgres env of the reporting process
    qty, batch, count, fgs = {}, {}, {}, []
    for fg, volume, q in con.execute("SELECT fg, volume_name, batch_qty FROM input_db.volume WHERE rfq_id = ?", [rfq_id]).fetchall():
        key = (fg, normalize_volume_label(volume))
        qty[key] = max(qty.get(key, 0) or 0, q or 0)
        if fg not in fgs:
            fgs.append(fg)
    for fg, volume, q in con.execute("SELECT fg, volume, batch_qty FROM input_db.batch WHERE rfq_id = ?", [rfq_id]).fetchall():
        key = (fg, normalize_volume_label(volume))
        batch[key] = max(batch.get(key, 0) or 0, q or 0)
        count[key] = count.get(key, 0) + 1
        if fg not in fgs:
            fgs.append(fg)
    volumes = order_volumes({k[1] for k in list(qty) + list(batch)})
    return volumes, {fg: {v: (qty.get((fg, v)), batch.get((fg, v)), count.get((fg, v))) for v in volumes} for fg in fgs}


def build_batch_qty_sheet(wb, con, rfq_id, hidden=False):
    volumes, by_fg = batch_rows(con, rfq_id)
    ws = add_sheet(wb, "Batch Qty", hidden)
    ws.append(["Assembly"] + [f"{volume_label(v)} {what}" for v in volumes for what in ("Qty", "Batch Qty", "Batch Count")])
    for fg, per_volume in by_fg.items():
        ws.append([fg] + [x for v in volumes for x in per_volume[v]])
    style_batch_qty(ws)
    return ws


def style_batch_qty(ws):
    n = ws.max_column
    last = max(ws.max_row, 1)
    style_range(ws, 1, 1, 1, n, font=Font(name="Calibri", size=8, bold=True, color="FFFFFF"), fill_=fill("3366FF"), border=BORDER,
                align=openpyxl.styles.Alignment(horizontal="left", vertical="center"))
    if last > 1:
        style_range(ws, 2, last, 1, n, font=Font(name="Calibri", size=8), border=BORDER, number_format="0",
                    align=openpyxl.styles.Alignment(vertical="center"))
    set_widths(ws, {"A": 25.2})
    for c in range(2, n + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 14
    ws.freeze_panes = "A2"
