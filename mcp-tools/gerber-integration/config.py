"""Gerber-integration settings for CAM 3.4. Paths come from the environment (see .env.example).

3.3 config.py imported shared.db_config (not in the baseline) and held the Bifrost gateway
constants. 3.4 routes tools directly and does not bring Bifrost back (SPEC-015).
"""
import os

# 3.3 shared.db_config.DB_PATH: the bom_storage.duckdb intake writes (gerber_geometry/gerber_checklist
# live there too). Not run end to end in 3.4.
DB_PATH = os.environ.get("BOM_STORAGE_DB", "/app/database/bom_storage.duckdb")
