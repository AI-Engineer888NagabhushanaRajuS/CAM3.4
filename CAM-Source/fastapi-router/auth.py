"""Shared per-request JWT auth for duck_db_api.py, upload_server.py, and
hitl_router.py -- the 3 backend services the web frontend/daemon call
directly (fastapi_router.py is deliberately excluded: its 2 endpoints are
called by Dify's own workflow, which can't be updated from this repo to mint
or attach a token).

Every protected request must carry `Authorization: Bearer <jwt>` whose
payload's `rfq_id` matches this specific request's own rfq_id (path param or
form field), and whose `iat`/`exp` are both present with `exp == iat + 60`.
The frontend/daemon fetch a fresh token from `POST /auth/token` (served by
duck_db_api.py) immediately before each real call -- see accomplish-ui's
`apps/web/src/client/lib/apiAuth.ts`.

JWT_SECRET MUST be identical across all 3 services' processes (and set via
the same env var in production) -- a token minted with one value will fail
verification anywhere it's imported with a different value. Same
env-var-with-dev-fallback pattern as config.py's MCP_JUNGLE_URL and db.py's
DB URLs.
"""

import os
import time
from pathlib import Path

import jwt
from fastapi import Form, Header, HTTPException

# Loads fastmcp-router/.env directly -- deliberately NOT relying on some
# other module (e.g. db.py) having already called load_dotenv() first.
# duck_db_api.py and hitl_router.py both `import auth` BEFORE `from db
# import (...)`, so the transitive "db.py's own load_dotenv() call happens
# to run first" trick that worked for upload_server.py (which imports db
# before auth) silently did NOT apply here -- confirmed by upload_server.py
# actually crashing on a fresh restart with KeyError: 'JWT_SECRET' despite
# .env already containing LOGIC_DB_URL/FILE_METADATA_DB_URL correctly.
# Making this file load its own .env removes the dependency on import order
# in whichever service happens to import it.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parent / ".env")

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 60


def create_token(subject_id: str, claim_name: str = "rfq_id") -> str:
    """Mints a token scoped to exactly one subject (an rfq_id by default, or
    any other claim_name -- e.g. "project_id" for the FDE Staging Pipeline,
    which reuses this exact JWT scheme/secret rather than a second auth
    system), valid for TOKEN_TTL_SECONDS from the moment of issuance -- exp
    is always iat + 60, never a fixed wall-clock value, so it's correct
    regardless of when it's later verified. Every existing caller's
    positional `create_token(rfq_id)` keeps working unchanged -- claim_name
    defaults to "rfq_id".
    """
    now = int(time.time())
    payload = {claim_name: subject_id, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    return authorization[len("Bearer "):]


def _decode_and_check(token: str, subject_id: str | None, claim_name: str = "rfq_id") -> dict:
    """subject_id=None skips the claim-match check entirely (still enforces
    signature/iat/exp) -- used by verify_token_any_project below, where
    there is no subject yet to compare against (creating/listing projects
    happens before any project_id exists)."""
    try:
        # jwt.decode itself enforces exp (raises ExpiredSignatureError past
        # it); iat is checked explicitly below since PyJWT doesn't validate
        # it against wall-clock time on its own.
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    if "iat" not in payload or "exp" not in payload:
        raise HTTPException(status_code=401, detail="Token missing iat/exp")
    if payload["exp"] != payload["iat"] + TOKEN_TTL_SECONDS:
        raise HTTPException(status_code=401, detail="Token exp is not iat + 60s")
    if subject_id is not None and payload.get(claim_name) != subject_id:
        raise HTTPException(status_code=401, detail=f"Token {claim_name} does not match request {claim_name}")
    return payload


def verify_token(rfq_id: str, authorization: str = Header(None)) -> dict:
    """Dependency for routes where rfq_id is a path parameter -- FastAPI
    resolves this dependency's own `rfq_id` argument from the exact same
    path-param source the route handler's `rfq_id` comes from, so this
    always sees the real value for that specific request, not a guess."""
    return _decode_and_check(_extract_bearer(authorization), rfq_id)


def verify_token_form(rfq_id: str = Form(...), authorization: str = Header(None)) -> dict:
    """Dependency for routes where rfq_id arrives as a multipart form field
    (upload_server.py's upload endpoints) rather than a path parameter."""
    return _decode_and_check(_extract_bearer(authorization), rfq_id)


def verify_token_project(project_id: str, authorization: str = Header(None)) -> dict:
    """FDE Staging Pipeline's counterpart to verify_token() above -- same
    JWT scheme/secret, scoped to a project_id path parameter instead of
    rfq_id. Used by routes for an EXISTING project (upload, list files)."""
    return _decode_and_check(_extract_bearer(authorization), project_id, claim_name="project_id")


def verify_token_project_form(project_id: str = Form(...), authorization: str = Header(None)) -> dict:
    """FDE Staging Pipeline's counterpart to verify_token_form() above --
    project_id arrives as a form field rather than a path parameter."""
    return _decode_and_check(_extract_bearer(authorization), project_id, claim_name="project_id")


def verify_token_any_project(authorization: str = Header(None)) -> dict:
    """FDE Staging Pipeline only: gates POST/GET /api/fde/projects (create
    and list) -- both happen before any project_id exists yet to scope a
    token to, so there's nothing to compare against. Still enforces a
    validly-signed, non-expired token (signature/iat/exp), just no
    claim-match check. The frontend mints this token via authFetchFde()
    called with a placeholder project_id (e.g. "new") purely to get a
    fresh signed token -- that placeholder value is never actually checked
    server-side for these two routes."""
    return _decode_and_check(_extract_bearer(authorization), None)
