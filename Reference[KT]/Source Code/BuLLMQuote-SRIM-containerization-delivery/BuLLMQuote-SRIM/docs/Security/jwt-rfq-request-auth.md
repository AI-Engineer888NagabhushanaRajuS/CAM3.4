# Security Fix: Per-Request RFQ-Scoped JWT Authentication

**Date:** 2026-09-02
**Status:** Implemented, verified, live
**Requested by:** Platform owner, in response to this platform's own documented
known limitation — "no authentication on internal APIs" (see the root
`CLAUDE.md`'s Development Notes section).

## 1. What changed

Every request the web frontend (and the daemon's one direct server-to-server
call) makes to 3 of this platform's backend services must now carry
```
Authorization: Bearer <jwt>
```
where the JWT's payload is
```json
{ "rfq_id": "<the rfq_id this specific request is about>", "iat": <unix ts>, "exp": <iat + 60> }
```
The token is minted fresh by the backend immediately before each real
request (not cached/reused across calls, since it's deliberately only valid
for 60 seconds), and is rejected with `401 Unauthorized` if it's missing,
malformed, expired, signed with the wrong secret, or scoped to a different
`rfq_id` than the request it's attached to.

## 2. Why this design, and what it actually protects against

This is **request-integrity/isolation enforcement scoped to a single RFQ's
data**, not a user-identity/authorization system. It does not answer "is
this person allowed to see this RFQ" (this platform still has no
user-identity concept in the Python backend — see the root `CLAUDE.md`'s own
"no user-identity/auth concept" limitation, unchanged by this work) — it
answers "does this specific request genuinely intend to act on the `rfq_id`
it claims to."

**What it defends against:**
- A stray/misconfigured client (or a bug) accidentally sending a request for
  one RFQ's data with a URL built for a different RFQ — the token's own
  embedded `rfq_id` claim must match the URL/form `rfq_id`, so a mismatch is
  now a hard `401`, not silently served.
- Basic tampering with request rfq_id at the network layer without also
  forging a validly-signed token.
- A leaked/logged token being replayed after any meaningful delay — the
  60-second `exp` window makes stolen tokens practically useless outside a
  live session.

**What it does NOT defend against (be clear-eyed about this):**
- `POST /auth/token` is itself **unauthenticated** — anyone who can reach
  `python_bridge` on the network can mint a valid token for *any* `rfq_id`
  on request, with no credential check at all. This is intentional given the
  requested design ("frontend asks backend for a token first," chosen
  explicitly over a shared-secret-baked-into-the-frontend-build approach
  during scoping) — it stops accidental/naive cross-RFQ requests, not a
  determined attacker who can already reach these services.
- All 3 protected services trust one **shared HMAC secret**
  (`JWT_SECRET` env var, `fastmcp-router/auth.py`). Compromising any one
  service's environment compromises token-forging ability for all three.
  **The shipped default (`dev-only-shared-rfq-jwt-secret-change-me`) MUST be
  overridden via the `JWT_SECRET` environment variable before any real
  deployment** — this mirrors the existing, already-documented pattern for
  `db.py`'s own Postgres credential fallback.
- Network-layer trust is unchanged: these services still bind to
  `0.0.0.0`/LAN IPs with permissive CORS (`allow_origins=["*"]`), as they did
  before this change — this work adds a request-level check on top of an
  already-open network posture, it does not close that posture.

## 3. Scope

### Protected (JWT required, validated per request)

| Service | File | Routes protected |
|---|---|---|
| python_bridge | `fastmcp-router/duck_db_api.py` | 13 of 16 routes (see exclusions below) |
| upload_server | `fastmcp-router/upload_server.py` | All 4 routes |
| hitl_router | `fastmcp-router/hitl_router.py` | All 6 routes |

