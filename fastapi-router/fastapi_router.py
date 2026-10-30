import json
import os
import pathlib
import re
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
import ast
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import httpx
from datetime import datetime


# Import your native core functions directly from your script
from tool_calling import call_tool
from db import (
    increment_skill_index,
    get_skill_by_code,
    get_active_version,
    versioned_key,
    set_hitl_required,
    get_all_live_tool_names,
)
import rfq_memory_client


def _load_tool_routing_sets():
    """Load DUCKDB_SCOPED_TOOLS and SCRUB_TOOLS from ISATVON manifests.

    Falls back to hardcoded sets if manifests/ is missing (e.g., during early
    bootstrap before SPEC-003 manifests are present).
    """
    manifests_dir = pathlib.Path(__file__).parent.parent / "manifests"
    if not manifests_dir.is_dir():
        # Fallback: hardcoded sets (pre-manifest bootstrap)
        return (
            {
                "centum_reporting__cbom",
                "centum_reporting__enrich_erp",
                "centum_reporting__enrich_costing_sheet",
                "centum_reporting__resolve_final_selection",
                "centum_reporting__generate_reports",
                "centum_reporting__export_reports",
            },
            {
                "centum_intake__standardize_scrub_bom",
                "centum_intake__standardize_quote_win",
                "centum_intake__standardize_erp",
                "centum_intake__standardize_costing_sheet",
            },
        )

    duckdb_tools = set()
    scrub_tools = set()
    for mf in manifests_dir.glob("*.json"):
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # duckdb_scoped_tools: explicit list in manifest (not all tools in the module)
        for tool_name in manifest.get("duckdb_scoped_tools", []):
            duckdb_tools.add(tool_name)
        # scrub_tools: explicit list in manifest
        for tool_name in manifest.get("scrub_tools", []):
            scrub_tools.add(tool_name)

    return duckdb_tools, scrub_tools


# The reporting_module MCP tools -- these touch cbom.duckdb/reports.duckdb
# directly and take a single opaque "rfq_id" string argument. Gets rewritten
# to the versioned key before dispatch. Loaded from manifests/ at startup.
# The 4 scrub_mcp_server.py intake tools -- these need the BARE rfq_id plus
# an explicit numeric "version" argument; they build their own versioned key
# internally right before touching DuckDB. Also loaded from manifests/.
DUCKDB_SCOPED_TOOLS, SCRUB_TOOLS = _load_tool_routing_sets()


class ToolExecuteRequest(BaseModel):
    # Make root rfq_id optional so it accepts nested arguments payloads smoothly
    rfq_id: Optional[Any] = None  
    tool_name: str
    arguments: Dict[str, Any]

app = FastAPI(
    title="Upstream to Postgres MCP Bridge Router",
    version="1.0.0"
)

# Routing-sequence lookups below build their SQL as a raw string forwarded to
# the postgres-mcp tool (see call_tool in tool_calling.py), which takes only a
# "sql" string with no parameter-binding support -- so untrusted path
# parameters must be validated against an allow-list before interpolation
# rather than bound as query parameters. Real rfq_id/profile_name values only
# ever contain letters, digits, underscores, and hyphens (e.g.
# "RFQ-PRICE-TEST-001", "Standard_BOM_Flow").
_SAFE_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_sql_identifier(value: str, field_name: str) -> str:
    if not value or not _SAFE_SQL_IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid {field_name}: must contain only letters, digits, underscores, and hyphens"
        )
    return value

def notify_skill_progress(rfq_id, skill_code, skill_name, macro_category, macro_category_name, step_status, error=None):
    payload = {
        "rfqId": rfq_id,
        "skillCode": skill_code,
        "skillName": skill_name,
        "macroCategory": macro_category,
        "macroCategoryName": macro_category_name,
        "stepStatus": step_status,
        "updatedAt": datetime.utcnow().isoformat() + "Z",
    }
    if error is not None:
        payload["error"] = error
    httpx.post(
    "http://100.121.36.255:9334/api/internal/emit-skill-progress",
    json=payload,
    timeout=5,
    )

