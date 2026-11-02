"""Intake settings for CAM 3.4. Paths and URLs come from the environment (see .env.example).

3.3 config.py imported shared.db_config (not in the repo) and held the Bifrost gateway
constants. 3.4 routes tools directly and does not bring Bifrost back (SPEC-015), so neither is
carried over.
"""
import os

# Same file the reporting engine reads as its input database (REPORTING_INPUT_DB).
DB_PATH = os.environ.get("REPORTING_INPUT_DB", "/app/database/input_db.duckdb")
