/**
 * Per-request JWT auth for the 3 RFQ-scoped backend services (python_bridge
 * / duck_db_api.py, upload_server.py, hitl_router.py — NOT fastapi_router.py,
 * whose 2 endpoints are called by Dify's own workflow, not this frontend).
 *
 * Every call to those services must carry `Authorization: Bearer <jwt>`
 * whose payload's rfq_id matches that specific request, with iat/exp a
 * 60-second window. Tokens are deliberately too short-lived to reuse across
 * calls, so a fresh one is minted right before every real request via
 * `POST {PYTHON_BRIDGE_URL}/auth/token` — see fastmcp-router/auth.py's own
 * module docstring for the full backend-side contract.
 */

import { PYTHON_BRIDGE_URL } from '../config/endpoints';

async function getRfqToken(rfqId: string): Promise<string> {
  const res = await fetch(`${PYTHON_BRIDGE_URL}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rfq_id: rfqId }),
  });
  if (!res.ok) {
    throw new Error(`Failed to mint auth token for rfq_id=${rfqId}: HTTP ${res.status}`);
  }
  const data = (await res.json()) as { token: string };
  return data.token;
}

/**
 * Drop-in replacement for `fetch()` against python_bridge/upload_server/
 * hitl_router — mints a fresh rfq-scoped token first, then attaches it as
 * `Authorization: Bearer <token>` alongside any headers the caller supplied.
 */
export async function authFetch(url: string, rfqId: string, options: RequestInit = {}): Promise<Response> {
  const token = await getRfqToken(rfqId);
  return fetch(url, {
    ...options,
    headers: {
      ...(options.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
  });
}

/**
 * Triggers a browser download from an auth-protected GET endpoint.
 *
 * `window.open(url)` (the previous pattern for these 3 download buttons)
 * cannot attach a custom Authorization header, so this fetches the file with
 * the header attached, then triggers the save via a synthetic anchor click —
 * same blob+anchor pattern already used elsewhere in this codebase for
 * client-side exceljs downloads.
 */
export async function authDownload(url: string, rfqId: string, fallbackFilename = 'download.xlsx'): Promise<void> {
  const res = await authFetch(url, rfqId);
  if (!res.ok) {
    throw new Error(`Download failed: HTTP ${res.status}`);
  }
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match?.[1] ?? fallbackFilename;

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

/**
 * FDE Staging Pipeline's counterpart to getRfqToken/authFetch above -- same
 * JWT scheme/secret (see fastmcp-router/auth.py's create_token claim_name
 * parameter), scoped to a project_id claim instead of rfq_id.
 */
async function getProjectToken(projectId: string): Promise<string> {
  const res = await fetch(`${PYTHON_BRIDGE_URL}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!res.ok) {
    throw new Error(`Failed to mint auth token for project_id=${projectId}: HTTP ${res.status}`);
  }
  const data = (await res.json()) as { token: string };
  return data.token;
}

/**
 * Drop-in FDE equivalent of authFetch() above -- mints a fresh
 * project-scoped token first, then attaches it as `Authorization: Bearer
 * <token>`. For routes that don't yet have a project_id (create/list
 * projects), pass any placeholder string (e.g. "new") -- the server-side
 * verify_token_any_project dependency never checks it against anything.
 */
export async function authFetchFde(url: string, projectId: string, options: RequestInit = {}): Promise<Response> {
  const token = await getProjectToken(projectId);
  return fetch(url, {
    ...options,
    headers: {
      ...(options.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
  });
}

export { getRfqToken, getProjectToken };
