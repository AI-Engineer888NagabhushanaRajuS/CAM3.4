"""The Checks tab: the reconciliation panel of the Drills observation sheets (CE-005646, CE-005641), as live formulas.

Each row compares two independent sources of the same number. Drills fills this panel by hand with typed Matching / Not Matching
remarks; here both sides are read from the data and the result is a formula, so it changes if either side changes.
"""
from openpyxl.styles import Alignment, Font, PatternFill

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")


def _first_numbered_volume(cbom_df):
    volumes = sorted({str(v) for v in cbom_df["volume_no"].dropna() if str(v).lower() != "proto"}, key=lambda v: (len(v), v))
    return volumes[0] if volumes else None


def check_rows(con, rfq_id, cbom_df):
    """(check, source A label, value A, source B label, value B) for each check, from the scrub BOM, the CBOM and the volume table."""
    volume = _first_numbered_volume(cbom_df)
    # Every line of the first volume, the FG root row included: the scrub BOM lists that row too, so both sides count the same rows.
    lines = cbom_df[cbom_df["volume_no"].astype(str) == volume] if volume is not None else cbom_df.iloc[0:0]
    data_lines = lines[lines["is_data"] == True] if "is_data" in lines else lines  # noqa: E712 -- numpy bools
    scrub_cpns, scrub_qty = con.execute(
        "SELECT count(DISTINCT cpn), coalesce(sum(quantity), 0) FROM input_db.scrub_bom_items WHERE rfq_id = ?", [rfq_id]).fetchone()
    volume_rows = con.execute("SELECT count(*) FROM input_db.volume WHERE rfq_id = ?", [rfq_id]).fetchone()[0]
    cbom_volumes = len({str(v) for v in cbom_df["volume_no"].dropna()})
    costed = int(data_lines["ext_price_conv"].notna().sum()) if "ext_price_conv" in data_lines else 0
    return [
        ("CPN count", "Scrub BOM (distinct CPN)", int(scrub_cpns), "CBOM (distinct CPN, first volume)",
         int(lines["cpn"].nunique()) if len(lines) else 0),
        ("CPN quantity", "Scrub BOM (sum of Qty)", round(float(scrub_qty), 4), "CBOM (sum of Part Qty, first volume)",
         round(float(lines["part_qty"].fillna(0).sum()), 4) if len(lines) and "part_qty" in lines else 0),
        ("Volumes", "Volume table (rows)", int(volume_rows), "CBOM (volumes present)", cbom_volumes),
        ("Costed lines", "Data lines (first volume)", int(len(data_lines)), "Lines with a price", costed),
    ]


def build_checks_sheet(wb, con, rfq_id, cbom_df):
    ws = wb.create_sheet(title="Checks")
    ws["A1"] = "Checks"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Each row compares two independent sources. Result is a live formula: it changes if either side changes."
    ws["A2"].font = Font(italic=True, color="595959")
    headers = ["Sl No", "Check", "Source A", "Value A", "Source B", "Value B", "Result"]
    for col, label in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col, value=label)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, (check, a_label, a_value, b_label, b_value) in enumerate(check_rows(con, rfq_id, cbom_df), start=1):
        # the Result column is a live formula; the two values are read from the data above
        row = 4 + i
        ws.cell(row=row, column=1, value=i)
        ws.cell(row=row, column=2, value=check)
        ws.cell(row=row, column=3, value=a_label)
        ws.cell(row=row, column=4, value=a_value)
        ws.cell(row=row, column=5, value=b_label)
        ws.cell(row=row, column=6, value=b_value)
        ws.cell(row=row, column=7, value=f'=IF(ABS(D{row}-F{row})<0.0001,"Matching","Not Matching")').font = Font(bold=True)
    for col, width in zip("ABCDEFG", (8, 18, 30, 14, 38, 14, 16)):
        ws.column_dimensions[col].width = width
    return ws
