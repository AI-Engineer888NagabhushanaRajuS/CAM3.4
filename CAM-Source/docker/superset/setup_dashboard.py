"""Creates the Reports & Analytics dashboard in the local Superset and turns on its embedding.

Steps (from CAM-Source, Docker Desktop running; the secrets files are git-ignored):
  1. docker build -t cam-superset:4.1.1 docker/superset             (official Superset 4.1.1 + the DuckDB driver)
  2. create docker/superset/superset.env with SUPERSET_SECRET_KEY=<random>
  3. docker volume create cam-superset-home
     docker run --rm --env-file docker/superset/superset.env -v cam-superset-home:/app/superset_home cam-superset:4.1.1        sh -c "superset db upgrade && superset fab create-admin --username admin --firstname CAM --lastname Admin --email admin@cam.local --password <PW> && superset init"
  4. docker run -d --name cam-superset --env-file docker/superset/superset.env -p 8088:8088 -v cam-superset-home:/app/superset_home        -v <CAM-Source>/database:/app/cam-database:ro cam-superset:4.1.1 /usr/bin/run-server.sh
  5. register the reports database once (sqlalchemy_uri duckdb:////app/cam-database/reports.duckdb?access_mode=read_only, name "CAM reports")
  6. python setup_dashboard.py --password <PW>      (idempotent: prints the embed UUID)
Then put the UUID in the daemon and the web panel (the placeholder UUID is replaced in the source already).
Nothing secret is written to disk by this script: the password comes from the command line or SUPERSET_ADMIN_PASSWORD.
"""
import argparse
import http.cookiejar
import json
import os
import urllib.request


class Api:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.token = None
        self.csrf = None

    def _call(self, method, path, body=None, auth=True):
        headers = {"Content-Type": "application/json", "Referer": self.base + "/"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if method != "GET" and self.csrf:
            headers["X-CSRFToken"] = self.csrf
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        with self.opener.open(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}

    def login(self, username, password):
        r = self._call("POST", "/api/v1/security/login", {"username": username, "password": password, "provider": "db", "refresh": True}, auth=False)
        self.token = r["access_token"]
        self.csrf = self._call("GET", "/api/v1/security/csrf_token/")["result"]

    def get(self, path):
        return self._call("GET", path)

    def post(self, path, body):
        return self._call("POST", path, body)

    def put(self, path, body):
        return self._call("PUT", path, body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8088")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default=os.environ.get("SUPERSET_ADMIN_PASSWORD", ""))
    ap.add_argument("--database", default="CAM reports")
    ap.add_argument("--table", default="summary_report")
    args = ap.parse_args()
    if not args.password:
        raise SystemExit("give --password or set SUPERSET_ADMIN_PASSWORD")

    api = Api(args.url)
    api.login(args.username, args.password)

    dbs = api.get("/api/v1/database/?q=(page_size:100)")["result"]
    db_id = next(d["id"] for d in dbs if d["database_name"] == args.database)

    datasets = api.get("/api/v1/dataset/?q=(page_size:100)")["result"]
    ds = next((d for d in datasets if d["table_name"] == args.table), None)
    if ds is None:
        # a virtual dataset (a saved SQL query over the report table): DuckDB's table reflection is not compatible with this Superset release
        ds_id = api.post("/api/v1/dataset/", {"database": db_id, "table_name": args.table, "sql": f"SELECT * FROM {args.table}"})["id"]
    else:
        ds_id = ds["id"]

    chart_name = "Reports: summary by RFQ"
    charts = api.get("/api/v1/chart/?q=(page_size:100)")["result"]
    chart = next((c for c in charts if c["slice_name"] == chart_name), None)
    columns = ["rfq_id", "fg", "volume_no", "bom_qty", "inventory_stock", "ext_vol_conv_price", "volume_qty", "moq_cost", "pct_moq_of_cost"]
    params = {"viz_type": "table", "datasource": f"{ds_id}__table", "query_mode": "raw", "all_columns": columns, "row_limit": 1000, "adhoc_filters": []}
    if chart is None:
        chart_id = api.post("/api/v1/chart/", {"slice_name": chart_name, "viz_type": "table", "datasource_id": ds_id, "datasource_type": "table", "params": json.dumps(params)})["id"]
    else:
        chart_id = chart["id"]
        api.put(f"/api/v1/chart/{chart_id}", {"params": json.dumps(params)})

    dash_title = "CAM Reports & Analytics"
    dashboards = api.get("/api/v1/dashboard/?q=(page_size:100)")["result"]
    dash = next((d for d in dashboards if d["dashboard_title"] == dash_title), None)
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-1"], "parents": ["ROOT_ID"]},
        "ROW-1": {"type": "ROW", "id": "ROW-1", "children": ["CHART-1"], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        "CHART-1": {"type": "CHART", "id": "CHART-1", "children": [], "parents": ["ROOT_ID", "GRID_ID", "ROW-1"], "meta": {"width": 12, "height": 60, "chartId": chart_id, "sliceName": chart_name}},
    }
    if dash is None:
        dash_id = api.post("/api/v1/dashboard/", {"dashboard_title": dash_title, "slug": "cam-reports", "published": True, "position_json": json.dumps(position)})["id"]
    else:
        dash_id = dash["id"]

    # the chart must point at its dataset and at the dashboard, or the dashboard shows "no chart definition"
    api.put(f"/api/v1/chart/{chart_id}", {"datasource_id": ds_id, "datasource_type": "table", "dashboards": [dash_id]})
    api.put(f"/api/v1/dashboard/{dash_id}", {"position_json": json.dumps(position), "published": True})
    embed = api.put(f"/api/v1/dashboard/{dash_id}/embedded", {"allowed_domains": []})
    uuid = embed["result"]["uuid"]
    print(json.dumps({"dashboard_id": dash_id, "embed_uuid": uuid, "dataset_id": ds_id, "chart_id": chart_id, "database_id": db_id}))


if __name__ == "__main__":
    main()
