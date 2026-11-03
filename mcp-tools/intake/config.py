"""Intake settings for CAM 3.4. Paths and URLs come from the environment (see .env.example).

3.3 config.py imported shared.db_config (not in the repo) and held the Bifrost gateway
constants. 3.4 routes tools directly and does not bring Bifrost back (SPEC-015), so neither is
carried over.
"""
import os

# 3.3: shared.db_config.DB_PATH, one bom_storage.duckdb used by intake, distributor-pricing and
# gerber-integration (not the reporting engine's input_db.duckdb, which has no processed_bom_items).
DB_PATH = os.environ.get("BOM_STORAGE_DB", "/app/database/bom_storage.duckdb")
