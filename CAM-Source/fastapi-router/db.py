"""
db.py

Database helper functions for RFQ execution tracking.

Tables used
-----------
rfq_process_tracking
    rfq_process_stage -> current skill index

system_skills_registry
    skill_index
    mcp_tool_name
    skill_name
    macro_category
    macro_category_name
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Loads fastmcp-router/.env (gitignored, see .gitignore's existing .env/.env.*
# patterns) if present -- same python-dotenv convention already used by
# mcp-tools/rfq-memory/config.py and mcp-tools/distributor-pricing/mcp_server.py
# for their own secrets. Silently does nothing if the file doesn't exist, so
# this stays a no-op wherever LOGIC_DB_URL/FILE_METADATA_DB_URL are already
# set some other way (e.g. a real deployment's own process env).
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent / ".env")

# Single canonical source for these two connection strings -- every other
# module that needs them (upload_server.py, manage_backend.py's service env
# blocks) should import LOGIC_DB_URL/FILE_METADATA_DB_URL from here rather
# than re-declaring their own copy, so there is exactly one place a Hetzner
# deployment needs to override via env var instead of several independently
# hardcoded strings.
#
# No hardcoded fallback on purpose -- this used to default to a local-dev
# Postgres credential, which is not safe to keep in source control. Set both
# env vars in your local .env before running any service that imports this
# module.
LOGIC_DB_URL = os.environ["LOGIC_DB_URL"]
FILE_METADATA_DB_URL = os.environ["FILE_METADATA_DB_URL"]

# FDE Staging Pipeline's own, fully isolated pair -- separate databases,
# separate dedicated role (fde_staging_app, scoped via GRANTs to only these
# 2 databases, never the shared postgres superuser), on the same Postgres
# instance as the production pair above. Soft-optional (os.environ.get, not
# os.environ[...]) unlike LOGIC_DB_URL/FILE_METADATA_DB_URL -- a process that
# never sets ENABLE_FDE_ROUTES=true has no reason to require these; the
# staging-specific connection helpers below raise a clear error at first
# real use instead, not at import time.
STAGING_LOGIC_DB_URL = os.environ.get("STAGING_LOGIC_DB_URL")
STAGING_FILE_METADATA_DB_URL = os.environ.get("STAGING_FILE_METADATA_DB_URL")


@contextmanager
def get_logic_connection():
    """
    Connection to logic_db.
    Used for system_skills_registry.
    """

    conn = psycopg2.connect(LOGIC_DB_URL)

    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_metadata_connection():
    """
    Connection to file_metadata_db.
    Used for rfq_process_tracking.
    """

    conn = psycopg2.connect(FILE_METADATA_DB_URL)

    try:
        yield conn
    finally:
        conn.close()

# ==========================================================
# RFQ VERSION SCHEMA MIGRATION (idempotent -- see
# reporting_module/final_selection.py's ensure_conflicts_table() for the same
# idiom on a different table). Adds real per-version tracking to
# rfq_process_tracking/rfq_file_telemetry (file_metadata_db), which previously
# had exactly one row per rfq_id and no way to isolate multiple versions'
# execution state from one another.
# ==========================================================

def ensure_version_schema():
    """
    Idempotent migration: adds `version`/`is_active` to rfq_process_tracking
    and `version` to rfq_file_telemetry, re-points rfq_file_telemetry's FK at
    the new composite (rfq_id, version) key, and enforces "at most one active
    version per rfq_id" via a partial unique index. Safe to call on every
    request (cheap information_schema check when already migrated) -- same
    call pattern as ensure_conflicts_table().

    All 9 existing rfq_process_tracking rows / 20 existing rfq_file_telemetry
    rows get version=1, is_active=true automatically via the column defaults,
    so this is safe to run against live data with no manual backfill.
    """

    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'rfq_process_tracking' AND column_name = 'version'
                """
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    "ALTER TABLE rfq_process_tracking ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                )
                cursor.execute(
                    "ALTER TABLE rfq_process_tracking ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true"
                )
                cursor.execute(
                    "ALTER TABLE rfq_file_telemetry DROP CONSTRAINT IF EXISTS rfq_file_telemetry_rfq_id_fkey"
                )
                cursor.execute(
                    "ALTER TABLE rfq_process_tracking DROP CONSTRAINT rfq_process_tracking_pkey"
                )
                cursor.execute(
                    "ALTER TABLE rfq_process_tracking ADD CONSTRAINT rfq_process_tracking_pkey PRIMARY KEY (rfq_id, version)"
                )

            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'rfq_file_telemetry' AND column_name = 'version'
                """
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    "ALTER TABLE rfq_file_telemetry ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                )
                cursor.execute(
                    """
                    ALTER TABLE rfq_file_telemetry
                    ADD CONSTRAINT rfq_file_telemetry_rfq_id_version_fkey
                    FOREIGN KEY (rfq_id, version) REFERENCES rfq_process_tracking(rfq_id, version)
                    ON DELETE CASCADE
                    """
                )

            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_rfq_process_tracking_one_active
                ON rfq_process_tracking (rfq_id) WHERE is_active
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rfq_file_telemetry_rfq_version
                ON rfq_file_telemetry(rfq_id, version)
                """
            )
        conn.commit()


