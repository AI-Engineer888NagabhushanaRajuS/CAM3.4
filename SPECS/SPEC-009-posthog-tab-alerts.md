# SPEC-009 — PostHog Per-Tab Failure Alerts

## Branch
`feat/spec-009-posthog-tab-alerts`

## Why
SPEC-002 built per-tab validators (16 report tabs). When a tab fails validation, the error
is returned to the UI but no analytics event is emitted. Architecture diagrams (Diagram 1)
show CAM 3.4 should emit structured telemetry on failure modes so the ops team can track
which tabs / which RFQ patterns cause the most failures. PostHog is the chosen telemetry
provider (already in accomplish-ui's package.json or easily added).

## Scope (files to change)

### 1. Add PostHog client to accomplish-ui — `accomplish-ui/apps/web/`
Check if `posthog-js` is already in package.json. If not, add it.
Initialize PostHog in `apps/web/src/client/main.tsx` (or equivalent entry point):
```typescript
import PostHog from 'posthog-js'
const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY ?? ''
if (POSTHOG_KEY) PostHog.init(POSTHOG_KEY, { api_host: 'https://app.posthog.com' })
export const posthog = PostHog
```
If key is empty, PostHog is a no-op (safe for dev with no key set).

### 2. Emit event on tab validation failure — `accomplish-ui/apps/web/src/client/`
Find where per-tab validation results are displayed (likely a component near the report
tabs or a hook that calls GET /rfq/{rfq_id}/status). After receiving validation failures,
emit:
```typescript
posthog.capture('rfq_tab_validation_failed', {
  rfq_id: rfqId,
  tab_name: failedTab.name,
  error_count: failedTab.errors.length,
  errors: failedTab.errors.slice(0, 5), // cap at 5 for payload size
})
```

### 3. Add VITE_POSTHOG_KEY to .env.example — `accomplish-ui/apps/web/.env.example`
```
VITE_POSTHOG_KEY=
```
(empty default = no-op)

### 4. Server-side event option — `fastapi-router/fastapi_router.py`
If the validation happens server-side (SPEC-002 wrote validate_reports MCP tool),
add a lightweight PostHog HTTP event call using `httpx` when validation fails.
PostHog API key from env: `POSTHOG_API_KEY`. If not set, skip silently.
Use `posthog_python` only if already a dependency — otherwise raw httpx POST to
`https://app.posthog.com/capture/` is fine (3 lines, no new dep).

## Tests
- `testing/test_posthog_events.py`: mock `posthog.capture`, trigger a tab validation failure,
  assert `rfq_tab_validation_failed` was called with correct keys
- Tests must pass with VITE_POSTHOG_KEY unset (no-op path)

## Acceptance criteria
- PostHog initialized but gated on `VITE_POSTHOG_KEY` env var
- `rfq_tab_validation_failed` event emitted on every tab validation failure
- No crash when key is absent (dev mode)
- `.env.example` updated
