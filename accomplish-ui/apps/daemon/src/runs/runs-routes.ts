/**
 * SPEC-021 tracking: GET /api/runs?by=<email>&limit=<n> lists recent pipeline runs of every RFQ (who ran what, when, passed or failed).
 * The upload service answers to any valid token, so WHO MAY SEE WHAT is decided here, from the signed-in session: an admin sees everyone's
 * runs (and may ask for one user's), anybody else sees only the runs they started themselves.
 */
import type http from 'node:http';

export interface RunsSession {
  email: string;
  role: string;
}

const bridge = (): string => (process.env.PYTHON_BRIDGE_URL ?? process.env.PYTHON_SERVICE_URL ?? 'http://localhost:3110').replace(/\/$/, '');
// Compose publishes upload-server on 13100; the bare-metal default is 3100.
const uploadServer = (): string => (process.env.RFQ_UPLOAD_URL ?? 'http://localhost:3100').replace(/\/$/, '');

type Fetch = typeof fetch;

function send(res: http.ServerResponse, code: number, body: unknown): void {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

/** Which address the listing is limited to: null = everybody (admin only). */
export function visibleTo(session: RunsSession, requested: string | null): string | null {
  return session.role === 'admin' ? requested : session.email;
}

/** True when the URL belongs to this module (the caller then stops). Never throws. */
export function handleRunsRoute(req: http.IncomingMessage, res: http.ServerResponse, session: RunsSession | null, doFetch: Fetch = fetch): boolean {
  const url = new URL(req.url ?? '/', 'http://localhost');
  if (url.pathname !== '/api/runs') {
    return false;
  }
  void (async () => {
    try {
      if (!session) {
        send(res, 401, { error: 'Not signed in' });
        return;
      }
      if (req.method !== 'GET') {
        send(res, 405, { error: 'GET only' });
        return;
      }
      const limit = Math.min(Math.max(Number.parseInt(url.searchParams.get('limit') ?? '50', 10) || 50, 1), 100);
      const by = visibleTo(session, url.searchParams.get('by'));
      const tokenRes = await doFetch(`${bridge()}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rfq_id: 'ALL-RUNS' }),
        signal: AbortSignal.timeout(5000),
      });
      if (!tokenRes.ok) {
        send(res, 502, { error: `Could not get a token for the run history (HTTP ${tokenRes.status})` });
        return;
      }
      const { token } = (await tokenRes.json()) as { token: string };
      const q = new URLSearchParams({ limit: String(limit), ...(by ? { by } : {}) });
      const up = await doFetch(`${uploadServer()}/api/runs?${q.toString()}`, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(30000) });
      const body = (await up.json().catch(() => ({}))) as { runs?: unknown; detail?: string };
      if (!up.ok) {
        send(res, up.status === 400 ? 400 : 502, { error: typeof body.detail === 'string' ? body.detail : `The upload service answered HTTP ${up.status}` });
        return;
      }
      send(res, 200, { runs: body.runs ?? [], scope: by ? { email: by } : 'everyone' });
    } catch (e) {
      if (!res.headersSent) {
        send(res, 502, { error: `Run history unavailable: ${e instanceof Error ? e.message : String(e)}` });
      }
    }
  })();
  return true;
}
