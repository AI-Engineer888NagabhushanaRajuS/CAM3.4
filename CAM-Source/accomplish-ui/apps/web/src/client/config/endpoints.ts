/**
 * Centralized network endpoint registry for the web client.
 *
 * SINGLE SOURCE OF TRUTH for the backend (daemon Browser API) address.
 * Every transport caller — RPC, SSE event stream, session/login, health
 * polling — must read from here instead of hardcoding `http://127.0.0.1:9234`.
 *
 * Resolution order (most migration-proof first):
 *   1. `VITE_BACKEND_URL` env var  → explicit override (set in `.env`, CI, or
 *      the hosting platform). Use this when the API lives on a different
 *      origin/subdomain than the SPA.
 *   2. Dev default                 → `http://127.0.0.1:9334` (matches the
 *      daemon's BrowserApiServer during `pnpm dev:web` -- bumped off CAM's
 *      centum-intake stack's port 9234 so both stacks can run side by side).
 *   3. Production default          → same origin that served the app, so
 *      deploying to a real domain (behind a reverse proxy that routes
 *      /rpc, /events, /health to the daemon) needs ZERO code changes.
 *
 * To change the port/host everywhere: edit the dev fallback below, or set
 * VITE_BACKEND_URL. Nothing else in the codebase should reference the address.
 */

function resolveBackendUrl(): string {
  const fromEnv = import.meta.env.VITE_BACKEND_URL as string | undefined;
  if (fromEnv && fromEnv.trim()) {
    console.log(`[endpoints.ts] Using VITE_BACKEND_URL override: ${fromEnv}`);
    // Strip any trailing slash so `${BACKEND_URL}/rpc` never double-slashes.
    return fromEnv.trim().replace(/\/+$/, '');
  }
  if (import.meta.env.DEV) {
    console.log(import.meta.env.DEV);
    console.log("[endpoints.ts] Using dev fallback backend URL: http://127.0.0.1:9334");
    console.log(`${window.location.protocol}//${window.location.hostname}:9334`)
    return `${window.location.protocol}//${window.location.hostname}:9334`;
  }
  // Production build served from a domain: talk to the same origin.
  return window.location.origin;
}

/** Absolute base URL of the backend Browser API (no trailing slash). */
export const BACKEND_URL = resolveBackendUrl();

/**
 * Build an absolute backend URL for a given path.
 * @param path A path beginning with `/` (e.g. `/rpc`, `/events`, `/health`).
 */
export function backendUrl(path: string): string {
  return `${BACKEND_URL}${path}`;
}

/**
 * The RFQ upload_server (FastAPI, port 3100) -- a separate Python service from
 * the daemon, handling BOM/QuoteWin/costing-sheet file uploads.
 *
 * Same resolution order as BACKEND_URL above (env override, then dev fallback
 * derived from window.location.hostname, then same-origin for production) --
 * a previous version of this hardcoded `http://192.168.1.27:3000` directly in
 * 4 separate call sites (App.tsx, StageExecutionOutput.tsx,
 * RfqIntakeUploadModal.tsx, RfqErpQuoteWinUploadModal.tsx), which broke
 * uploads for any client not on that exact LAN (e.g. connected over NetBird)
 * since the browser can't reach a private LAN IP from outside that LAN.
 */
function resolveRfqUploadUrl(): string {
  const fromEnv = import.meta.env.VITE_RFQ_UPLOAD_URL as string | undefined;
  if (fromEnv && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/+$/, '');
  }
  if (import.meta.env.DEV) {
    return `${window.location.protocol}//${window.location.hostname}:3100`;
  }
  return window.location.origin;
}

/** Absolute base URL of the RFQ upload_server (no trailing slash). */
export const RFQ_UPLOAD_URL = resolveRfqUploadUrl();

/**
 * duck_db_api.py (FastAPI, port 3110) -- the "Python Bridge" wrapping BOM
 * preview/inline-edit-save/export-download. Same resolution order and same
 * hardcoded-LAN-IP bug as RFQ_UPLOAD_URL above (2 call sites: App.tsx,
 * StageExecutionOutput.tsx).
 */
function resolvePythonBridgeUrl(): string {
  const fromEnv = import.meta.env.VITE_PYTHON_BRIDGE_URL as string | undefined;
  if (fromEnv && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/+$/, '');
  }
  if (import.meta.env.DEV) {
    return `${window.location.protocol}//${window.location.hostname}:3110`;
  }
  return window.location.origin;
}

/** Absolute base URL of the Python Bridge (duck_db_api.py, no trailing slash). */
export const PYTHON_BRIDGE_URL = resolvePythonBridgeUrl();

/**
 * hitl_router.py (FastAPI, port 5102) -- the final_selection_conflicts
 * review/resolve service (stage 6, pricingConsolidation). Same resolution
 * order and same hardcoded-LAN-IP bug as the others above.
 */
function resolveHitlBridgeUrl(): string {
  const fromEnv = import.meta.env.VITE_HITL_BRIDGE_URL as string | undefined;
  if (fromEnv && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/+$/, '');
  }
  if (import.meta.env.DEV) {
    return `${window.location.protocol}//${window.location.hostname}:5102`;
  }
  return window.location.origin;
}

/** Absolute base URL of the HITL router (hitl_router.py, no trailing slash). */
export const HITL_BRIDGE_URL = resolveHitlBridgeUrl();

/**
 * FDE Staging Pipeline's upload/project endpoints -- same physical process
 * as RFQ_UPLOAD_URL above (upload_server.py, port 3100, ENABLE_FDE_ROUTES
 * conditionally registers /api/fde/*), kept as its own named export so a
 * future split-deployment can point it elsewhere with zero code changes,
 * same reasoning RFQ_UPLOAD_URL/PYTHON_BRIDGE_URL/HITL_BRIDGE_URL already
 * each get their own resolver despite some sharing hosts today.
 */
function resolveFdeUploadUrl(): string {
  const fromEnv = import.meta.env.VITE_FDE_UPLOAD_URL as string | undefined;
  if (fromEnv && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/+$/, '');
  }
  if (import.meta.env.DEV) {
    return `${window.location.protocol}//${window.location.hostname}:3100`;
  }
  return window.location.origin;
}

/** Absolute base URL of the FDE upload/project endpoints (no trailing slash). */
export const FDE_UPLOAD_URL = resolveFdeUploadUrl();
