"""'New Suppliers' tab: awarded suppliers that are not in the supplier master, with their spend per volume.

Where "new" comes from (RE 4 Domain 1 and 3: "parts awarded to suppliers not in the master"). The inputs can
tell us this in two ways, and both are implemented:

  1. Supplier master (the Supplier settings tab, 2,146 rows in the reference workbook). When CAM_SUPPLIER_MASTER
     points at a supplier master file, every awarded supplier missing from it is a new supplier.
  2. No master provided: nothing can be confirmed, so every awarded supplier is listed with "No master" and the
     Manifest says so. Nothing is guessed.

The reference code's own placeholder ("a static TRUE stub for every data row") is not used.
"""
import os

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_CURRENCY_FORMAT = '"$"#,##0.00'


def _norm(name):
    return " ".join(str(name).split()).upper()


def load_supplier_master(path=None):
    """Names from the supplier master file's Name column, or None when no master is configured."""
    path = path or os.environ.get("CAM_SUPPLIER_MASTER", "")
    if not path or not os.path.exists(path):
        return None
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = wb["Supplier"] if "Supplier" in wb.sheetnames else wb.worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    header = next(rows)
    name_col = next(i for i, h in enumerate(header) if h and "name" in str(h).lower())
    return {_norm(r[name_col]) for r in rows if r and r[name_col]}


def new_supplier_rows(cbom_records, volumes, master_names):
    """One row per awarded supplier: lines, spend per volume, and whether it is in the master.

    cbom_records: the CBOM rows as dicts (final_supp_name, cpn, volume_no, ext_part_vol_price_conv).
    volumes: volume numbers in display order (proto first, as the workbook already orders them).
    master_names: a set from load_supplier_master(), or None when no master is configured.
    """
    by_supplier = {}
    for rec in cbom_records:
        name = rec.get("final_supp_name")
        if name is None or name != name or str(name).strip() in ("", "-"):  # NaN from pandas is skipped
            continue
        entry = by_supplier.setdefault(_norm(name), {"name": str(name).strip(), "cpns": set(),
                                                     "spend": {v: 0.0 for v in volumes}})
        entry["cpns"].add(rec.get("cpn"))
        value = rec.get("ext_part_vol_price_conv")
        if rec.get("volume_no") in entry["spend"] and isinstance(value, (int, float)) and value == value:
            entry["spend"][rec["volume_no"]] += float(value)

    rows = []
    for key, entry in sorted(by_supplier.items(), key=lambda kv: kv[1]["name"].upper()):
        if master_names is None:
            status = "No master"
        else:
            status = "New" if key not in master_names else "In master"
        rows.append({"supplier": entry["name"], "status": status, "parts": len(entry["cpns"]),
                     "spend": entry["spend"]})
    return rows


def build_new_suppliers_sheet(wb, rows, volumes, master_provided):
    ws = wb.create_sheet(title="New Suppliers")
    header = ["Supplier", "Status", "Parts awarded"] + [f"Ext Vol Cost V{v}" for v in volumes]
    ws.append(header)
    for col in range(1, len(header) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for row in rows:
        ws.append([row["supplier"], row["status"], row["parts"]] + [round(row["spend"][v], 2) for v in volumes])
    for r in range(2, ws.max_row + 1):
        for col in range(4, len(header) + 1):
            ws.cell(row=r, column=col).number_format = _CURRENCY_FORMAT
    note_row = ws.max_row + 2
    note = ("Supplier master provided: New = not in it." if master_provided
            else "No supplier master provided (CAM_SUPPLIER_MASTER unset): nothing is confirmed as new.")
    ws.cell(row=note_row, column=1, value=note)
    return ws
