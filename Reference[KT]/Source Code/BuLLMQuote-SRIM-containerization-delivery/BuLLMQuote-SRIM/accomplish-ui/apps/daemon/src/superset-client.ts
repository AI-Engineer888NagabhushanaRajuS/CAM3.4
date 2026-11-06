/**
 * Server-side Apache Superset client -- fetches guest tokens for embedding a dashboard
 * (stage 9, "Reports & Analytics") without ever exposing Superset admin credentials to
 * the browser. Mirrors the existing external-service pattern in browser-api-server.ts
 * (env var -> fetch -> JSON body), kept in its own module since this one needs a small
 * in-memory access-token cache and a two-step login+guest-token call sequence.
 */
import { log } from './logger.js';

const SUPERSET_URL = (process.env.SUPERSET_URL ?? 'http://localhost:8088').replace(/\/$/, '');
const SUPERSET_ADMIN_USERNAME = process.env.SUPERSET_ADMIN_USERNAME ?? '';
const SUPERSET_ADMIN_PASSWORD = process.env.SUPERSET_ADMIN_PASSWORD ?? '';

// Superset access tokens are short-lived; re-logging in on every guest-token request
// would work but is wasteful for a dashboard a user may leave open and re-poll -- cache
// for a few minutes, well under Superset's own token lifetime, and re-login lazily once
// it expires. Mirrors the simplicity of BrowserApiServer's own in-memory `sessions` Map
// (no persisted store needed for a value this short-lived and easily re-derived).
const ACCESS_TOKEN_TTL_MS = 4 * 60 * 1000;
let cachedAccessToken: { token: string; expiresAt: number } | null = null;

async function getSupersetAccessToken(): Promise<string> {
  if (cachedAccessToken && cachedAccessToken.expiresAt > Date.now()) {
    return cachedAccessToken.token;
  }
  if (!SUPERSET_ADMIN_USERNAME || !SUPERSET_ADMIN_PASSWORD) {
    throw new Error('Superset not configured (SUPERSET_ADMIN_USERNAME/SUPERSET_ADMIN_PASSWORD missing)');
  }

  const res = await fetch(`${SUPERSET_URL}/api/v1/security/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: SUPERSET_ADMIN_USERNAME,
      password: SUPERSET_ADMIN_PASSWORD,
      provider: 'db',
      refresh: true,
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Superset login failed: HTTP ${res.status} — ${text}`);
  }
  const data = (await res.json()) as { access_token?: string };
  if (!data.access_token) {
    throw new Error('Superset login response missing access_token');
  }
  cachedAccessToken = { token: data.access_token, expiresAt: Date.now() + ACCESS_TOKEN_TTL_MS };
  return data.access_token;
}

/**
 * Fetches a CSRF token for a Bearer-authenticated Superset API call, plus the session
 * cookie Superset ties it to. Confirmed against the real running instance that Superset
 * rejects the guest_token POST with "The CSRF session token is missing" if only the
 * X-CSRFToken header is sent without the matching session cookie -- Superset's CSRF
 * check validates the header's token against a value stored server-side in that
 * session, not the Bearer token alone. Node's fetch has no shared cookie jar across
 * separate calls (unlike a browser), so the Set-Cookie from this response must be
 * captured and forwarded manually on the follow-up request.
 */
async function getSupersetCsrfToken(accessToken: string): Promise<{ csrfToken: string; cookie: string } | null> {
  try {
    const res = await fetch(`${SUPERSET_URL}/api/v1/security/csrf_token/`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) return null;
    const setCookie = res.headers.get('set-cookie');
    const data = (await res.json()) as { result?: string };
    if (!data.result || !setCookie) return null;
    // Only the cookie's name=value pair is needed on the request Cookie header --
    // strip Set-Cookie's own attributes (Path, HttpOnly, SameSite, etc.).
    const cookie = setCookie.split(';')[0];
    return { csrfToken: data.result, cookie };
  } catch {
    return null;
  }
}

// RFQ IDs throughout this platform are system-generated (e.g. "RFQ-000056")
// but the search box that ultimately supplies this value is freely editable
// text -- never interpolate it into the RLS clause below without validating
// it first. Same character class every backend _validate_id()/rfq_id column
// convention in this codebase already assumes.
const VALID_RFQ_ID = /^[A-Za-z0-9_-]+$/;

export async function getSupersetGuestToken(dashboardUuid: string, rfqId?: string): Promise<string> {
  const accessToken = await getSupersetAccessToken();
  const csrf = await getSupersetCsrfToken(accessToken);

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${accessToken}`,
  };
  if (csrf) {
    headers['X-CSRFToken'] = csrf.csrfToken;
    headers['Cookie'] = csrf.cookie;
  }

  // Row Level Security scopes the embedded dashboard to just this RFQ's data
  // instead of every RFQ ever processed. Assumes the dataset(s) backing this
  // dashboard have an `rfq_id` column -- the convention used everywhere else
  // in this platform (Postgres, DuckDB) -- adjust the column name here if this
  // specific Superset dataset names it differently. Fails open (no RLS, full
  // dashboard) for a missing/invalid rfqId rather than sending a malformed
  // clause Superset would just reject the whole guest-token request over.
  const rls = rfqId && VALID_RFQ_ID.test(rfqId)
    ? [{ clause: `rfq_id = '${rfqId}'` }]
    : [];

  const res = await fetch(`${SUPERSET_URL}/api/v1/security/guest_token/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      user: { username: 'guest', first_name: 'Guest', last_name: 'User' },
      resources: [{ type: 'dashboard', id: dashboardUuid }],
      rls,
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    // A stale cached access token could cause a 401 here -- drop it so the next call
    // re-logs in, rather than repeatedly failing until the TTL naturally expires.
    if (res.status === 401) cachedAccessToken = null;
    log.warn(`[Superset] guest_token request failed: HTTP ${res.status} — ${text}`);
    throw new Error(`Superset guest token request failed: HTTP ${res.status}`);
  }
  const data = (await res.json()) as { token?: string };
  if (!data.token) {
    throw new Error('Superset guest_token response missing token');
  }
  return data.token;
}

export function getSupersetDomain(): string {
  return SUPERSET_URL;
}
