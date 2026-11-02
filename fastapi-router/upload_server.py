import asyncio
import threading
import os
import random
import json
import zipfile
import requests
from typing import Optional
from fastapi import Depends, FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2

import db
import auth
import rfq_memory_client

# FDE Staging Pipeline -- off by default; production's own process should
# never set this. See docs/MCP/... / the FDE plan for why this is one
# shared process with conditionally-registered routes rather than a
# second service: this repo runs upload_server.py as a single
# manage_backend.py SERVICES entry, and both feature sets are meant to be
# reachable during development from the same instance.
ENABLE_FDE_ROUTES = os.environ.get("ENABLE_FDE_ROUTES", "false").lower() == "true"

# CAM 3.4: Temporal is the default engine. Set CAM_USE_TEMPORAL=false only to
# fall back to Dify for shadow-run comparison during rollout.
USE_TEMPORAL = os.environ.get("CAM_USE_TEMPORAL", "true").lower() == "true"

app = FastAPI()

# No hardcoded fallback on purpose -- DIFY_API_KEY used to default to a real
# local-dev key, which is not safe to keep in source control. Set both env
# vars in your local .env before running this service.
# When USE_TEMPORAL=true these are unused but must still be set to avoid
# os.environ[] KeyError on import -- set to any placeholder in that case.
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost:3001")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "placeholder-not-used-when-temporal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.getcwd(), "staged", "inbox")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Was a second hardcoded copy of the same connection string as
# db.FILE_METADATA_DB_URL -- sourced from db.py's single canonical constant
# instead, so there is one place (not two) to override for deployment.
DB_CONFIG = db.FILE_METADATA_DB_URL

ALLOWED_FILE_TYPES = {
    "csv", "xls", "xlsx", "274x", "274-d", "x2", "x3",
    "pdf", "zip", "eml", "tiff", "jpeg", "jpg", "png",
    "bmp", "stp", "step", "dwg", "dxf"
}

# ── Helper Functions ───────────────────────────────────────────────────────────

def get_db_connection():
    return psycopg2.connect(DB_CONFIG)

# Triggers now run in worker threads (see start_dify_workflow); the schema check is check-then-ALTER.
_GUARD_SCHEMA_LOCK = threading.Lock()