**23 routes total**, validated via two FastAPI dependencies in the new
shared `fastmcp-router/auth.py`:
- `verify_token(rfq_id: str, authorization: str = Header(None))` — routes
  where `rfq_id` is a path parameter (the majority).
- `verify_token_form(rfq_id: str = Form(...), authorization: str = Header(None))`
  — routes where `rfq_id` arrives as a multipart form field
  (`upload_server.py`'s 3 upload endpoints).

Both call a shared `_decode_and_check()` that verifies the HS256 signature,
enforces `exp == iat + 60` exactly (not just "not yet expired" — a token
with any other exp/iat relationship is rejected), and checks the token's
`rfq_id` claim against the request's own `rfq_id`.

### Explicitly excluded, and why

| Excluded route(s) | Reason |
|---|---|
| `fastapi_router.py`'s 2 endpoints (`/pipeline/routing-sequence/{rfq_id}/{profile_name}`, `/tool/execute`) | Called by **Dify's own workflow** (external, not this frontend) — confirmed via `docs/DMR/dynamic-master-router.md` and this session's own investigation. Dify's workflow graph lives outside this repo and can't be updated here to mint/attach a token; requiring auth here would break every Dify-driven pipeline run. |
| `duck_db_api.py`: `GET /api/bom/export-cbom/{rfq_id}/download`, `GET /api/bom/export-quote/{rfq_id}/download`, `GET /api/bom/export/{rfq_id}/download` | **Explicit platform-owner decision (2026-09-02)**, made after discovering `App.tsx`'s Quote Readiness panel links to these via a plain `window.open(url)`, which cannot attach a custom `Authorization` header. Rather than rework that panel to the fetch+blob+anchor-click pattern already used for the equivalent buttons in `StageExecutionOutput.tsx`, these 3 routes were left unauthenticated for every caller. Documented inline at each route's own docstring in `duck_db_api.py`. |
| `POST /auth/token` itself | Can't require the credential it's the one issuing. |

### Frontend

New shared helper: `accomplish-ui/apps/web/src/client/lib/apiAuth.ts`
- `authFetch(url, rfqId, options)` — mints a token via `POST
  {PYTHON_BRIDGE_URL}/auth/token`, then calls `fetch` with `Authorization:
  Bearer <token>` merged into the caller's own headers. Drop-in replacement
  for bare `fetch`.
- `authDownload(url, rfqId, fallbackFilename)` — for the handful of
  downloads that used to rely on `window.open(url)` (which can't carry a
  custom header): fetches with the auth header attached, reads the response
  as a `Blob`, and triggers the save via a synthetic `<a download>` click.

Wired into every real call site across:
`App.tsx`, `StageExecutionOutput.tsx`, `RfqIntakeUploadModal.tsx`,
`RfqExecutionCard.tsx`, `RfqErpQuoteWinUploadModal.tsx` — 21 call sites in
total (one was missed in the first pass — a computed-URL `fetch` inside
`StageExecutionOutput.tsx`'s `handleSaveChanges`, found via a follow-up
repo-wide sweep and fixed the same day).

The daemon's one direct server-to-server call to `duck_db_api.py`
(`apps/daemon/src/browser-api-server.ts`, the `bom:get-preview-data` case)
now mints its own token the same way before calling through.

The Admin panel (`/organization`, `/project`, `/costing`, role-gated via
`isAdmin()`/`requireAdmin()` in `lib/session.ts`) was checked and confirmed
to load its data from static Excel assets (`lib/masterExcel.ts`), never
calling any of the 3 protected services directly — no changes needed there.

## 4. Files changed

**Backend** (`fastmcp-router/`):
- `auth.py` — **new**. `create_token`, `verify_token`, `verify_token_form`,
  `_decode_and_check`, `_extract_bearer`.
- `duck_db_api.py` — new `POST /auth/token` endpoint; `Depends(auth.verify_token)`
  added to 13 routes (3 later removed per the carve-out above).
- `upload_server.py` — `Depends(auth.verify_token)`/`verify_token_form` added
  to all 4 routes.
- `hitl_router.py` — `Depends(auth.verify_token)` added to all 6 routes.

**Frontend** (`accomplish-ui/apps/web/src/client/`):
- `lib/apiAuth.ts` — **new**.
- `App.tsx`, `components/execution/StageExecutionOutput.tsx`,
  `components/rfq/RfqIntakeUploadModal.tsx`,
  `components/rfq/RfqExecutionCard.tsx`,
  `components/rfq/RfqErpQuoteWinUploadModal.tsx` — call sites converted to
  `authFetch`/`authDownload`.

**Daemon**:
- `accomplish-ui/apps/daemon/src/browser-api-server.ts` — one call site
  updated to mint a token before calling `duck_db_api.py`.

## 5. Dependencies

- Backend: `pyjwt` (already present in the Python environment these
  services run under — no new install needed; confirmed `pyjwt==2.13.0`).
- Frontend: none added — the frontend never decodes a JWT, it only relays
  the opaque string the backend hands it.

## 6. Verification performed

**Backend, via direct `curl` against the live services:**
- No `Authorization` header → `401`.
- Malformed header (`NotBearer ...`) → `401`.
- Valid token, correct `rfq_id` → `200`.
- Valid token, `rfq_id` mismatched against the URL → `401`
  (`"Token rfq_id does not match request rfq_id"`).
- Synthetically pre-expired token → `401` (`"Token expired"`).
- A token minted by `python_bridge` accepted by `upload_server` and
  `hitl_router` (confirms the shared secret works cross-service).
- After the carve-out: the 3 download routes return `200` with no header at
  all; every other route sampled still correctly returns `401` without one.

**Frontend, via a real headless-browser session against the live app**
(login → search → open RFQ-000004):
- Confirmed `POST /auth/token` fires immediately before each real request.
- Confirmed every sampled `/api/bom/*`, `/api/dify/*` request carried a
  populated `Authorization` header.
- Zero failed (4xx/5xx) responses on any BOM/RFQ API call during the
  session; UI rendered identically to pre-change behavior.

**Repo-wide sweep** (after the first pass): grepped all of
`apps/web/src/client/` for any remaining bare `fetch(` referencing
`PYTHON_BRIDGE_URL`/`RFQ_UPLOAD_URL`/`HITL_BRIDGE_URL` or their derived
constants — found and fixed one missed call site
(`StageExecutionOutput.tsx`'s `handleSaveChanges`, which built its target
URL into a variable rather than inlining the constant, so it didn't match
the first pass's literal-pattern search).

## 7. Known residual risks / recommended follow-ups

1. **`JWT_SECRET` has an insecure dev-fallback default.** Set it explicitly
   (identical value across all 3 services) before any deployment reachable
   off of localhost — same caveat this codebase already documents for
   `db.py`'s Postgres credentials.
2. **`POST /auth/token` is unauthenticated by design.** If stronger
   isolation is ever needed (e.g. multi-tenant, per the platform's own
   documented "Project Isolation — not yet implemented" gap in the root
   `CLAUDE.md`), this endpoint would need a real credential check before
   issuing a token, not just an `rfq_id` string.
3. **3 download routes are permanently unauthenticated** — revisit if
   `App.tsx`'s Quote Readiness panel is ever reworked to use `authDownload`
   instead of `window.open`, at which point auth could be safely restored
   there too.
4. **`fastapi_router.py` remains fully open** — the two routes Dify calls
   have no auth of any kind. Closing this gap would require adding an HTTP
   Request node to Dify's own workflow (external to this repo) to fetch and
   attach a token before each of its calls.
5. Existing, still-open, already-documented gaps this work doesn't touch:
   no user-identity concept in the Python backend, permissive
   `allow_origins=["*"]` CORS on all 3 services, and no rate limiting on
   `POST /auth/token` itself.
