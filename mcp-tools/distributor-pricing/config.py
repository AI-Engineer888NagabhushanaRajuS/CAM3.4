"""Distributor-pricing settings for CAM 3.4. Paths come from the environment (see .env.example).

The 3.3 config.py imported shared.db_config (not in the baseline) and held Bifrost constants.
3.4 routes tools directly and does not bring Bifrost back (SPEC-015). DB_PATH is the same
bom_storage.duckdb that intake writes (3.3 shared.db_config.DB_PATH); not run end to end in 3.4.
"""
import os

DB_PATH = os.environ.get("BOM_STORAGE_DB", "/app/database/bom_storage.duckdb")