def trigger_dify_workflow_internal(rfq_id: str):
    """Triggers workflow and logs the attempt to DB.

    When USE_TEMPORAL=true: starts a Temporal RFQWorkflow instead of Dify.
    When USE_TEMPORAL=false: calls Dify as before (the default is true; see CAM_USE_TEMPORAL).

    Guarded by db.try_start_pipeline_run() -- both callers of this function
    (a brand-new upload, and GET /api/dify/start/{rfq_id}'s HITL-resume
    trigger) funnel through here, so this is the single chokepoint that
    prevents 2 near-simultaneous triggers for the same (rfq_id, active
    version) from both starting a Dify/Temporal run at once. See that
    function's own docstring in db.py for the full reasoning and its stated
    limitations.
    """
    with _GUARD_SCHEMA_LOCK:
        db.ensure_processing_guard_schema()
    if not db.try_start_pipeline_run(rfq_id):
        print(f"[DIFY API SKIPPED]: {rfq_id} already has a pipeline run triggered recently -- rejecting duplicate trigger")
        return "ALREADY_PROCESSING", {
            "status": "REJECTED",
            "error": f"A pipeline run for rfq_id={rfq_id!r} was already triggered recently and is still considered in-flight. Try again shortly.",
        }

    dify_status = "TRIGGERED"
    dify_response_summary = {}

    if USE_TEMPORAL:
        # CAM 3.4: Temporal path — same idempotent ID as Dify's rfq_id key
        try:
            import sys as _sys
            import pathlib as _pathlib
            _worker_dir = str(_pathlib.Path(__file__).parent.parent / "temporal_worker")
            if _worker_dir not in _sys.path:
                _sys.path.insert(0, _worker_dir)
            import client as temporal_client
            workflow_id = asyncio.run(temporal_client.start_rfq_workflow(rfq_id))
            print(f"[TEMPORAL SUCCESS]: Workflow {workflow_id!r} started for {rfq_id}")
            dify_status = "TRIGGERED"
            dify_response_summary = {"status": "SUCCESS", "engine": "temporal", "workflow_id": workflow_id}
        except Exception as temporal_err:
            print(f"[TEMPORAL EXCEPTION]: {temporal_err}")
            dify_status = "CONNECTION_REFUSED"
            dify_response_summary = {"status": "NETWORK_ERROR", "error": str(temporal_err)}
    else:
        # Original Dify path (unchanged)
        dify_url = f"{DIFY_BASE_URL}/workflows/run"
        dify_headers = {
            "Authorization": f"Bearer {DIFY_API_KEY}",
            "Content-Type": "application/json"
        }
        dify_payload = {
            "inputs": {"rfq_id": rfq_id},
            "response_mode": "streaming",
            "user": f"system-user-{rfq_id}"
        }
        try:
            dify_response = requests.post(
                dify_url,
                headers=dify_headers,
                json=dify_payload,
                timeout=(10, 120)
            )
            if dify_response.ok:
                print(f"[DIFY API SUCCESS]: Workflow initiated for {rfq_id}")
                dify_response_summary = {"status": "SUCCESS", "code": dify_response.status_code}
            else:
                print(f"[DIFY API WARNING]: {dify_response.status_code} — {dify_response.text}")
                dify_status = "TRIGGER_FAILED"
                dify_response_summary = {"status": "REJECTED", "error": dify_response.text}
        except requests.exceptions.RequestException as req_err:
            print(f"[DIFY API EXCEPTION]: {req_err}")
            dify_status = "CONNECTION_REFUSED"
            dify_response_summary = {"status": "NETWORK_ERROR", "error": str(req_err)}

    # Append status log to PostgreSQL telemetry
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        dify_log_patch = json.dumps({
            "dify_trigger_status": dify_status,
            "dify_response": dify_response_summary
        })
        cursor.execute(
            """
            UPDATE rfq_file_telemetry
            SET execution_logs = execution_logs || %s::jsonb
            WHERE rfq_id = %s AND file_role = 'BOM' AND is_active = TRUE;
            """,
            (dify_log_patch, rfq_id)
        )
        conn.commit()
        cursor.close()
    except Exception as update_err:
        print(f"[METADATA LOG UPDATE ERROR]: {update_err}")
    finally:
        if conn:
            conn.close()

    return dify_status, dify_response_summary