def ensure_step_events_schema():
    """What each pipeline step really did, kept so the left pane and the timeline can say it after a reload.
    One row per status change of one skill of one RFQ version; the stage index alone cannot tell "ran" from "skipped"."""
    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS rfq_step_events (
                    id BIGSERIAL PRIMARY KEY,
                    rfq_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    skill_code TEXT NOT NULL,
                    skill_name TEXT,
                    macro_category INTEGER,
                    step_status TEXT NOT NULL,
                    detail TEXT,
                    warning BOOLEAN NOT NULL DEFAULT FALSE,
                    at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rfq_step_events_rfq ON rfq_step_events (rfq_id, version, id)")
        conn.commit()


def record_step_event(rfq_id, skill_code, skill_name, macro_category, step_status, detail=None, warning=False):
    """Best effort: a failure to record must never fail the tool call. Version is the RFQ's active one."""
    ensure_step_events_schema()
    try:
        version = get_active_version(rfq_id)
    except Exception:
        version = 1
    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO rfq_step_events (rfq_id, version, skill_code, skill_name, macro_category, step_status, detail, warning) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (rfq_id, version, skill_code, skill_name, macro_category, step_status, detail, bool(warning)),
            )
        conn.commit()


def ensure_processing_guard_schema():
    """
    Idempotent migration (same pattern as ensure_version_schema() above):
    adds `last_triggered_at` to rfq_process_tracking. Backs
    try_start_pipeline_run()'s same-RFQ concurrency guard below -- safe to
    call on every request (cheap information_schema check once migrated).
    """
    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'rfq_process_tracking' AND column_name = 'last_triggered_at'
                """
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    "ALTER TABLE rfq_process_tracking ADD COLUMN last_triggered_at TIMESTAMP NULL"
                )
        conn.commit()


def try_start_pipeline_run(rfq_id: str, stale_after_seconds: int = 1800) -> bool:
    """
    Guards against 2 near-simultaneous Dify-workflow triggers for the SAME
    (rfq_id, active version) racing each other -- e.g. 2 users both hitting
    "resume" on a HITL-paused RFQ around the same time, or a double-click.
    The pipeline itself is a sequential per-RFQ state machine (rfq_process_stage
    advances one skill at a time); 2 truly concurrent Dify runs against the
    same version risk a skill executing twice or rfq_process_stage advancing
    inconsistently -- see MULTI_USER_PRODUCTION_READINESS.md's Q1 for the
    full reasoning.

    Design note / honest limitation: this is a TIME-based heuristic, not a
    hard lock released on completion -- there is no "Dify workflow finished"
    signal that reaches this codebase (only per-STEP /tool/execute calls),
    so there's no clean event to release a real lock on. `stale_after_seconds`
    (default 30 minutes, comfortably longer than the realistic worst case --
    8 skills x up to 300s each -- but not a guarantee) is how long a trigger
    is considered "still in flight" before a new trigger is allowed through
    again. This deliberately favors self-healing (a crashed/abandoned run
    doesn't permanently block that RFQ) over perfect mutual exclusion.

    Returns True if the caller should proceed with triggering Dify (and this
    call has already recorded `last_triggered_at = now()` for that version),
    False if a trigger for this exact (rfq_id, active version) was already
    recorded within `stale_after_seconds` and the caller should reject this
    attempt with a clear "already processing" response instead.
    """
    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:
            # Serializes concurrent callers for the SAME rfq_id the same way
            # upload_server.py's version-increment fix does -- so 2 requests
            # racing to check-then-set last_triggered_at can't both observe
            # "not recently triggered" and both proceed.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", (rfq_id,))
            cursor.execute(
                """
                SELECT last_triggered_at FROM rfq_process_tracking
                WHERE rfq_id = %s AND is_active
                """,
                (rfq_id,)
            )
            row = cursor.fetchone()
            if row is not None and row[0] is not None:
                cursor.execute(
                    "SELECT EXTRACT(EPOCH FROM (now() - %s))",
                    (row[0],)
                )
                age_seconds = cursor.fetchone()[0]
                if age_seconds is not None and age_seconds < stale_after_seconds:
                    conn.commit()  # releases the advisory lock; nothing else to persist
                    return False

            cursor.execute(
                """
                UPDATE rfq_process_tracking SET last_triggered_at = now()
                WHERE rfq_id = %s AND is_active
                """,
                (rfq_id,)
            )
        conn.commit()
    return True


@contextmanager
def duckdb_file_lock(key: str = "reporting_group"):
    """
    Cross-process serialization for DuckDB access to reports.duckdb/cbom.duckdb/
    input_db.duckdb.

    DuckDB's embedded engine does not queue concurrent access to the same
    database file across SEPARATE OS PROCESSES the way it does for concurrent
    connections within one process (that case is genuinely MVCC-safe) -- a
    second process opening a file another process already holds gets an
    immediate IOException, not a wait. This codebase runs each pipeline stage
    as its own process (reporting_mcp_server, python_bridge, hitl_router,
    scrub_mcp_server, bom_qa_lookup_server), several of which open the same
    physical .duckdb files, so this lock makes them take turns instead of
    racing.

    Deliberately ONE key for reports.duckdb + cbom.duckdb + input_db.duckdb
    together, not a separate key per file: reporting_module/database.py's own
    connect() always opens/attaches all three in a single call (input_db
    read-only, the other two read-write), so every caller that goes through it
    already needs exclusivity across all three simultaneously -- splitting the
    lock per-file would not enable any real parallelism (every connect()-based
    caller would still need to hold both keys at once) while adding a lock-
    ordering deadlock risk if different call sites ever acquired 2 keys in a
    different order. `key` exists as a parameter (rather than hardcoding this
    one domain) only so a future genuinely-independent DuckDB file group could
    use its own key without touching this function.

    Session-scoped (pg_advisory_lock/pg_advisory_unlock), not the `_xact_`
    variant used elsewhere in this module -- this must span the full
    open-DuckDB-connection -> use -> close lifetime, which is not itself a
    single Postgres transaction. Uses its own dedicated Postgres connection
    (held only for the lock's own lifetime) and explicitly unlocks in
    `finally`, so a crash inside the `with` block still releases it.
    """
    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtext(%s));", (key,))
        conn.commit()
        try:
            yield
        finally:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtext(%s));", (key,))
            conn.commit()


def get_active_version(rfq_id: str) -> int:
    """
    Resolves which version is currently active for rfq_id. Raises if rfq_id
    has no active version row at all (mirrors get_current_skill_index's
    existing error style).
    """

    with get_metadata_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT version FROM rfq_process_tracking WHERE rfq_id = %s AND is_active",
                (rfq_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise Exception(f"RFQ '{rfq_id}' has no active version.")
            return row["version"]


def versioned_key(rfq_id: str, version: int) -> str:
    """
    The internal DuckDB/final_selection_conflicts scoping key for one
    specific version of an rfq_id -- e.g. "RFQ-1001__v2". Postgres
    (rfq_process_tracking/rfq_file_telemetry) always keys on the bare
    canonical rfq_id + a separate version column; this synthetic string is
    only used where DuckDB tables (which have no version column at all) need
    isolation between versions purely via their existing rfq_id-scoping.

    version=1 maps to the BARE rfq_id, unchanged -- every RFQ that existed
    before this versioning feature shipped has its DuckDB/
    final_selection_conflicts rows stored under the plain rfq_id with no
    suffix at all, and the schema migration gives every pre-existing
    rfq_process_tracking row version=1. Suffixing version 1 too would silently
    orphan all of that real data (a version-1 lookup would resolve to a key
    like "RFQ-1001__v1" that has never actually been written). Only version 2+
    -- which by construction can only ever be created going forward, after
    this feature exists -- gets a real suffix, giving it its own fresh,
    never-before-used identity with no backward-compatibility burden.
    """
    if version <= 1:
        return rfq_id
    return f"{rfq_id}__v{version}"


# ==========================================================
# ROUTING PROFILES
# ==========================================================

def get_routing_sequence(profile_name: str = "Standard_BOM_Flow") -> list:
    """
    Returns the LIVE routing_sequence array (list of mcp_tool_name strings)
    for a routing profile, freshly queried every call -- no caching, since a
    Skills Settings toggle must take effect on the very next /tool/execute
    call, not on some cached snapshot.
    """

    with get_logic_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = %s LIMIT 1",
                (profile_name,),
            )
            row = cursor.fetchone()
            if row is None:
                raise Exception(f"Routing profile '{profile_name}' not found")
            return row["routing_sequence"]


def get_all_live_tool_names() -> list:
    """Union of every routing_sequence across every profile in
    quote_routing_profiles, freshly queried every call (same no-caching
    contract as get_routing_sequence). fastapi_router.py's /tool/execute
    "ROUTING GATE" uses this instead of one hardcoded profile_name so a tool
    that belongs to ANY live profile (Standard_BOM_Flow, RFQ_Flow, or any
    future one) is correctly treated as enabled -- a single-profile check
    here previously meant every profile except whichever one was hardcoded
    got every one of its tools silently skipped.
    """
    with get_logic_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT tool FROM quote_routing_profiles, "
                "jsonb_array_elements_text(routing_sequence) AS tool"
            )
            return [row[0] for row in cursor.fetchall()]


# ==========================================================
# RFQ PROCESS TRACKING
# ==========================================================

def get_current_skill_index(rfq_id: str) -> int:
    """
    Returns the current skill index stored in
    rfq_process_tracking.rfq_process_stage, for the ACTIVE version only.
    """

    with get_metadata_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:

            cursor.execute(
                """
                SELECT rfq_process_stage
                FROM rfq_process_tracking
                WHERE rfq_id = %s AND is_active
                """,
                (rfq_id,),
            )

            row = cursor.fetchone()

            if row is None:
                raise Exception(
                    f"RFQ '{rfq_id}' does not exist."
                )

            return row["rfq_process_stage"]


def increment_skill_index(rfq_id: str) -> int:
    """
    Increments rfq_process_stage for the ACTIVE version only -- without the
    `AND is_active` filter, this would advance every version's row at once,
    silently breaking per-version execution-state isolation the moment a
    second version exists for an rfq_id.

    Returns the updated skill index.
    """

    with get_metadata_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:

            cursor.execute(
                """
                UPDATE rfq_process_tracking
                SET rfq_process_stage = rfq_process_stage + 1, updated_at = CURRENT_TIMESTAMP
                WHERE rfq_id = %s AND is_active
                RETURNING rfq_process_stage;
                """,
                (rfq_id,),
            )

            row = cursor.fetchone()

            conn.commit()

            if row is None:
                raise Exception(
                    f"Unable to update RFQ '{rfq_id}'."
                )

            return row["rfq_process_stage"]


def advance_skill_index_to_at_least(rfq_id: str, min_index: int) -> int:
    """
    Sets rfq_process_stage to max(current, min_index) for the ACTIVE version --
    idempotent and never regresses, unlike increment_skill_index()'s blind +1.

    Needed by hitl_router.py's resolve_final_selection confirm: that skill's own
    hitl gate (reporting_module/final_selection.py's resolve_final_selection())
    always returns hitl=1, even with zero conflicts, so it never advances
    rfq_process_stage past its own position in the routing sequence -- a single
    +1 from the human-approval confirm only reaches THAT position (still
    pointing at resolve_final_selection itself, not past it), which the Dify
    workflow's own "is this RFQ still HITL-pending" check then reads as
    "still not approved," aborting every resume attempt with a
    "HITL pending" exception (confirmed via Dify's /v1/workflows/logs API:
    total_steps=4, aborted before ever calling back into this project).
    Calling this with min_index = (resolve_final_selection's index in the
    live routing_sequence) + 1 moves the stage unambiguously past the gate in
    one call, regardless of how many increments were "owed" -- and is safe to
    call more than once (e.g. a retried request) since it only ever moves
    forward.

    Returns the resulting (new-or-unchanged) skill index.
    """

    with get_metadata_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:

            cursor.execute(
                """
                UPDATE rfq_process_tracking
                SET rfq_process_stage = GREATEST(rfq_process_stage, %s), updated_at = CURRENT_TIMESTAMP
                WHERE rfq_id = %s AND is_active
                RETURNING rfq_process_stage;
                """,
                (min_index, rfq_id),
            )

            row = cursor.fetchone()

            conn.commit()

            if row is None:
                raise Exception(
                    f"Unable to update RFQ '{rfq_id}'."
                )

            return row["rfq_process_stage"]


def set_skill_index(
    rfq_id: str,
    skill_index: int,
):
    """
    Explicitly sets the current skill index for the ACTIVE version only.
    """

    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE rfq_process_tracking
                SET rfq_process_stage = %s, updated_at = CURRENT_TIMESTAMP
                WHERE rfq_id = %s AND is_active;
                """,
                (
                    skill_index,
                    rfq_id,
                ),
            )

            conn.commit()


def set_hitl_required(rfq_id: str, value: bool) -> None:
    """
    Marks whether the ACTIVE version is currently paused awaiting a human
    action (uploading QuoteWin/Costing Sheet, or resolving final-selection
    conflicts) -- set True whenever a tool response carries a truthy "hitl"
    flag, cleared as soon as any subsequent skill successfully advances.
    Lets callers (e.g. upload_server.py's /api/dify/start resume trigger)
    tell, from Postgres alone, whether a paused RFQ is specifically at the
    post-scrub_bom checkpoint (rfq_process_stage == 0 and hitl_required)
    without needing to inspect the last tool response's raw JSON.

    Setting value=True also clears last_triggered_at (try_start_pipeline_run's
    own dedup timestamp) back to NULL -- a HITL pause means the previous Dify
    run has definitively stopped and is waiting on a human, so there is no
    "still in flight" run left to protect against. Without this, a real bug
    reproduces: the ORIGINAL trigger (e.g. the BOM upload) sets
    last_triggered_at, and a human can easily take longer than a few seconds
    (but well under try_start_pipeline_run's 30-minute staleness window) to
    prepare and upload QuoteWin -- the resulting legitimate resume trigger
    then gets wrongly rejected as "already processing" even though nothing
    has been running since the pause began. Clearing it here makes a resume
    trigger behave exactly like a never-triggered RFQ (immediately allowed),
    while still protecting against 2 near-simultaneous resume clicks: the
    first one's try_start_pipeline_run call sets last_triggered_at = now(),
    so a second click microseconds later correctly sees a fresh timestamp and
    is rejected -- see that function's own docstring for the rest of this
    reasoning.
    """

    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE rfq_process_tracking
                SET hitl_required = %s,
                    updated_at = CURRENT_TIMESTAMP,
                    last_triggered_at = CASE WHEN %s THEN NULL ELSE last_triggered_at END
                WHERE rfq_id = %s AND is_active;
                """,
                (value, value, rfq_id),
            )

            conn.commit()


def get_hitl_state(rfq_id: str):
    """
    Returns (rfq_process_stage, hitl_required) for the ACTIVE version, or
    None if there is no active tracking row at all.
    """

    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT rfq_process_stage, hitl_required
                FROM rfq_process_tracking
                WHERE rfq_id = %s AND is_active;
                """,
                (rfq_id,),
            )

            row = cursor.fetchone()
            return tuple(row) if row else None


# ==========================================================
# SYSTEM SKILLS REGISTRY
# ==========================================================

def get_skill_by_index(skill_index: int):
    """
    Returns the skill metadata corresponding
    to a skill index.
    """

    with get_logic_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:

            cursor.execute(
                """
                SELECT

                    skill_index,
                    mcp_tool_name,
                    skill_name,
                    macro_category,
                    macro_category_name

                FROM system_skills_registry

                WHERE skill_index = %s

                LIMIT 1;
                """,
                (skill_index,),
            )

            row = cursor.fetchone()

            if row is None:
                raise Exception(
                    f"No skill found for skill_index={skill_index}"
                )

            return {
                "skillIndex": row["skill_index"],
                "skillCode": row["mcp_tool_name"],
                "skillName": row["skill_name"],
                "macroCategory": row["macro_category"],
                "macroCategoryName": row["macro_category_name"],
            }


def get_skill_by_code(mcp_tool_name: str):
    """
    Returns metadata for a mcp_tool_name.

    Useful when execute_tool() already knows
    which MCP tool was executed.
    """

    with get_logic_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:

            cursor.execute(
                """
                SELECT

                    skill_index,
                    mcp_tool_name,
                    skill_name,
                    macro_category,
                    macro_category_name

                FROM system_skills_registry

                WHERE mcp_tool_name = %s

                LIMIT 1;
                """,
                (mcp_tool_name,),
            )

            row = cursor.fetchone()

            if row is None:
                raise Exception(
                    f"No skill found for mcp_tool_name='{mcp_tool_name}'"
                )

            return {
                "skillIndex": row["skill_index"],
                "skillCode": row["mcp_tool_name"],
                "skillName": row["skill_name"],
                "macroCategory": row["macro_category"],
                "macroCategoryName": row["macro_category_name"],
            }


# ==========================================================
# EXECUTION HELPERS
# ==========================================================

def advance_execution(rfq_id: str):
    """
    Advances the workflow to the next skill.

    Returns the metadata for the new skill.
    """

    new_skill_index = increment_skill_index(rfq_id)

    return get_skill_by_index(new_skill_index)


def get_current_execution(rfq_id: str):
    """
    Returns the current skill metadata
    without modifying execution state.
    """

    skill_index = get_current_skill_index(rfq_id)

    return get_skill_by_index(skill_index)


# ==========================================================
# FDE STAGING PIPELINE (fde_projects / fde_project_files) --
# staging_file_metadata_db_2 only, fully isolated from every table above.
# See docs/Database/logic-database.md's Multi-project isolation guidance --
# this is that guidance applied for real, not just documented.
# ==========================================================

@contextmanager
def get_staging_metadata_connection():
    """Connection to staging_file_metadata_db_2 (fde_projects/fde_project_files)
    -- the FDE Staging Pipeline's own isolated database. Deliberately a
    SEPARATE helper from get_metadata_connection() (production's
    file_metadata_db_2) -- no code path can reach production data through
    this connection, or vice versa, since they're different databases
    behind a different, narrowly-GRANTed Postgres role."""
    if not STAGING_FILE_METADATA_DB_URL:
        raise RuntimeError(
            "STAGING_FILE_METADATA_DB_URL is not set -- required when ENABLE_FDE_ROUTES=true."
        )
    conn = psycopg2.connect(STAGING_FILE_METADATA_DB_URL)
    try:
        yield conn
    finally:
        conn.close()


def ensure_fde_schema():
    """Idempotent migration (same pattern as ensure_version_schema() above):
    creates fde_project_id_seq / fde_projects / fde_project_files in
    staging_file_metadata_db_2 if they don't already exist. Safe to call on
    every request (cheap information_schema check once migrated)."""
    with get_staging_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'fde_projects'"
            )
            if cursor.fetchone() is None:
                cursor.execute("CREATE SEQUENCE IF NOT EXISTS fde_project_id_seq")
                cursor.execute(
                    """
                    CREATE TABLE fde_projects (
                        project_id   TEXT PRIMARY KEY,
                        project_name TEXT NOT NULL,
                        description  TEXT NULL,
                        created_by   TEXT NULL,
                        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE fde_project_files (
                        file_id                 BIGSERIAL PRIMARY KEY,
                        project_id              TEXT NOT NULL REFERENCES fde_projects(project_id) ON DELETE CASCADE,
                        original_filename       TEXT NOT NULL,
                        stored_file_path        TEXT NOT NULL,
                        file_extension           TEXT NOT NULL,
                        file_size_bytes          BIGINT NOT NULL,
                        created_by               TEXT NULL,
                        uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
                        extracted_from_file_id   BIGINT NULL REFERENCES fde_project_files(file_id) ON DELETE SET NULL,
                        scan_status               TEXT NOT NULL DEFAULT 'PENDING'
                    )
                    """
                )
        conn.commit()


def mint_fde_project_id() -> str:
    """FDE-PROJ-000006-style ID, via fde_project_id_seq -- mirrors this
    codebase's existing sequence-backed, zero-padded ID-minting convention."""
    with get_staging_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT nextval('fde_project_id_seq')")
            n = cursor.fetchone()[0]
        conn.commit()
    return f"FDE-PROJ-{n:06d}"


def fde_cognee_session_id(project_id: str) -> str:
    """Deterministic Cognee session_id for a project -- no DB column needed,
    every future Stage 2+ tool recomputes this identically. Not called by
    anything yet (Stage 1 has no Cognee dependency); exists now purely so
    no future stage invents a second, divergent convention."""
    return project_id


def fde_cognee_dataset_name(project_id: str) -> str:
    """Deterministic Cognee dataset_name for a project -- see
    fde_cognee_session_id()'s own docstring. Not called by anything yet."""
    return f"upload_{project_id}"
