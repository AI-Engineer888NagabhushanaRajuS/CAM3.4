# Security report — Centum / BuLLMQuote-SRIM

5 gaps, each independently re-verified against live source this session
(not carried from an older report without re-checking). None showed evidence
of active exploitation during this review — this is a pre-exposure hardening
list, not an incident report.

---

## 1. `POST /auth/token` issues a token for any `rfq_id`, no credential required

**File:** `fastmcp-router/duck_db_api.py` ~148–161
**What:** The endpoint that mints every JWT has no authentication check before
calling `issue_token()`. Anyone who can reach this service on the network can
mint a valid token for any `rfq_id`.
**Context:** documented in `docs/Security/jwt-rfq-request-auth.md` as a
deliberate, scoped choice — the JWT layer stops *accidental* cross-RFQ
requests, not a determined attacker. Restating it here because the practical
effect (zero-credential token minting) reads differently from a distance than
"there's a JWT layer" does.
**Fix:** require a shared service-to-service secret or network-level
restriction (e.g. this port not reachable outside the host/mesh) before
minting, if the threat model changes from "accidental" to "adversarial."

## 2. `CORS allow_origins=["*"]` in three backend services

**Files:** `fastmcp-router/duck_db_api.py`, `fastmcp-router/hitl_router.py`,
`fastmcp-router/upload_server.py`
**What:** All three accept cross-origin requests from any origin.
**Fix:** restrict to the actual frontend origin(s) this deployment serves.

## 3. Shared JWT secret ships with an insecure default

**File:** `docs/Security/jwt-rfq-request-auth.md` (documents the default;
`fastmcp-router/auth.py` reads it from environment at runtime)
**What:** The default value `dev-only-shared-rfq-jwt-secret-change-me` is
explicitly flagged in its own docs as something that "MUST be" changed. Not
confirmed here whether the live deployment has actually overridden it —
worth a direct check (`echo $JWT_SECRET` on the running service, not a code
read) since this doc only confirms the code *reads* from env, not what value
is actually set.
**Fix:** confirm the live value is not the shipped default; rotate if it is.

## 4. Hardcoded test credentials ship in frontend source

**File:** `accomplish-ui/apps/web/src/client/pages/LoginPage.tsx`
**What:** `password: 'srim-test-2026'` is hardcoded at module scope, wired to
a one-click test-login button. No runtime guard (environment check, build
flag) prevents this shipping to a production build.
**Fix:** gate the test-login button behind a build-time environment check
(e.g. `import.meta.env.DEV`) so it cannot appear in a production bundle.

## 5. Reporting server's external gateway registration points at a stale port

**File:** `mcp-tools/reporting/superset/mcp_server.py` line 153
**What:** The server actually binds `port=8105`. MCP Jungle's own external
registration for it still points at the old `:8005`. The code's own docstring
already flags this as a live operational risk.
**Fix:** update the MCP Jungle registration to `:8105`, or confirm whatever
currently calls `:8005` is dead and remove the stale registration instead.

---

## Separately: shared infrastructure, not this repo's own code

**MCP Jungle (`:8080`, reachable over this host's NetBird mesh IP, not just
localhost) is a gateway shared across multiple projects on this machine, not
exclusive to Centum/CAM.** Two of its 13 registered servers —
`postgres_logic` and `postgres_metadata` — are direct Postgres MCP connectors
into `logic_db`/`file_metadata_db` configured with **`--access-mode=unrestricted`**.
Any tool or agent routed through that shared gateway can read or write this
platform's real tables directly, completely bypassing the application layer.
A second pair, `postgres_logic_2`/`postgres_metadata_2`, does the same against
`logic_db_2`/`file_metadata_db_2`.

This is not a bug in Centum/CAM's own code — it's a property of the shared
gateway's configuration — but it directly affects this platform's data, so
it belongs in this report. **This needs a decision from whoever owns the MCP
Jungle gateway config**, not a code fix here: either narrow those connectors
to read-only access, or confirm the access model is intentional and
documented as such.

## What was not checked

`project2_owner`'s reported ability to `CONNECT` to all 9 databases on the
Postgres instance, including ones meant to be isolated, was **not**
independently re-queried this session. Checking it requires connecting to
live Postgres with the superuser credential found in source — this session's
own safety controls declined that action, and it was not worked around. If
this needs confirming, it should be done directly by whoever holds those
credentials, not by having an agent use a credential it found in a file.
