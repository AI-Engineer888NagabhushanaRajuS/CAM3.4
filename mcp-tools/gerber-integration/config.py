"""Gerber-integration settings for CAM 3.4. Paths come from the environment (see .env.example).

3.3 config.py imported shared.db_config (not in the baseline) and held the Bifrost gateway
constants. 3.4 routes tools directly and does not bring Bifrost back (SPEC-015).
"""
import os

# Same input database the reporting engine reads (REPORTING_INPUT_DB).
DB_PATH = os.environ.get("REPORTING_INPUT_DB", "/app/database/input_db.duckdb")