def _notify_execute_failure(rfq_id, tool_name, error_message):
    """Best-effort UI notification for any /tool/execute failure path -- a
    failed tool call previously left the frontend showing "[RUNNING]"
    forever (the last thing it heard was the "running" notification before
    the call), with no indication anything went wrong. A lookup/notify
    failure here must never mask the real error being reported to the caller.
    """
    try:
        skill = get_skill_by_code(tool_name)
        notify_skill_progress(
            rfq_id=rfq_id,
            skill_code=skill["skillCode"],
            skill_name=skill["skillName"],
            macro_category=skill["macroCategory"],
            macro_category_name=skill["macroCategoryName"],
            step_status="failed",
            error=error_message,
        )
    except Exception as e:
        print(f"[SSE ERROR] (failed notification) {e}")


@app.get("/pipeline/routing-sequence/{rfq_id}/{profile_name}")
def get_routing_sequence(rfq_id: str, profile_name: str):
    try:
        rfq_id = _validate_sql_identifier(rfq_id, "rfq_id")
        profile_name = _validate_sql_identifier(profile_name, "profile_name")
    except ValueError as e:
        return {"error": str(e)}

    # Points at BuLLMQuote's own logic_db_2/file_metadata_db_2 -- registered
    # in Bifrost as the Production_Logic_DB/Production_FileMetedata_DB MCP
    # clients (replacing MCP Jungle's postgres_logic_2/postgres_metadata_2),
    # each backed by `postgres-mcp` with
    # DATABASE_URI=...@host.docker.internal:5432/... The un-suffixed
    # originals (postgres_logic/postgres_metadata) still point at CAM's
    # shared logic_db/file_metadata_db; do not repoint those.
    LOGIC_TOOL = "Production_Logic_DB-execute_sql"
    METADATA_TOOL = "Production_FileMetedata_DB-execute_sql"

    try:
        # Get routing sequence from logic_db
        routing_result = call_tool(
            tool_name=LOGIC_TOOL,
            arguments={
                "sql": f"""
                    SELECT routing_sequence
                    FROM quote_routing_profiles
                    WHERE profile_name = '{profile_name}';
                """
            }
        )

        if "result" not in routing_result:
            # The gateway/MCP server can reject the call outright (e.g. a dead
            # transport to the backing postgres-mcp server) instead of ever
            # producing a "result" -- indexing straight into ["result"] then
            # raises an opaque KeyError that hides the real reason. Surfacing
            # the actual JSON-RPC error here is what the caller (Dify) and
            # whoever's debugging a stuck RFQ actually needs to see.
            raise RuntimeError(f"{LOGIC_TOOL} call failed: {routing_result.get('error', routing_result)}")

        routing_text = routing_result["result"]["content"][0]["text"]
        routing_rows = ast.literal_eval(routing_text)

        if not routing_rows:
            return {
                "error": f"Profile '{profile_name}' not found"
            }

        routing_sequence = routing_rows[0]["routing_sequence"]

        # Get current stage from file_metadata_db
        stage_result = call_tool(
            tool_name=METADATA_TOOL,
            arguments={
                "sql": f"""
                    SELECT rfq_process_stage
                    FROM rfq_process_tracking
                    WHERE rfq_id = '{rfq_id}';
                """
            }
        )

        if "result" not in stage_result:
            raise RuntimeError(f"{METADATA_TOOL} call failed: {stage_result.get('error', stage_result)}")

        stage_text = stage_result["result"]["content"][0]["text"]
        stage_rows = ast.literal_eval(stage_text)

        if not stage_rows:
            return {
                "error": f"RFQ '{rfq_id}' not found"
            }

        skill_index = stage_rows[0]["rfq_process_stage"]

        return {
            "routing_sequence": routing_sequence,
            "skill_index": skill_index
        }

    except Exception as e:
        print(f"[ERROR] Failed: {e}")
        return {
            "error": str(e)
        }