async def process_file_upload(rfq_id: str, file_obj: UploadFile, file_label: str, version: int):
    """Handles file saving, extension check, and database telemetry insertion.

    version: which rfq_process_tracking version this file belongs to. Every
    insert here also deactivates any PRIOR active row for this exact
    (rfq_id, file_role) pair first -- previously missing, which meant a
    re-uploaded file of the same role never stopped being "active" alongside
    the new one, and scrub_mcp_server.py's _fetch_file_path() had no reliable
    way to pick the right one (confirmed non-deterministic against real data
    that already has 2-3 duplicate rows for several rfq_ids).
    """
    file_name = file_obj.filename or f"{file_label.lower()}_upload"
    file_extension = os.path.splitext(file_name)[1].replace(".", "").lower() or "unknown"

    if file_extension not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=415,
            detail={
                "message": f"Unsupported file type for {file_label}: .{file_extension}",
                "allowed_types": sorted(ALLOWED_FILE_TYPES)
            }
        )

    unique_id = random.randint(100000, 999999)
    saved_filename = f"{unique_id}_{file_label}_{file_name}"
    file_path = os.path.normpath(os.path.join(UPLOAD_DIR, saved_filename))

    with open(file_path, "wb") as buffer:
        buffer.write(await file_obj.read())

    telemetry_log = {
        "uploader_client": "React Canvas UI",
        "file_label": file_label,
        "original_name": file_name,
        "disk_transfer": "SUCCESS",
        "message": f"{file_label} file staged for RFQ {rfq_id}."
    }

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE rfq_file_telemetry
            SET is_active = FALSE
            WHERE rfq_id = %s AND file_role = %s;
            """,
            (rfq_id, file_label)
        )
        cursor.execute(
            """
            INSERT INTO rfq_file_telemetry
                (rfq_id, version, file_role, file_path, file_type, scan_status, execution_logs, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE);
            """,
            (
                rfq_id,
                version,
                file_label,
                file_path,
                file_extension,
                "PENDING",
                json.dumps(telemetry_log)
            )
        )
        conn.commit()
        cursor.close()
    finally:
        conn.close()

    # Best-effort Cognee ingestion trigger (RFQ chat memory feature) --
    # fire-and-forget, never allowed to affect this upload's own response.
    # `version` here is this function's own explicit parameter (the exact
    # version this file row was just inserted under), never inferred, per
    # plan §0.C.
    try:
        rfq_memory_client.queue_ingestion(
            rfq_id=rfq_id, version=version, source="file_upload",
            tool_result={"file_role": file_label, "file_path": file_path},
        )
    except Exception as e:
        print(f"[MEMORY INGEST ERROR] {e}")

    return file_path


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/dify/start/{rfq_id}")
async def start_dify_workflow(rfq_id: str, token: dict = Depends(auth.verify_token)):
    """GET endpoint to manually or externally trigger the Dify workflow for a given RFQ ID."""
    rfq_id = rfq_id.strip()
    if not rfq_id:
        raise HTTPException(status_code=400, detail="rfq_id cannot be empty.")

    # Off the event loop: the trigger calls asyncio.run() (Temporal) and blocks on requests (Dify).
    dify_status, response_summary = await asyncio.to_thread(trigger_dify_workflow_internal, rfq_id)

    return {
        "success": dify_status in ["TRIGGERED", "SUCCESS"],
        "rfq_id": rfq_id,
        "dify_status": dify_status,
        "dify_response": response_summary
    }


@app.post("/api/rfq/upload")
async def upload_rfq_file(
    bom_file: UploadFile = File(...),
    volume_file: UploadFile = File(...),
    # Optional -- gerber_integration__extract_features (RFQ_Flow's
    # routing_sequence) checks for an active GERBER_ZIP file_role row and
    # skips itself gracefully (hitl=0) when this wasn't provided, same
    # "optional third input" shape as costing_sheet/ERP elsewhere in this
    # platform.
    gerber_file: Optional[UploadFile] = File(None),
    rfq_id: str = Form(...),
    token: dict = Depends(auth.verify_token_form),
):
    conn = None
    try:
        if not rfq_id or not rfq_id.strip():
            raise HTTPException(
                status_code=400,
                detail="Missing form field: 'rfq_id' cannot be blank."
            )

        rfq_id = rfq_id.strip()
        db.ensure_version_schema()
        conn = get_db_connection()
        cursor = conn.cursor()

        # Serialize concurrent uploads for the SAME rfq_id (e.g. 2 users, or
        # a double-click) before doing anything else in this transaction.
        # Without this, 2 concurrent requests could both read the same
        # "current max version" below (a classic check-then-act race) and
        # both compute the same new_version, then race on the INSERT --
        # caught by the (rfq_id, version) primary key / the
        # idx_rfq_process_tracking_one_active partial unique index, but only
        # as an ugly unhandled 500 for whichever loses, not a clean
        # response. pg_advisory_xact_lock is keyed on a hash of rfq_id (works
        # even before any row exists for it, unlike SELECT ... FOR UPDATE)
        # and auto-releases at this transaction's own commit/rollback below
        # -- no separate unlock call needed, and no lock survives a crash.
        # A DIFFERENT rfq_id's upload is completely unaffected (the hash
        # only serializes requests sharing this exact rfq_id).
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", (rfq_id,))

        # A re-upload of a NEW BOM file to an rfq_id that already has an
        # active version creates an isolated new version rather than
        # overwriting -- the prior version's tracking row (and its DuckDB
        # data, keyed separately under its own versioned identifier
        # downstream) is left completely untouched.
        cursor.execute(
            "SELECT version FROM rfq_process_tracking WHERE rfq_id = %s AND is_active;",
            (rfq_id,)
        )
        existing_active = cursor.fetchone()

        process_stage = 0  # 0 = STAGED_INTAKE
        triggered_by = "UI_CANVAS_PORT_3000"

        if existing_active is None:
            new_version = 1
        else:
            cursor.execute(
                "SELECT COALESCE(MAX(version), 0) FROM rfq_process_tracking WHERE rfq_id = %s;",
                (rfq_id,)
            )
            new_version = cursor.fetchone()[0] + 1
            cursor.execute(
                "UPDATE rfq_process_tracking SET is_active = FALSE WHERE rfq_id = %s;",
                (rfq_id,)
            )

        cursor.execute(
            """
            INSERT INTO rfq_process_tracking
                (rfq_id, version, is_active, rfq_process_stage, hitl_required, triggered_by)
            VALUES (%s, %s, TRUE, %s, %s, %s);
            """,
            (rfq_id, new_version, process_stage, False, triggered_by)
        )
        conn.commit()
        cursor.close()

        # Save BOM and Volume files, both tagged with the new version.
        # Volume is mandatory here -- intake__import_bom (RFQ_Flow) requires
        # a file_role='VOLUME' row in rfq_file_telemetry to exist alongside
        # the BOM row before it can run; there is no graceful-skip for it.
        file_path = await process_file_upload(rfq_id, bom_file, "BOM", version=new_version)
        volume_path = await process_file_upload(rfq_id, volume_file, "VOLUME", version=new_version)

        saved_paths = {"BOM": file_path, "VOLUME": volume_path}
        if gerber_file is not None and gerber_file.filename:
            saved_paths["GERBER_ZIP"] = await process_file_upload(rfq_id, gerber_file, "GERBER_ZIP", version=new_version)

        # Trigger Dify workflow
        # Off the event loop: see start_dify_workflow.
        dify_status, _ = await asyncio.to_thread(trigger_dify_workflow_internal, rfq_id)

        return {
            "success": True,
            "rfq_id": rfq_id,
            "version": new_version,
            "saved_paths": saved_paths,
            "telemetry": {
                "rfq_process_stage": "0 (STAGED_INTAKE)",
                "dify_pipeline_status": dify_status
            }
        }

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[CRITICAL ERROR]: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@app.post("/api/rfq/upload/quotewin")
async def upload_quotewin_file(
    quotewin_file: UploadFile = File(...),
    rfq_id: str = Form(...),
    token: dict = Depends(auth.verify_token_form),
):
    """Endpoint to upload QuoteWin files for an RFQ.

    This is a follow-up upload completing the SAME intake session the BOM
    upload already started (not a new version by itself) -- it always
    resolves and tags the file with whatever version is CURRENTLY active,
    never mints a new one.
    """
    if not rfq_id or not rfq_id.strip():
        raise HTTPException(status_code=400, detail="Missing form field: 'rfq_id' cannot be blank.")

    rfq_id = rfq_id.strip()
    try:
        active_version = db.get_active_version(rfq_id)
        file_path = await process_file_upload(rfq_id, quotewin_file, "QUOTEWIN", version=active_version)
        return {
            "success": True,
            "rfq_id": rfq_id,
            "version": active_version,
            "saved_paths": {"QUOTEWIN": file_path}
        }
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rfq/upload/costing_sheet")
async def upload_costing_sheet_file(
    costing_sheet_file: UploadFile = File(...),
    rfq_id: str = Form(...),
    token: dict = Depends(auth.verify_token_form),
):
    """Endpoint to upload Costing Sheet files for an RFQ.

    Replaces the earlier ERP upload endpoint -- ERP is not exposed in the
    current product (its MCP tool/schema/routing stay in the codebase for
    future use, see scrub_mcp_server.py/erp_to_database.py), and Costing
    Sheet has taken its place as the optional third input, same
    graceful-skip treatment ERP previously had.

    Like QuoteWin above, this always resolves and tags the file with
    whatever version is CURRENTLY active -- never mints a new one.
    """
    if not rfq_id or not rfq_id.strip():
        raise HTTPException(status_code=400, detail="Missing form field: 'rfq_id' cannot be blank.")

    rfq_id = rfq_id.strip()
    try:
        active_version = db.get_active_version(rfq_id)
        file_path = await process_file_upload(rfq_id, costing_sheet_file, "COSTING_SHEET", version=active_version)
        return {
            "success": True,
            "rfq_id": rfq_id,
            "version": active_version,
            "saved_paths": {"COSTING_SHEET": file_path}
        }
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── FDE Staging Pipeline (ENABLE_FDE_ROUTES only) ──────────────────────────────
#
# Completely separate database (staging_file_metadata_db_2, via
# db.get_staging_metadata_connection()) and disk tree (FDE_UPLOAD_DIR, sibling
# to but never mixed with UPLOAD_DIR above) from every RFQ endpoint in this
# file -- no code path here can reach production data or vice versa. Auth
# reuses auth.py's same JWT scheme/secret, scoped to a project_id claim
# (see auth.verify_token_project/verify_token_any_project) rather than a
# second auth system.

if ENABLE_FDE_ROUTES:
    FDE_UPLOAD_DIR = os.path.join(os.getcwd(), "staged", "staging_inbox", "fde")
    os.makedirs(FDE_UPLOAD_DIR, exist_ok=True)

    class FdeProjectCreateRequest(BaseModel):
        project_name: str
        description: Optional[str] = None

    def _fde_project_dir(project_id: str) -> str:
        d = os.path.join(FDE_UPLOAD_DIR, project_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _fde_insert_file_row(cursor, project_id: str, original_filename: str,
                              file_extension: str, extracted_from_file_id: Optional[int] = None) -> int:
        """Inserts a placeholder fde_project_files row (stored_file_path set
        after the real file_id is known -- needed to build the on-disk
        filename), returns the new file_id."""
        cursor.execute(
            """
            INSERT INTO fde_project_files
                (project_id, original_filename, stored_file_path, file_extension,
                 file_size_bytes, extracted_from_file_id)
            VALUES (%s, %s, '', %s, 0, %s)
            RETURNING file_id;
            """,
            (project_id, original_filename, file_extension, extracted_from_file_id),
        )
        return cursor.fetchone()[0]

    @app.post("/api/fde/projects")
    def create_fde_project(
        body: FdeProjectCreateRequest,
        token: dict = Depends(auth.verify_token_any_project),
    ):
        """Creates a new FDE project -- the sole project-creation surface
        (the frontend's gear-icon Settings dialog is the only caller)."""
        db.ensure_fde_schema()
        project_name = body.project_name.strip()
        if not project_name:
            raise HTTPException(status_code=400, detail="project_name cannot be blank.")

        project_id = db.mint_fde_project_id()
        with db.get_staging_metadata_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO fde_projects (project_id, project_name, description)
                    VALUES (%s, %s, %s)
                    RETURNING project_id, project_name, description, created_at;
                    """,
                    (project_id, project_name, body.description),
                )
                row = cursor.fetchone()
            conn.commit()

        return {
            "project_id": row[0],
            "project_name": row[1],
            "description": row[2],
            "created_at": row[3].isoformat(),
        }

    @app.get("/api/fde/projects")
    def list_fde_projects(token: dict = Depends(auth.verify_token_any_project)):
        """Lists every FDE project -- backs FDEProjectPicker's "select an
        existing project" list."""
        db.ensure_fde_schema()
        with db.get_staging_metadata_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT project_id, project_name, description, created_at
                    FROM fde_projects
                    ORDER BY created_at DESC;
                    """
                )
                rows = cursor.fetchall()
        return [
            {
                "project_id": r[0],
                "project_name": r[1],
                "description": r[2],
                "created_at": r[3].isoformat(),
            }
            for r in rows
        ]

    @app.post("/api/fde/projects/{project_id}/upload")
    async def upload_fde_project_file(
        project_id: str,
        file: UploadFile = File(...),
        token: dict = Depends(auth.verify_token_project),
    ):
        """Single-file-per-call upload (matches Uppy's per-file XHR
        transport -- the Dashboard drives N calls to this same endpoint, one
        per file, rather than a batch). Auto-extracts .zip uploads
        server-side into sibling fde_project_files rows, each pointing back
        at the zip's own file_id via extracted_from_file_id -- "any file
        type, no fixed schema" per the FDE spec, so there is no allowlist
        check here (unlike ALLOWED_FILE_TYPES above, which is RFQ-specific
        and intentionally untouched)."""
        db.ensure_fde_schema()

        with db.get_staging_metadata_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM fde_projects WHERE project_id = %s", (project_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"FDE project '{project_id}' not found.")
            conn.commit()

        original_name = file.filename or "upload"
        file_extension = os.path.splitext(original_name)[1].replace(".", "").lower() or "unknown"
        contents = await file.read()

        project_dir = _fde_project_dir(project_id)
        saved = []

        with db.get_staging_metadata_connection() as conn:
            with conn.cursor() as cursor:
                file_id = _fde_insert_file_row(cursor, project_id, original_name, file_extension)
                stored_path = os.path.normpath(os.path.join(project_dir, f"{file_id}_{original_name}"))
                with open(stored_path, "wb") as f:
                    f.write(contents)
                cursor.execute(
                    "UPDATE fde_project_files SET stored_file_path = %s, file_size_bytes = %s WHERE file_id = %s",
                    (stored_path, len(contents), file_id),
                )
                saved.append({"file_id": file_id, "original_filename": original_name, "stored_file_path": stored_path})

                if file_extension == "zip":
                    try:
                        with zipfile.ZipFile(stored_path) as zf:
                            for member in zf.namelist():
                                if member.endswith("/"):
                                    continue  # directory entry, not a real file
                                member_bytes = zf.read(member)
                                member_name = os.path.basename(member) or member
                                member_ext = os.path.splitext(member_name)[1].replace(".", "").lower() or "unknown"
                                member_file_id = _fde_insert_file_row(
                                    cursor, project_id, member_name, member_ext,
                                    extracted_from_file_id=file_id,
                                )
                                member_path = os.path.normpath(os.path.join(project_dir, f"{member_file_id}_{member_name}"))
                                with open(member_path, "wb") as mf:
                                    mf.write(member_bytes)
                                cursor.execute(
                                    "UPDATE fde_project_files SET stored_file_path = %s, file_size_bytes = %s WHERE file_id = %s",
                                    (member_path, len(member_bytes), member_file_id),
                                )
                                saved.append({
                                    "file_id": member_file_id,
                                    "original_filename": member_name,
                                    "stored_file_path": member_path,
                                    "extracted_from_file_id": file_id,
                                })
                    except zipfile.BadZipFile:
                        print(f"[FDE UPLOAD WARNING] '{original_name}' has a .zip extension but is not a valid zip -- kept as a single opaque file.")
            conn.commit()

        return {"success": True, "project_id": project_id, "saved": saved}

    @app.get("/api/fde/projects/{project_id}/files")
    def list_fde_project_files(project_id: str, token: dict = Depends(auth.verify_token_project)):
        """Backs the persistent "already uploaded" file list in
        FDEUploadDocsPanel."""
        db.ensure_fde_schema()
        with db.get_staging_metadata_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT file_id, original_filename, file_extension, file_size_bytes,
                           uploaded_at, extracted_from_file_id, scan_status
                    FROM fde_project_files
                    WHERE project_id = %s
                    ORDER BY uploaded_at DESC;
                    """,
                    (project_id,),
                )
                rows = cursor.fetchall()
        return [
            {
                "file_id": r[0],
                "original_filename": r[1],
                "file_extension": r[2],
                "file_size_bytes": r[3],
                "uploaded_at": r[4].isoformat(),
                "extracted_from_file_id": r[5],
                "scan_status": r[6],
            }
            for r in rows
        ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3100)