import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import http from 'node:http';
import { cpSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { applySkillEnabled, realignInFlight, syncManifestFromTool, type Db } from '../src/manifests/manifest-runtime.js';
import { handleManifestRoute } from '../src/manifests/manifest-routes.js';
import { hashText } from '../src/manifests/manifest-paths.js';

const REAL = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../manifests');
const PRICING = 'skills/skill_04_distributor_selection.json';

/** An in-memory stand-in for the three tables the runtime touches; it answers exactly the statements manifest-runtime.ts sends. */
function fakeDb() {
  const registry = [
    { mcp_tool_name: 'intake__a', skill_index: 1, macro_category: 1 },
    { mcp_tool_name: 'gerber__x', skill_index: 2, macro_category: 2 },
    { mcp_tool_name: 'price__a', skill_index: 3, macro_category: 3 },
    { mcp_tool_name: 'price__b', skill_index: 4, macro_category: 3 },
  ];
  const profiles: Record<string, string[]> = { Standard_BOM_Flow: ['intake__a', 'price__a', 'price__b'], RFQ_Flow: ['intake__a', 'gerber__x', 'price__a'] };
  const memory = new Map<string, string[]>();
  const db: Db = {
    async query(sql, params = []) {
      if (sql.startsWith('SELECT mcp_tool_name')) { return { rows: registry }; }
      if (sql.startsWith('CREATE TABLE')) { return { rows: [] }; }
      if (sql.startsWith('SELECT profile_name')) { return { rows: Object.entries(profiles).map(([profile_name, routing_sequence]) => ({ profile_name, routing_sequence })) }; }
      if (sql.startsWith('SELECT tool_name')) { return { rows: [...memory].map(([tool_name, p]) => ({ tool_name, profiles: p })) }; }
      if (sql.startsWith('SELECT DISTINCT tool')) { return { rows: [...new Set(Object.values(profiles).flat())].map((tool) => ({ tool })) }; }
      if (sql.startsWith('UPDATE quote_routing_profiles')) { profiles[params[1] as string] = JSON.parse(params[0] as string); return { rows: [] }; }
      if (sql.startsWith('DELETE FROM')) { memory.delete(params[0] as string); return { rows: [] }; }
      if (sql.startsWith('INSERT INTO')) { memory.set(params[0] as string, JSON.parse(params[1] as string)); return { rows: [] }; }
      throw new Error('unexpected SQL: ' + sql);
    },
  };
  return { db, profiles };
}

let work = '';
beforeEach(() => {
  work = mkdtempSync(join(tmpdir(), 'cam-runtime-'));
  cpSync(REAL, work, { recursive: true });
  process.env.CAM_MANIFESTS_DIR = work;
  process.env.CAM_CHAT_AUDIT_DIR = work;
});
afterEach(() => rmSync(work, { recursive: true, force: true }));

describe('SPEC-025: a skill flag really switches its pipeline tools', () => {
  it('off removes the skill\'s tools from every profile, on puts them back in the same profiles and canonical order', async () => {
    const { db, profiles } = fakeDb();
    expect(await applySkillEnabled(db, 'SKILL_04', false)).toEqual(['price__a', 'price__b']);
    expect(profiles).toEqual({ Standard_BOM_Flow: ['intake__a'], RFQ_Flow: ['intake__a', 'gerber__x'] });
    await applySkillEnabled(db, 'SKILL_04', true);
    expect(profiles).toEqual({ Standard_BOM_Flow: ['intake__a', 'price__a', 'price__b'], RFQ_Flow: ['intake__a', 'gerber__x', 'price__a'] });
  });

  it('a tool of another profile is not dragged into Standard_BOM_Flow when its skill is switched on again', async () => {
    const { db, profiles } = fakeDb();
    await applySkillEnabled(db, 'SKILL_02', false);
    expect(profiles.RFQ_Flow).toEqual(['intake__a', 'price__a']);
    await applySkillEnabled(db, 'SKILL_02', true);
    expect(profiles.Standard_BOM_Flow).toEqual(['intake__a', 'price__a', 'price__b']);
    expect(profiles.RFQ_Flow).toEqual(['intake__a', 'gerber__x', 'price__a']);
  });

  it('an RFQ already part-way keeps its place when a step is switched on or off in the middle of its sequence', async () => {
    const stages: Record<string, number> = { fresh: 0, early: 1, paused: 2, finished: 3 };
    const meta: Db = {
      async query(sql, params = []) {
        if (sql.startsWith('SELECT rfq_id')) { return { rows: Object.entries(stages).filter(([, v]) => v > 0).map(([rfq_id, rfq_process_stage]) => ({ rfq_id, rfq_process_stage })) }; }
        stages[params[1] as string] = params[0] as number;
        return { rows: [] };
      },
    };
    const logic: Db = { query: async () => ({ rows: [] }) }; // no RFQ_Flow profile
    // 'risk' is inserted after b: an RFQ that has done a and b runs it next, one that has done c as well skips it and keeps its place after c
    expect(await realignInFlight(logic, meta, ['a', 'b', 'c'], ['a', 'b', 'risk', 'c'])).toBe(1);
    expect(stages).toEqual({ fresh: 0, early: 1, paused: 2, finished: 4 });
    // switched off again: back to where they were
    await realignInFlight(logic, meta, ['a', 'b', 'risk', 'c'], ['a', 'b', 'c']);
    expect(stages).toEqual({ fresh: 0, early: 1, paused: 2, finished: 3 });
  });

  it('a skill with no tool (SKILL_05) is display only', async () => {
    const { db, profiles } = fakeDb();
    expect(await applySkillEnabled(db, 'SKILL_05', false)).toEqual([]);
    expect(profiles.Standard_BOM_Flow).toHaveLength(3);
  });

  it('saving a manifest with enabled:false calls the runtime for exactly that skill, and an unchanged save does not', async () => {
    const calls: Array<[string, boolean]> = [];
    const server = http.createServer((req, res) => {
      handleManifestRoute(req, res, { email: 'a@x.test', role: 'admin' }, async (id, on) => { calls.push([id, on]); return ['t']; });
    });
    await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
    const base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
    const put = async (text: string, baseHash: string) => (await fetch(base + '/api/manifests/file', { method: 'PUT', body: JSON.stringify({ path: PRICING, text, baseHash }) })).json() as Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    try {
      const abs = join(work, PRICING);
      const doc = JSON.parse(readFileSync(abs, 'utf8'));
      const same = await put(JSON.stringify(doc), hashText(readFileSync(abs, 'utf8')));
      expect(same.runtime.applied).toEqual({});
      doc.skill_metadata.enabled = false;
      const off = await put(JSON.stringify(doc), hashText(readFileSync(abs, 'utf8')));
      expect(off.runtime).toEqual({ applied: { SKILL_04: ['t'] }, errors: [] });
      expect(calls).toEqual([['SKILL_04', false]]);
    } finally {
      server.close();
    }
  });

  it('the Settings toggle is mirrored into the manifest: all tools off writes enabled:false, one back on removes it', async () => {
    const { db, profiles } = fakeDb();
    profiles.Standard_BOM_Flow = ['intake__a'];
    profiles.RFQ_Flow = ['intake__a', 'gerber__x'];
    expect(await syncManifestFromTool(db, 'price__a', 'settings-toggle')).toBe('SKILL_04');
    expect(JSON.parse(readFileSync(join(work, PRICING), 'utf8')).skill_metadata.enabled).toBe(false);
    profiles.Standard_BOM_Flow.push('price__b');
    expect(await syncManifestFromTool(db, 'price__b', 'settings-toggle')).toBe('SKILL_04');
    expect(JSON.parse(readFileSync(join(work, PRICING), 'utf8')).skill_metadata.enabled).toBeUndefined();
    expect(await syncManifestFromTool(db, 'price__b', 'settings-toggle')).toBeNull();
  });
});
