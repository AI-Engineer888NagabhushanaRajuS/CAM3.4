import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import http from 'node:http';
import { handleRunsRoute, visibleTo, type RunsSession } from '../src/runs/runs-routes.js';

const sessions: Record<string, RunsSession> = { admin: { email: 'boss@x.test', role: 'admin' }, user: { email: 'dana@x.test', role: 'user' } };
const upstream = vi.fn();
let server: http.Server;
let base = '';

beforeAll(async () => {
  server = http.createServer((req, res) => {
    const who = req.headers['x-test-user'];
    const session = typeof who === 'string' ? sessions[who] ?? null : null;
    const fake = (async (url: string, init?: RequestInit) => upstream(String(url), init)) as unknown as typeof fetch;
    if (!handleRunsRoute(req, res, session, fake)) res.writeHead(404).end();
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
});
afterAll(() => { server.close(); });
beforeEach(() => {
  upstream.mockReset();
  upstream.mockImplementation(async (url: string) => (url.endsWith('/auth/token')
    ? new Response(JSON.stringify({ token: 'jwt' }))
    : new Response(JSON.stringify({ runs: [{ rfq_id: 'RFQ-1', started_by: 'Dana' }] }))));
});

const get = async (q: string, as: string | null) => {
  const res = await fetch(`${base}/api/runs${q}`, { headers: as ? { 'x-test-user': as } : {} });
  return { status: res.status, json: (await res.json()) as any }; // eslint-disable-line @typescript-eslint/no-explicit-any
};
const upstreamQuery = () => new URL(upstream.mock.calls.find((c) => !String(c[0]).endsWith('/auth/token'))![0]).searchParams;

describe('GET /api/runs: who may see what', () => {
  it('needs a session', async () => {
    expect((await get('', null)).status).toBe(401);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('an admin sees everybody, and may ask for one user', async () => {
    const all = await get('?limit=20', 'admin');
    expect(all.status).toBe(200);
    expect(all.json.scope).toBe('everyone');
    expect(upstreamQuery().get('by')).toBeNull();
    expect(upstreamQuery().get('limit')).toBe('20');
    await get('?by=lee%40x.test', 'admin');
    expect(upstream.mock.calls.filter((c) => !String(c[0]).endsWith('/auth/token')).map((c) => new URL(c[0]).searchParams.get('by'))).toEqual([null, 'lee@x.test']);
  });

  it('anybody else only ever sees their own runs, whatever they ask for', async () => {
    const r = await get('?by=boss%40x.test', 'user');
    expect(r.json.scope).toEqual({ email: 'dana@x.test' });
    expect(upstreamQuery().get('by')).toBe('dana@x.test');
    expect(visibleTo(sessions.user, null)).toBe('dana@x.test');
    expect(visibleTo(sessions.admin, null)).toBeNull();
  });

  it('sends the minted token to the upload service and clamps the limit', async () => {
    await get('?limit=9999', 'admin');
    const call = upstream.mock.calls.find((c) => !String(c[0]).endsWith('/auth/token'))!;
    expect((call[1] as RequestInit).headers).toEqual({ Authorization: 'Bearer jwt' });
    expect(upstreamQuery().get('limit')).toBe('100');
  });

  it('says so when the upload service fails, and passes a bad-address 400 through', async () => {
    upstream.mockImplementation(async (url: string) => (url.endsWith('/auth/token') ? new Response(JSON.stringify({ token: 'j' })) : new Response(JSON.stringify({ detail: 'invalid email' }), { status: 400 })));
    expect((await get('?by=x', 'admin')).json.error).toContain('invalid email');
    upstream.mockImplementation(async () => { throw new Error('ECONNREFUSED'); });
    const r = await get('', 'admin');
    expect(r.status).toBe(502);
    expect(r.json.error).toContain('ECONNREFUSED');
  });
});