@app.post("/tool/execute")
def execute_tool(request: ToolExecuteRequest):
    # Deliberately a plain `def`, not `async def`: this function calls
    # tool_calling.call_tool(), which does a BLOCKING requests.post() (up to
    # a 300s timeout for slow LLM-backed tools) with no await/asyncio
    # anywhere in the call chain. An `async def` route that calls blocking
    # I/O directly monopolizes Uvicorn's single event-loop thread for the
    # full duration of that call -- since this service runs as a single
    # worker (see `uvicorn.run(...)` below, no `workers=`), that meant ONE
    # user's tool call froze this entire service for every other
    # concurrent user/RFQ. A plain `def` route is automatically dispatched
    # to FastAPI/Starlette's thread pool, so concurrent calls no longer
    # block each other. No other code in this function needs `await`.
    # Extract rfq_id safely from arguments dictionary if missing at root level
    effective_rfq_id = request.rfq_id
    if effective_rfq_id is None:
        effective_rfq_id = request.arguments.get("rfq_id", "UNKNOWN_RFQ")

    print(f"RFQ ID Detected: {effective_rfq_id}")
    print(f"Tool Payload Name: {request.tool_name}")
    print(f"Forwarded Arguments: {request.arguments}")

    #
    # -------------------------------------------------------------
    # Routing-profile gate: skip disabled tools entirely
    # -------------------------------------------------------------
    #
    # Queried FRESH on every call (no caching) -- a Skills Settings toggle
    # must take effect on the very next /tool/execute call. Runs BEFORE the
    # version-resolution below (a skipped tool never needs a versioned key)
    # and before the actual Bifrost call_tool() below (a skipped tool never
    # needs to reach the gateway at all).
    #
    try:
        # Union of every profile's routing_sequence, not one hardcoded
        # profile_name -- Dify's /tool/execute payload carries no
        # profile_name at all (see the DMR's HTTP Request 2 node), so this
        # gate has no way to know which specific profile this rfq_id is
        # running under. Checking against a single hardcoded profile meant
        # every tool belonging to any OTHER profile (e.g. RFQ_Flow) was
        # unconditionally treated as disabled and silently skipped, no
        # matter what routing-sequence lookup preceded it.
        live_tool_names = get_all_live_tool_names()
    except Exception as e:
        # Fail OPEN, not closed: if the routing-profile lookup itself breaks,
        # the pipeline must not silently stall every RFQ -- log loudly and
        # fall through to normal execution rather than treating a lookup
        # failure as "disabled".
        print(f"[ROUTING GATE ERROR] Could not load routing_sequence, failing open: {e}")
        live_tool_names = None

    if live_tool_names is not None and request.tool_name not in live_tool_names:
        try:
            skill = get_skill_by_code(request.tool_name)
            skill_code, skill_name = skill["skillCode"], skill["skillName"]
            macro_category, macro_category_name = skill["macroCategory"], skill["macroCategoryName"]
        except Exception:
            skill_code, skill_name = request.tool_name, request.tool_name
            macro_category, macro_category_name = None, None

        print(
            f"[ROUTING GATE] Skipping disabled tool '{request.tool_name}' for "
            f"RFQ={effective_rfq_id} -- not present in any quote_routing_profiles.routing_sequence"
        )

        try:
            increment_skill_index(effective_rfq_id)
        except Exception as e:
            print(f"[ROUTING GATE ERROR] increment_skill_index failed while skipping: {e}")

        try:
            set_hitl_required(effective_rfq_id, False)
        except Exception as e:
            print(f"[HITL STATE ERROR] Could not clear hitl_required while skipping: {e}")

        try:
            if macro_category is not None:
                notify_skill_progress(
                    rfq_id=effective_rfq_id,
                    skill_code=skill_code,
                    skill_name=skill_name,
                    macro_category=macro_category,
                    macro_category_name=macro_category_name,
                    step_status="completed",
                )
        except Exception as e:
            print(f"[SSE ERROR] (skip notification) {e}")

        return JSONResponse(
            status_code=200,
            content={"skipped": True, "hitl": 0, "tool_name": request.tool_name},
        )

    #
    # -------------------------------------------------------------
    # Version resolution: rewrite arguments to the active version's
    # DuckDB-scoped identity -- only reached by tools that will actually run.
    # -------------------------------------------------------------
    #
    try:
        active_version = get_active_version(effective_rfq_id)
        if request.tool_name in DUCKDB_SCOPED_TOOLS:
            request.arguments["rfq_id"] = versioned_key(effective_rfq_id, active_version)
        elif request.tool_name in SCRUB_TOOLS:
            request.arguments["rfq_id"] = effective_rfq_id
            request.arguments["version"] = active_version
    except Exception as e:
        # Same fail-open philosophy as the routing gate above: an inability
        # to resolve the active version must not silently stall the RFQ --
        # log loudly and fall through with arguments untouched (bare rfq_id),
        # matching pre-versioning behavior.
        print(f"[VERSION RESOLUTION ERROR] Could not resolve active version for {effective_rfq_id}: {e}")

    # Notify "running" BEFORE the tool call, not just "completed" after --
    # without this, the progress log goes silent for however long the skill
    # actually takes (LLM-backed tools can run over a minute) with no signal
    # that anything is happening at all. Best-effort: a lookup/notify failure
    # here must never block the real tool call below.
    try:
        starting_skill = get_skill_by_code(request.tool_name)
        notify_skill_progress(
            rfq_id=effective_rfq_id,
            skill_code=starting_skill["skillCode"],
            skill_name=starting_skill["skillName"],
            macro_category=starting_skill["macroCategory"],
            macro_category_name=starting_skill["macroCategoryName"],
            step_status="running",
        )
    except Exception as e:
        print(f"[SSE ERROR] (running notification) {e}")

    try:
    # 1. Capture the raw response from the Bifrost MCP gateway
        mcp_envelope = call_tool(
        tool_name=request.tool_name,
        arguments=request.arguments
    )
    
        try:
        # 2. Extract the string text from the standard MCP structure
            raw_text_content = mcp_envelope["result"]["content"][0]["text"]

        # 3. Parse it back into a native dict object
            try:
                print(f"RAW TEXT CONTENT{raw_text_content}")
                clean_json_body = json.loads(raw_text_content)

                #
                # -------------------------------------------------------------
                # Advance workflow
                # -------------------------------------------------------------
                #
                # A tool signaling hitl (truthy) means a human review gate was
                # reached (e.g. resolve_final_selection finding multi-source
                # conflicts) -- the RFQ must NOT advance past this skill until
                # that review completes (see hitl_router.py), or the pipeline
                # would silently skip the human checkpoint. "skipped" tool
                # results (e.g. no Costing Sheet uploaded) are a different,
                # non-hitl signal and DO advance normally.
                #
                # BUG FIXED: a tool reporting status="failed" (e.g.
                # standardize_quote_win with no QuoteWin file ever uploaded,
                # or standardize_scrub_bom re-run hitting a duplicate-data
                # error on a resumed RFQ still sitting at its pre-QuoteWin
                # HITL checkpoint) also has no "hitl" key, so hitl_flag alone
                # was False here too -- indistinguishable from a genuine
                # success/skip, silently advancing rfq_process_stage past a
                # real failure and letting the whole rest of the pipeline
                # (including later, unrelated steps) run against incomplete
                # data. A failed tool call must halt advancement exactly like
                # an explicit hitl gate, not fall through as if it succeeded.
                #
                hitl_flag = bool(clean_json_body.get("hitl"))
                tool_failed = clean_json_body.get("status") == "failed"

                if not hitl_flag and not tool_failed:

                    try:
                        # Any successful (non-hitl) advance means this RFQ is
                        # no longer paused awaiting a human action -- clear the
                        # flag so a later resume-trigger doesn't mistake this
                        # step for the still-pending post-scrub_bom checkpoint.
                        set_hitl_required(effective_rfq_id, False)
                    except Exception as e:
                        print(f"[HITL STATE ERROR] Could not clear hitl_required: {e}")

                    try:

                        #
                        # Increment rfq_process_stage
                        #
                        #
                        # -------------------------------------------------------------
                        # Lookup the completed skill
                        # -------------------------------------------------------------
                        #

                        skill = get_skill_by_code(request.tool_name)

                        #
                        # Advance workflow
                        #
                        increment_skill_index(effective_rfq_id)

                        #
                        # Best-effort Cognee ingestion trigger (RFQ chat
                        # memory feature) -- fire-and-forget, never allowed
                        # to affect this response. `active_version` may be
                        # unset if the earlier version-resolution block
                        # (above) itself failed and fell through; skip
                        # triggering rather than guess a version, per plan
                        # §0.C's "never inferred, always explicit" rule.
                        #
                        try:
                            if "active_version" in locals():
                                rfq_memory_client.queue_ingestion(
                                    rfq_id=effective_rfq_id,
                                    version=active_version,
                                    source=request.tool_name,
                                    tool_result=clean_json_body,
                                )
                        except Exception as e:
                            print(f"[MEMORY INGEST ERROR] {e}")

                        #
                        # Publish SSE event
                        #
                        # await sse_manager.publish_skill_progress(

                        #     rfq_id=effective_rfq_id,

                        #     skill_code=skill["skillCode"],

                        #     skill_name=skill["skillName"],

                        #     macro_category=skill["macroCategory"],

                        #     macro_category_name=skill["macroCategoryName"],

                        #     step_status="completed",

                        # )

                        notify_skill_progress(rfq_id=effective_rfq_id,skill_code=skill["skillCode"], skill_name=skill["skillName"], macro_category=skill["macroCategory"],  macro_category_name=skill["macroCategoryName"], step_status="completed")

                        print(
                            f"[SSE] Published progress "
                            f"RFQ={effective_rfq_id} "
                            f"Skill={skill['skillCode']}"
                        )

                    except Exception as e:

                        #
                        # SSE failures must never fail the tool execution.
                        #
                        print(f"[SSE ERROR] {e}")

                else:

                    try:
                        # Records the checkpoint so a later resume-trigger
                        # (upload_server.py's /api/dify/start) can tell, from
                        # Postgres alone, that this RFQ is specifically
                        # paused (vs. simply not-yet-started).
                        set_hitl_required(effective_rfq_id, True)
                    except Exception as e:
                        print(f"[HITL STATE ERROR] Could not set hitl_required: {e}")

                    if tool_failed and not hitl_flag:
                        error_detail = clean_json_body.get("error")
                        print(
                            f"[TOOL FAILED] rfq_process_stage NOT advanced for "
                            f"RFQ={effective_rfq_id} tool={request.tool_name} -- "
                            f"tool reported status=failed: {error_detail}"
                        )
                        # Surface the failure to the UI -- previously only a
                        # "running" notification was ever sent for this skill,
                        # so a failed tool call left the frontend showing
                        # "[RUNNING]" forever with no indication anything went
                        # wrong (the exact "looks stuck" symptom this was
                        # investigating). No completed/next-stage notification
                        # follows a failure, so App.tsx must not advance the
                        # wizard stage on a "failed" stepStatus.
                        _notify_execute_failure(
                            effective_rfq_id, request.tool_name,
                            str(error_detail) if error_detail is not None else "Unknown error",
                        )
                    else:
                        print(
                            f"[HITL] rfq_process_stage NOT advanced for "
                            f"RFQ={effective_rfq_id} tool={request.tool_name} -- "
                            f"awaiting human review"
                        )
                        # This skill's own execution genuinely finished (it's
                        # the PIPELINE that's paused pending human review, not
                        # this tool call) -- without a "completed" notification
                        # here, the right-pane progress log had no way to ever
                        # transition this entry out of "running", even after
                        # the next skill (once resumed) sent its own "running"
                        # event and visibly took over as the active stage.
                        try:
                            notify_skill_progress(
                                rfq_id=effective_rfq_id,
                                skill_code=starting_skill["skillCode"],
                                skill_name=starting_skill["skillName"],
                                macro_category=starting_skill["macroCategory"],
                                macro_category_name=starting_skill["macroCategoryName"],
                                step_status="completed",
                            )
                        except Exception as e:
                            print(f"[SSE ERROR] (hitl completed notification) {e}")

                #
                # Return original tool response
                #
                return JSONResponse(
                    status_code=200,
                    content=clean_json_body,
                )

            except Exception as e:
                print(f"JSON EXTRACTION FAIL {str(e)}")
                _notify_execute_failure(effective_rfq_id, request.tool_name, f"Tool returned non-JSON content: {str(e)}")

                return JSONResponse(
                    status_code=500,
                    content={"hitl": 1, "error": f"Tool returned non-JSON content: {str(e)}", "raw": raw_text_content}
                )


        except Exception as e:
            print(f"Extraction exception encountered: {e}")
            _notify_execute_failure(effective_rfq_id, request.tool_name, f"Bridge Extraction Failure: {str(e)}")
            return JSONResponse(
            status_code=500,
            content={"hitl": 1, "error": f"Bridge Extraction Failure: {str(e)}", "raw": mcp_envelope}
        )
    except Exception as e:
        # Previously fell through with no return -- FastAPI then sends back an
        # empty/null body, which the caller (Dify) can't distinguish from a
        # real result, and rfq_process_stage is left un-advanced with no
        # visible error (e.g. a slow LLM-backed tool call timing out through
        # MCP Jungle). Same {"hitl": 1, "error": ...} convention already used
        # by the two except blocks above, for the same reason: something
        # needs a human's attention before this RFQ can proceed.
        print(f"Exception {str(e)}")
        _notify_execute_failure(effective_rfq_id, request.tool_name, f"Tool call failed: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"hitl": 1, "error": f"Tool call failed: {str(e)}"}
        )

