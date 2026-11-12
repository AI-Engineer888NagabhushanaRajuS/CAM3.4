"""The Feasibility & Risk rules an admin saved in Settings > Feasibility (Postgres logic_db.feasibility_settings, written by the daemon's
feasibility.save). Read on EVERY run, never cached: a saved change counts from the next RFQ.

load() -> (settings or None, source). source is "settings" when a row was saved, "defaults" when nobody saved anything yet (the run then uses the
documented defaults in reports/feasibility_risk.py and says so, so nobody mistakes them for the plant's own rules).
"""
import os
import sys

_PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "fastapi-router")
if _PROJECT_DIR not in sys.path:
    sys.path.append(_PROJECT_DIR)  # append: this folder's own config.py must win the name lookup

from db import get_logic_connection  # noqa: E402


def load():
    with get_logic_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('feasibility_settings')")
            if cur.fetchone()[0] is None:          # the daemon creates the table the first time Settings is saved
                return None, "defaults"
            cur.execute("SELECT settings FROM feasibility_settings WHERE id = 1")
            row = cur.fetchone()
            return (row[0], "settings") if row and row[0] else (None, "defaults")   # an empty row = nothing saved yet
