"""Builds the CAM reports dashboard inside the Superset container: the charts and datasets over the reports file, placed on the
embedded dashboard (slug cam-reports). Run inside the container after the "CAM reports" database is registered at
duckdb:////app/cam-database/reports.duckdb?access_mode=read_only (see the fix in the commit log). Safe to re-run."""
import json, uuid
from superset.app import create_app

DASH_UUID = "a82d4ef7-4542-4354-a8d8-e7bb92ffaf88"

def metric(col, agg, label):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": agg, "label": label, "optionName": label}

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard

    database = db.session.query(Database).filter_by(database_name="CAM reports").one()

    def dataset(name):
        ds = db.session.query(SqlaTable).filter_by(table_name=name, database_id=database.id).first()
        if ds is None:
            ds = SqlaTable(table_name=name, sql=f"SELECT * FROM {name}", database=database, schema=None)
            db.session.add(ds)
            db.session.commit()
            ds.fetch_metadata()
            db.session.commit()
        return ds

    def chart(name, viz, ds, params):
        s = db.session.query(Slice).filter_by(slice_name=name).first()
        base = {"datasource": f"{ds.id}__table", "adhoc_filters": [], "row_limit": 1000}
        base.update(params)
        if s is None:
            s = Slice(slice_name=name, viz_type=viz, datasource_type="table", datasource_id=ds.id, params=json.dumps(base))
            db.session.add(s)
        else:
            s.viz_type = viz; s.datasource_id = ds.id; s.params = json.dumps(base)
        db.session.commit()
        return s

    summary = dataset("summary_report")
    price = dataset("price_control_report")
    lead = dataset("lead_time_consolidated_report")
    cash = dataset("batchwise_cashflow_report")
    abc = dataset("aclass_parts_report")

    charts = [
        chart("Cost per set by assembly (VL-1..n)", "echarts_timeseries_bar", summary,
              {"x_axis": "fg", "metrics": [metric("ext_vol_conv_price", "SUM", "Extended volume cost")], "groupby": ["volume_no"], "orientation": "vertical", "show_legend": True, "order_desc": True, "x_axis_sort_asc": True, "x_axis_sort_series": "name"}),
        chart("MOQ cost by assembly", "echarts_timeseries_bar", summary,
              {"x_axis": "fg", "metrics": [metric("moq_cost", "SUM", "MOQ cost")], "groupby": ["volume_no"], "orientation": "vertical", "show_legend": True, "order_desc": True}),
        chart("Total MOQ cost", "big_number_total", summary,
              {"metric": metric("moq_cost", "SUM", "MOQ cost"), "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": "SMART_NUMBER"}),
        chart("Who set the price", "pie", price,
              {"metric": metric("bucket_total", "SUM", "Value"), "groupby": ["price_control"], "donut": True, "show_labels": True, "label_type": "key_percent"}),
        chart("Parts by lead time (weeks)", "echarts_timeseries_bar", lead,
              {"x_axis": "lead_time", "metrics": [metric("cpn_count", "SUM", "Parts")], "groupby": [], "orientation": "vertical", "show_legend": False, "order_desc": False, "x_axis_sort_asc": True, "x_axis_sort_series": "name"}),
        chart("Final buy by payment term", "echarts_timeseries_bar", cash,
              {"x_axis": "volume_no", "metrics": [metric("sum_final_buy_value", "SUM", "Final buy")], "groupby": ["supplier_type"], "orientation": "vertical", "show_legend": True}),
        # Matrix, not a pie: ABC class down the side, commodity across, each cell the value of the parts in it.
        chart("Value by ABC class and commodity", "heatmap_v2", abc,
              {"x_axis": "commodity", "groupby": "abc_classification", "metric": metric("ext_price_conv", "SUM", "Value"),
               "linear_color_scheme": "blue_white_yellow", "normalize_across": "heatmap", "show_values": True,
               "sort_x_axis": "value_desc", "sort_y_axis": "alpha_asc", "show_legend": True}),
    ]
    table = db.session.query(Slice).filter_by(slice_name="Reports: summary by RFQ").first()
    if table is not None:
        charts.append(table)

    dash = db.session.query(Dashboard).filter_by(slug="cam-reports").first()
    dash.slices = charts
    rows = {
        "ROW-KPI": [charts[2]],
        "ROW-BARS": [charts[0], charts[1]],
        "ROW-SPLIT": [charts[3], charts[4]],
        "ROW-CASH": [charts[5], charts[6]],
    }
    if table is not None:
        rows["ROW-TABLE"] = [table]
    position = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": list(rows.keys()), "parents": ["ROOT_ID"]}}
    for rid, items in rows.items():
        width = 12 if len(items) == 1 and items[0] is table else (4 if len(items) == 1 else (6 if len(items) == 2 else 12))
        position[rid] = {"type": "ROW", "id": rid, "children": [f"CHART-{s.id}" for s in items], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for s in items:
            w = 12 if s is table else (4 if s is charts[2] else 6)
            position[f"CHART-{s.id}"] = {"type": "CHART", "id": f"CHART-{s.id}", "children": [], "parents": ["ROOT_ID", "GRID_ID", rid], "meta": {"width": w, "height": 60 if s is not table else 70, "chartId": s.id, "sliceName": s.slice_name}}
    dash.position_json = json.dumps(position)
    db.session.commit()
    print("DASHBOARD", dash.id, "charts", [s.slice_name for s in dash.slices])