_USE_TEMPORAL = os.environ.get("CAM_USE_TEMPORAL", "false").lower() == "true"
_OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.1:8b")

_RFQ_GUARD = (
    "You are a read-only RFQ assistant for Centum Electronics. "
    "You CANNOT trigger RFQ runs, approve HITL gates, or change any data. "
    "If asked to perform an action, respond: "
    "'I can only read data. Please use the main RFQ interface to make changes.' "
    "Answer only from the RFQ context supplied below.\n\n"
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


def _build_rfq_context(rfq_id: str) -> dict:
    """Pull summary facts from DuckDB for the chat system prompt."""
    import sys as _sys
    _reporting_dir = str(pathlib.Path(__file__).parent.parent / "mcp-tools" / "reporting" / "superset")
    if _reporting_dir not in _sys.path:
        _sys.path.insert(0, _reporting_dir)

    ctx: dict = {}
    try:
        import database as _db
        con = _db.connect()
        try:
            row = con.execute(
                "SELECT * FROM summary_report WHERE rfq_id = ? LIMIT 1", [rfq_id]
            ).fetchdf()
            if not row.empty:
                ctx["summary"] = row.to_dict(orient="records")[0]
            miss = con.execute(
                "SELECT COUNT(*) FROM missing_notes_report WHERE rfq_id = ?", [rfq_id]
            ).fetchone()
            ctx["missing_parts_count"] = miss[0] if miss else 0
            aclass = con.execute(
                "SELECT COUNT(*) FROM aclass_parts_report WHERE rfq_id = ?", [rfq_id]
            ).fetchone()
            ctx["aclass_parts_count"] = aclass[0] if aclass else 0
        finally:
            con.close()
    except Exception as e:
        ctx["db_error"] = str(e)
    return ctx


@app.post("/rfq/{rfq_id}/chat")
async def rfq_chat(rfq_id: str, request: ChatRequest):
    """Read-only RFQ assistant — answers questions from DuckDB data via Ollama.

    Cannot trigger actions, approve HITL, or modify any data.
    """
    try:
        rfq_id = _validate_sql_identifier(rfq_id, "rfq_id")
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    ctx = _build_rfq_context(rfq_id)
    system_prompt = (
        _RFQ_GUARD
        + f"RFQ ID: {rfq_id}\n"
        + f"Context data:\n{json.dumps(ctx, indent=2, default=str)}"
    )

    payload = {
        "model": _OLLAMA_MODEL,
        "system": system_prompt,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{_OLLAMA_BASE}/api/chat", json=payload, timeout=60.0
            )
            resp.raise_for_status()
            answer = resp.json()["message"]["content"]
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"error": f"LLM unavailable: {e}", "message": "Service temporarily unavailable."},
        )

    return {"rfq_id": rfq_id, "message": answer, "sources": list(ctx.keys())}


