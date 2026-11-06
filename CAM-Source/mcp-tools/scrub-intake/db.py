"""
db.py

Database helper functions for RFQ execution tracking.

[BuLLMQuote-SRIM MIGRATION NOTE] Copied from CAM's root db.py as part of
migrating scrub_mcp_server into this repo (containerization Phase 2). CAM's
original hardcoded a fallback default pointing at `logic_db`/`file_metadata_db`
-- CAM's OWN databases. Left as-is, this copy would silently write into CAM's
live data instead of Centum's own `logic_db_2`/`file_metadata_db_2`. Fixed by
requiring the env var explicitly (raises if unset) instead of falling back to
the wrong database -- matching the exact pattern fastmcp-router/db.py already
uses elsewhere in this repo for the same reason.

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

import psycopg2
from psycopg2.extras import RealDictCursor

LOGIC_DB_URL = os.environ["LOGIC_DB_URL"]
FILE_METADATA_DB_URL = os.environ["FILE_METADATA_DB_URL"]


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


def ensure_user_tracking_schema():
    """
    Idempotent migration: adds a `"user"` column to rfq_file_telemetry,
    recording which accomplish-ui account (the session `uid`/short name --
    see session.ts's `getSession().user.name`) uploaded each file, i.e. who
    ran that RFQ execution. Same call pattern/idiom as ensure_version_schema()
    above -- cheap information_schema check when already migrated, safe to
    call on every upload request.

    Nullable, no default: existing rows (uploaded before this column existed)
    get NULL rather than a fabricated value, and any future caller that
    genuinely doesn't have a logged-in user available (e.g. a script driving
    the API directly) also gets an honest NULL instead of a guessed value.

    `user` is a reserved word in Postgres (the CURRENT_USER shorthand), so
    every reference to this column -- here and in every INSERT/SELECT
    elsewhere -- must be double-quoted as "user".
    """

    with get_metadata_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'rfq_file_telemetry' AND column_name = 'user'
                """
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    'ALTER TABLE rfq_file_telemetry ADD COLUMN "user" VARCHAR'
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
