import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import http from 'node:http';
import { cpSync, existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { handleManifestRoute, type ManifestSession } from '../src/manifests/manifest-routes.js';
import { canonicalJson, hashText } from '../src/manifests/manifest-paths.js';
import { deterministicHash } from '../src/manifests/manifest-store.js';

// The real copied design manifests; only ever READ. Every write test works on a temp copy.
const REAL = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../manifests');
const SKILL = 'skills/skill_01_input_standardization.json';

let server: http.Server;
let base = '';
let work = '';
let audit = '';
const sessions: Record<string, ManifestSession> = { admin: { email: 'a@x.test', role: 'admin' }, user: { email: 'u@x.test', role: 'user' } };

async function call(method: string, path: string, opts: { as?: string | null; body?: unknown; raw?: string } = {}) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (opts.as !== null) {
    headers['x-test-user'] = opts.as ?? 'admin';
  }
  const res = await fetch(base + path, { method, headers, body: opts.raw ?? (opts.body === undefined ? undefined : JSON.stringify(opts.body)) });
  return { status: res.status, json: (await res.json()) as any }; // eslint-disable-line @typescript-eslint/no-explicit-any
}
const getFile = (path: string) => call('GET', `/api/manifests/file?path=${encodeURIComponent(path)}`);
const put = (path: string, text: string, baseHash: string, as?: string) => call('PUT', '/api/manifests/file', { as, body: { path, text, baseHash } });

