from pathlib import Path

# ---------------------------------------------------------------------------
# Database
#
# The single shared constant both intake/ and distributor_pricing/ need
# identically — both FastMCP servers are separate processes pointed at the
# same physical DuckDB file.
# ---------------------------------------------------------------------------
DB_PATH = Path(r"C:\SRIM-DB-SETUP\Databases\bom_storage.duckdb")
