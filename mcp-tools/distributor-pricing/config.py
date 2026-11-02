"""Distributor-pricing settings for CAM 3.4. Paths come from the environment (see .env.example).

The 3.3 config.py imported shared.db_config (not in the baseline) and held Bifrost constants.
3.4 routes tools directly and does not bring Bifrost back (SPEC-015). DB_PATH defaults to the
reporting input database; which tables this tool writes there is UNVERIFIED (see SPEC-015).
"""
import os

DB_PATH = os.environ.get("REPORTING_INPUT_DB", "/app/database/input_db.duckdb")