beforeAll(async () => {
  server = http.createServer((req, res) => {
    const who = req.headers['x-test-user'];
    const session = typeof who === 'string' ? sessions[who] ?? null : null;
    if (!handleManifestRoute(req, res, session)) {
      res.writeHead(404).end();
    }
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
});
afterAll(() => {
  server.close();
});
beforeEach(() => {
  work = mkdtempSync(join(tmpdir(), 'manifests-'));
  cpSync(REAL, work, { recursive: true });
  rmSync(join(work, '.history'), { recursive: true, force: true }); // the real folder keeps copies of live saves; every test starts with none
  audit = mkdtempSync(join(tmpdir(), 'manifests-audit-'));
  process.env.CAM_MANIFESTS_DIR = work;
  process.env.CAM_CHAT_AUDIT_DIR = audit;
  return undefined; // vitest 4: never hand back a value from beforeEach
});

describe('manifests tree and schema (real copied files)', () => {
  it('lists 1 agent, 10 skills, 40 sub-skills, 16 reports, 10 approved, 6 runtime read-only', async () => {
    process.env.CAM_MANIFESTS_DIR = REAL;
    const { status, json } = await call('GET', '/api/manifests');
    const t = json.tree;
    expect(status).toBe(200);
    expect(t.agent.skills).toHaveLength(10);
    expect(t.agent.skills.map((s: { sequence: number }) => s.sequence)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(t.agent.skills.every((s: { missing?: boolean }) => !s.missing)).toBe(true);
    expect(t.agent.skills.flatMap((s: { subSkills: unknown[] }) => s.subSkills)).toHaveLength(40);
    expect(t.agent.skills[0].subSkills[0]).toMatchObject({ id: '1.1', stepCount: 5 });
    expect(t.reporting.reportCount).toBe(16);
    expect(t.approved).toHaveLength(10);
    expect(t.approved.filter((a: { active: boolean }) => !a.active)).toHaveLength(2);
    expect(t.runtime).toHaveLength(6);
    expect(t.runtime.every((r: { readOnly: boolean; port: number }) => r.readOnly && r.port > 0)).toBe(true);
  });

  it('SPEC-023: every skill and sub-skill is on when no flag is set; the schema documents the flag', async () => {
    process.env.CAM_MANIFESTS_DIR = REAL;
    const { json } = await call('GET', '/api/manifests');
    expect(json.tree.agent.skills.every((s: { enabled: boolean }) => s.enabled === true)).toBe(true);
    expect(json.tree.agent.skills.flatMap((s: { subSkills: Array<{ enabled: boolean }> }) => s.subSkills).every((s: { enabled: boolean }) => s.enabled === true)).toBe(true);
    const schema = (await call('GET', '/api/manifests/schema/skill')).json;
    expect(schema.properties.skill_metadata.properties.enabled).toMatchObject({ type: 'boolean' });
  });

  it('SPEC-023: "enabled": false saved in the skill file (DRAFT, through the real save route) switches that skill / sub-skill off in the tree', async () => {
    const f = (await getFile(SKILL)).json;
    const doc = JSON.parse(f.text);
    doc.skill_metadata.enabled = false;
    doc.sub_skills[1].enabled = false;
    const res = await put(SKILL, JSON.stringify(doc), f.hash);
    expect(res.status).toBe(200); // a DRAFT manifest with the flag is accepted and saved
    const { json } = await call('GET', '/api/manifests');
    const s1 = json.tree.agent.skills[0];
    expect(s1.enabled).toBe(false);
    expect(s1.subSkills[1].enabled).toBe(false);
    expect(s1.subSkills[0].enabled).toBe(true);
    expect(json.tree.agent.skills[1].enabled).toBe(true);
  });

  it('SPEC-023: "enabled": false on the agent skill_sequence entry switches the skill off too', async () => {
    const agentPath = 'agent/agent_manifest.json';
    const f = (await getFile(agentPath)).json;
    const doc = JSON.parse(f.text);
    doc.skill_sequence[2].enabled = false;
    expect((await put(agentPath, JSON.stringify(doc), f.hash)).status).toBe(200);
    const { json } = await call('GET', '/api/manifests');
    expect(json.tree.agent.skills.map((s: { enabled: boolean }) => s.enabled)).toEqual([true, true, false, true, true, true, true, true, true, true]);
  });

  it('reports a missing skill file as missing:true instead of crashing', async () => {
    rmSync(join(work, SKILL));
    const { json } = await call('GET', '/api/manifests');
    expect(json.tree.agent.skills[0]).toMatchObject({ missing: true, sequence: 1, subSkills: [] });
    expect(json.tree.agent.skills[1].missing).toBeUndefined();
  });

  it('serves a draft-07 schema per kind and 404 for another kind', async () => {
    for (const kind of ['agent', 'skill', 'reporting', 'approved']) {
      const { status, json } = await call('GET', `/api/manifests/schema/${kind}`);
      expect(status).toBe(200);
      expect(json.$schema).toContain('draft-07');
      expect(json.required).toContain('governance');
    }
    expect((await call('GET', '/api/manifests/schema/runtime')).status).toBe(404);
  });

  it('every real design file validates under its own kind', async () => {
    const files = ['agent/agent_manifest.json', 'reporting/cam_isatvon_manifest.json']
      .concat(readdirSync(join(REAL, 'skills')).map((f) => `skills/${f}`), readdirSync(join(REAL, 'repo-approved')).map((f) => `repo-approved/${f}`));
    expect(files).toHaveLength(22);
    for (const f of files) {
      const { json } = await getFile(f);
      expect(json.validation.errors, f).toEqual([]);
      expect(json.validation.ok, f).toBe(true);
    }
  });

  it('GET file: runtime is read-only, unknown path 403, missing file 404, no session 401', async () => {
    const rt = await getFile('centum_intake.json');
    expect(rt.json).toMatchObject({ kind: 'runtime', readOnly: true });
    expect((await getFile('../package.json')).status).toBe(403);
    expect((await getFile('skills/nope.json')).status).toBe(404);
    expect((await call('GET', '/api/manifests', { as: null })).status).toBe(401);
  });
});

describe('manifest save', () => {
  it('shows validation errors with paths', async () => {
    const f = (await getFile(SKILL)).json;
    const doc = JSON.parse(f.text);
    delete doc.isatvon_definition.i_instructions;
    doc.skill_metadata.status = 'WHATEVER';
    doc.sub_skills[0].steps[0].mode = 'Robot';
    const res = await put(SKILL, JSON.stringify(doc), f.hash);
    expect(res.status).toBe(400);
    const errs = res.json.validation.errors as { path: string; message: string }[];
    expect(errs.find((e) => e.path === '/isatvon_definition')?.message).toContain('i_instructions');
    expect(errs.find((e) => e.path === '/skill_metadata/status')?.message).toContain('DRAFT');
    expect(errs.find((e) => e.path === '/sub_skills/0/steps/0/mode')).toBeTruthy();
  });

  it('saves: bumps the patch (keeps -draft), real hash replaces the placeholder, hash equals the recomputation', async () => {
    const f = (await getFile(SKILL)).json;
    expect(f.deterministicHash).toBe('sha256:COMPUTED_ON_SAVE');
    const doc = JSON.parse(f.text);
    doc.isatvon_definition.v_variables.max_iterations = 4;
    const res = await put(SKILL, JSON.stringify(doc), f.hash);
    expect(res.status).toBe(200);
    const saved = JSON.parse(res.json.text);
    expect(res.json.version).toBe('1.5.1-draft');
    expect(saved.skill_metadata.version).toBe('1.5.1-draft');
    expect(saved.governance.versioning.patch).toBe(1);
    expect(saved.skill_metadata.updated_at).not.toBe('2026-10-27T00:00:00Z');
    expect(saved.governance.deterministic_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(saved.isatvon_definition.v_variables.max_iterations).toBe(4);
    // recomputation, and independence from key order
    expect(deterministicHash(saved)).toBe(saved.governance.deterministic_hash);
    const reordered = Object.fromEntries(Object.entries(saved).reverse());
    expect(hashText(canonicalJson({ ...reordered, governance: { ...saved.governance, deterministic_hash: 'sha256:COMPUTED_ON_SAVE' } }))).toBe(saved.governance.deterministic_hash);
    // the returned text is the file as saved, and its hash is the new baseHash
    expect(readFileSync(join(work, SKILL), 'utf8')).toBe(res.json.text);
    expect(res.json.hash).toBe(hashText(res.json.text));
    expect((await getFile(SKILL)).json.hash).toBe(res.json.hash);
  });

  it('copies the previous file to .history and appends an audit line', async () => {
    const f = (await getFile(SKILL)).json;
    const res = await put(SKILL, f.text, f.hash);
    const hist = readdirSync(join(work, '.history'));
    expect(hist).toHaveLength(1);
    expect(hist[0]).toMatch(/^skill_01_input_standardization\.\d{8}T\d{9}Z\.json$/);
    expect(readFileSync(join(work, '.history', hist[0]), 'utf8')).toBe(f.text);
    const line = JSON.parse(readFileSync(join(audit, 'manifests-audit.jsonl'), 'utf8').trim());
    expect(line).toMatchObject({ who: 'a@x.test', action: 'manifest.save', path: SKILL, oldHash: f.hash, newHash: res.json.hash });
    expect(Date.parse(line.at)).not.toBeNaN();
  });

  it('returns 409 with currentHash for a stale baseHash and writes nothing', async () => {
    const f = (await getFile(SKILL)).json;
    expect((await put(SKILL, f.text, f.hash)).status).toBe(200);
    const stale = await put(SKILL, f.text, f.hash);
    expect(stale.status).toBe(409);
    expect(stale.json.currentHash).toBe((await getFile(SKILL)).json.hash);
    expect(readdirSync(join(work, '.history'))).toHaveLength(1);
  });

  it('refuses invalid JSON and schema errors with nothing written', async () => {
    const before = readFileSync(join(work, SKILL), 'utf8');
    const hash = hashText(before);
    const bad = await put(SKILL, '{ "skill_metadata": ', hash);
    expect(bad.status).toBe(400);
    expect(bad.json.validation.errors[0].message).toContain('Invalid JSON');
    expect((await put(SKILL, '{}', hash)).status).toBe(400);
    expect(readFileSync(join(work, SKILL), 'utf8')).toBe(before);
    expect(existsSync(join(work, '.history'))).toBe(false);
    expect(existsSync(join(audit, 'manifests-audit.jsonl'))).toBe(false);
    expect(readdirSync(join(work, 'skills')).filter((n) => n.includes('.tmp'))).toEqual([]);
  });

  it('refuses traversal, absolute, outside, nested and runtime paths with 403', async () => {
    const text = '{}';
    const paths = ['../package.json', 'skills/../centum_intake.json', '/etc/passwd', 'C:/Windows/win.ini', 'C:\\x.json', 'skills\\..\\..\\x.json', 'other/x.json', 'skills/sub/x.json', '.history/x.json', 'skills/x.json:stream', 'centum_intake.json', 'README.md', 'skills/skill_01_input_standardization.txt', ''];
    for (const p of paths) {
      expect((await put(p, text, 'x')).status, p).toBe(403);
    }
    expect((await call('PUT', '/api/manifests/file', { body: { text, baseHash: 'x' } })).status).toBe(403);
    const runtimeBefore = readFileSync(join(work, 'centum_intake.json'), 'utf8');
    expect(readFileSync(join(work, 'centum_intake.json'), 'utf8')).toBe(runtimeBefore);
  });

  it('refuses oversize text (413), non-admin (403), no session (401), missing file (404)', async () => {
    const f = (await getFile(SKILL)).json;
    const big = JSON.stringify({ pad: 'x'.repeat(513 * 1024) });
    expect((await put(SKILL, big, f.hash)).status).toBe(413);
    expect((await call('PUT', '/api/manifests/file', { raw: 'y'.repeat(2 * 1024 * 1024) })).status).toBe(413);
    expect((await put(SKILL, f.text, f.hash, 'user')).status).toBe(403);
    expect((await call('PUT', '/api/manifests/file', { as: null, body: {} })).status).toBe(401);
    writeFileSync(join(work, 'skills', 'keep.json'), '{}');
    expect((await put('skills/missing.json', f.text, f.hash)).status).toBe(404);
    expect(existsSync(join(work, 'skills', 'missing.json'))).toBe(false);
    expect(readFileSync(join(work, SKILL), 'utf8')).toBe(f.text);
  });
});

describe('SPEC-022 history of earlier saved versions', () => {
  const hist = (path: string) => call('GET', `/api/manifests/history?path=${encodeURIComponent(path)}`);
  const histFile = (path: string, stamp: string) => call('GET', `/api/manifests/history/file?path=${encodeURIComponent(path)}&stamp=${encodeURIComponent(stamp)}`);

  it('is empty before any save; after two saves lists both, newest first, and returns the exact earlier bytes', async () => {
    expect((await hist(SKILL)).json).toEqual({ path: SKILL, versions: [] });
    const original = readFileSync(join(work, SKILL), 'utf8');
    const f1 = (await getFile(SKILL)).json;
    const s1 = (await put(SKILL, f1.text.replace('Input Standardization', 'Input Standardization A'), f1.hash)).json;
    await new Promise((r) => setTimeout(r, 15)); // the stamp has millisecond resolution
    await put(SKILL, s1.text.replace('Input Standardization A', 'Input Standardization AB'), s1.hash);
    const list = (await hist(SKILL)).json.versions as Array<{ stamp: string; savedAt: string }>;
    expect(list).toHaveLength(2);
    expect(list[0].stamp > list[1].stamp).toBe(true);
    expect(list[0].savedAt).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
    const oldest = (await histFile(SKILL, list[1].stamp)).json;
    expect(oldest.text).toBe(original); // the history copy is the file as it was before the first save
    expect(oldest.hash).toBe(hashText(original));
    expect((await histFile(SKILL, list[0].stamp)).json.text).toBe(s1.text);
  });

  it('builds the file name itself: only a listed stamp of this manifest is readable, nothing else is', async () => {
    const f = (await getFile(SKILL)).json;
    await put(SKILL, f.text.replace('Input Standardization', 'Input Standardization A'), f.hash);
    const [{ stamp }] = (await hist(SKILL)).json.versions;
    for (const bad of ['../../secret', `${stamp}.json`, '20260101T000000000Z', '', 'x'.repeat(200), `${stamp}/../..`]) {
      expect((await histFile(SKILL, bad)).status).toBe(404);
    }
    // another manifest's saved copy is not reachable through this manifest's path
    expect((await histFile('skills/skill_02_feature_extraction.json', stamp)).status).toBe(404);
    expect((await hist('../etc/passwd')).status).toBe(403);
    expect((await hist('skills/.history/x.json')).status).toBe(403);
    expect((await call('GET', `/api/manifests/history?path=${encodeURIComponent(SKILL)}`, { as: null })).status).toBe(401);
  });
});