@app.get("/rfq/{rfq_id}/status")
def get_rfq_status(rfq_id: str):
    """Unified RFQ status: Postgres stage + Temporal workflow status + HITL flag."""
    import asyncio as _asyncio

    try:
        rfq_id = _validate_sql_identifier(rfq_id, "rfq_id")
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    try:
        stage = get_active_version(rfq_id)
    except Exception as e:
        stage = None
        print(f"[STATUS] get_active_version failed: {e}")

    temporal_status = None
    if _USE_TEMPORAL:
        import pathlib as _pathlib
        import sys as _sys
        _sys.path.insert(0, str(_pathlib.Path(__file__).parent.parent / "temporal_worker"))
        try:
            import client as _tc
            temporal_status = _asyncio.run(_tc.get_workflow_status(rfq_id))
        except Exception as e:
            temporal_status = {"error": str(e)}

    # Check for pending HITL from Postgres
    hitl_required = False
    try:
        from db import check_hitl_required  # noqa: F401 — only available in 3.4+ db.py
        hitl_required = check_hitl_required(rfq_id)
    except (ImportError, Exception):
        pass  # check_hitl_required not available in all versions — skip silently

    return {
        "rfq_id": rfq_id,
        "postgres_stage": stage,
        "temporal": temporal_status,
        "hitl_required": hitl_required,
        "engine": "temporal" if _USE_TEMPORAL else "dify",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5100)