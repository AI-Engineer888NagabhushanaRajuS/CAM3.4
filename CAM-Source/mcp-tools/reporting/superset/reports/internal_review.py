"""The Internal Review tab: where the money sits, read three ways (sourcing channel, commodity, quote age).

Drills keeps this as a hand-made management pivot. Here every figure comes from the same costed rows as the CBOM tab for the first
numbered volume, and each block ends with a check that the split adds back to that total. Spend is ext_price_conv on costed lines.
"""
from datetime import date

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TOTAL_FONT = Font(bold=True)
_MONEY = '"$"#,##0.00'
_PCT = "0.0%"
_AGE_BUCKETS = [("Under 30 days", 0, 30), ("30 to 90 days", 30, 90), ("90 to 180 days", 90, 180), ("Over 180 days", 180, None)]
_NO_DATE = "No quote date"


def _first_numbered_volume(cbom_df):
    volumes = sorted({str(v) for v in cbom_df["volume_no"].dropna() if str(v).lower() != "proto"}, key=lambda v: (len(v), v))
    return volumes[0] if volumes else None


def _costed_lines(cbom_df, quote_df, today):
    """One row per costed line of the first numbered volume, with its channel, commodity and the quote's age in days."""
    volume = _first_numbered_volume(cbom_df)
    lines = cbom_df[cbom_df["volume_no"].astype(str) == volume] if volume is not None else cbom_df.iloc[0:0]
    if "is_data" in lines:
        lines = lines[lines["is_data"] == True]  # noqa: E712 -- the column holds numpy bools
    lines = lines[lines["ext_price_conv"].notna()].copy()
    lines["channel"] = lines["supplier_type"].fillna("(unspecified)").astype(str) if "supplier_type" in lines else "(unspecified)"
    lines["commodity_name"] = lines["commodity"].fillna("(unspecified)").astype(str) if "commodity" in lines else "(unspecified)"
    eff = pd.to_datetime(quote_df["eff_date"], errors="coerce") if "eff_date" in quote_df else pd.Series(dtype="datetime64[ns]")
    latest = pd.DataFrame({"cpn": quote_df["part_number"].astype(str), "eff": eff}).dropna(subset=["eff"])
    latest = latest.groupby("cpn")["eff"].max()
    lines["quote_date"] = lines["cpn"].astype(str).map(latest)
    lines["age_days"] = (pd.Timestamp(today) - lines["quote_date"]).dt.days
    lines["age_bucket"] = lines["age_days"].apply(_bucket_of)
    return volume, lines


def _bucket_of(days):
    if pd.isna(days):
        return _NO_DATE
    for label, low, high in _AGE_BUCKETS:
        if days >= low and (high is None or days < high):
            return label
    return _NO_DATE


def _header(ws, row, labels):
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _block(ws, start_row, title, key_label, groups, total_value):
    """One split: a row per group (lines, spend, share of spend), a formula total, and the reconciliation line.

    groups: list of (label, line_count, spend) sorted by spend. Returns the next free row.
    """
    ws.cell(row=start_row, column=1, value=title).font = _TOTAL_FONT
    header_row = start_row + 1
    _header(ws, header_row, [key_label, "Lines", "Spend", "Share of spend"])
    first = header_row + 1
    for i, (label, count, spend) in enumerate(groups):
        row = first + i
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=2, value=count)
        ws.cell(row=row, column=3, value=round(float(spend), 2)).number_format = _MONEY
    last = first + max(len(groups), 1) - 1
    total_row = last + 1
    ws.cell(row=total_row, column=1, value="Total").font = _TOTAL_FONT
    ws.cell(row=total_row, column=2, value=f"=SUM(B{first}:B{last})").font = _TOTAL_FONT
    ws.cell(row=total_row, column=3, value=f"=SUM(C{first}:C{last})").font = _TOTAL_FONT
    ws.cell(row=total_row, column=3).number_format = _MONEY
    for row in range(first, last + 1):
        share = ws.cell(row=row, column=4, value=f'=IFERROR(C{row}/C${total_row},0)')
        share.number_format = _PCT
    ws.cell(row=total_row, column=4, value=f"=IFERROR(C{total_row}/C{total_row},0)").number_format = _PCT
    check_row = total_row + 1
    ws.cell(row=check_row, column=1, value="Reconciles to the CBOM spend")
    ws.cell(row=check_row, column=3, value=f'=IF(ABS(C{total_row}-{round(float(total_value), 2)})<0.01,"OK","CHECK")')
    return check_row + 2


def build_internal_review_sheet(wb, cbom_df, quote_df, today=None):
    """Adds the Internal Review tab to wb. Empty input still builds the tab, with zero spend and the checks saying so."""
    today = today or date.today()
    ws = wb.create_sheet(title="Internal Review")
    ws["A1"] = "Internal Review"
    ws["A1"].font = Font(bold=True, size=13)
    volume, lines = _costed_lines(cbom_df, quote_df, today)
    ws["A2"] = f"Costed lines of volume {volume if volume is not None else '-'} as of {today.isoformat()}. Spend is the extended conv. price."
    ws["A2"].font = Font(italic=True, color="595959")
    total_spend = float(lines["ext_price_conv"].sum()) if len(lines) else 0.0

    def groups_by(column):
        if len(lines) == 0:
            return []
        grouped = lines.groupby(column).agg(count=("cpn", "size"), spend=("ext_price_conv", "sum")).reset_index()
        grouped = grouped.sort_values("spend", ascending=False)
        return [(str(r[column]), int(r["count"]), r["spend"]) for _, r in grouped.iterrows()]

    row = 4
    row = _block(ws, row, "By sourcing channel", "Sourcing channel", groups_by("channel"), total_spend)
    row = _block(ws, row, "By commodity", "Commodity", groups_by("commodity_name"), total_spend)
    age_order = [label for label, _, _ in _AGE_BUCKETS] + [_NO_DATE]
    age_groups = [(label, count, spend) for label, count, spend in groups_by("age_bucket")]
    age_groups.sort(key=lambda g: age_order.index(g[0]))
    _block(ws, row, "By quote age (the part's latest quote date)", "Quote age", age_groups, total_spend)

    for col, width in zip("ABCD", (42, 12, 18, 16)):
        ws.column_dimensions[col].width = width
    return ws
