/** SPEC-020: the agent > skill > sub-skill tree the left pane is built from, read straight from manifests/ (never executed). */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { RUNTIME, hashText, manifestsDir } from './manifest-paths.js';
import { metaOf, type Doc } from './manifest-validate.js';
import { UI_ACTIONS } from './manifest-schemas.js';

interface Loaded {
  path: string;
  doc: Doc | null;
  hash: string;
  exists: boolean;
}

function load(root: string, rel: string): Loaded {
  const abs = join(root, rel);
  if (!existsSync(abs)) {
    return { path: rel, doc: null, hash: '', exists: false };
  }
  const text = readFileSync(abs, 'utf8');
  try {
    const doc: unknown = JSON.parse(text);
    return { path: rel, doc: doc && typeof doc === 'object' && !Array.isArray(doc) ? (doc as Doc) : null, hash: hashText(text), exists: true };
  } catch {
    return { path: rel, doc: null, hash: hashText(text), exists: true };
  }
}

const jsonFiles = (dir: string, only: RegExp = /\.json$/): string[] => (existsSync(dir) ? readdirSync(dir).filter((f) => only.test(f)).sort() : []);
const objects = (v: unknown): Doc[] => (Array.isArray(v) ? v.filter((x): x is Doc => !!x && typeof x === 'object') : []);

/** The flag is off only when it is exactly `false`: a file that never had one stays on. */
const on = (v: unknown): boolean => v !== false;

function skillNode(root: string, entry: Doc) {
  // manifest_file is untrusted data: only its file name is used, and only under skills/.
  const file = String(entry.manifest_file ?? '').replace(/\\/g, '/').split('/').pop() ?? '';
  const path = `skills/${file}`;
  const l = /^[A-Za-z0-9._-]+\.json$/.test(file) ? load(root, path) : null;
  const base = { path, id: String(entry.skill_id ?? ''), name: String(entry.name ?? ''), sequence: Number(entry.sequence), enabled: on(entry.enabled) };
  if (!l?.exists) {
    return { ...base, missing: true, subSkills: [] };
  }
  if (!l.doc) {
    return { ...base, invalid: true, hash: l.hash, subSkills: [] };
  }
  const m = metaOf(l.doc);
  const subSkills = objects(l.doc.sub_skills).map((s) => ({ id: String(s.sub_skill_id ?? ''), name: String(s.sub_skill_name ?? ''), type: String(s.type ?? ''), stepCount: Array.isArray(s.steps) ? s.steps.length : 0, humanSteps: Array.isArray(s.steps) ? s.steps.filter((x: { mode?: unknown }) => x?.mode === 'Human').length : 0, enabled: on(s.enabled) }));
  // SPEC-023: `enabled: false` in the agent's skill_sequence entry or in the skill's own skill_metadata switches the skill off in the left pane.
  // SPEC-025: `ui_actions` lists the pane's buttons for this stage; an absent list leaves the pane's built-in buttons, an unknown action is dropped.
  const uiActions = Array.isArray(l.doc.ui_actions) ? objects(l.doc.ui_actions).filter((a) => typeof a.label === 'string' && UI_ACTIONS.includes(String(a.action))).map((a) => ({ label: String(a.label), action: String(a.action) })) : undefined;
  return { path, id: m.id ?? base.id, name: m.name ?? base.name, sequence: base.sequence, version: m.version, status: m.status, hash: l.hash, subSkills, uiActions, enabled: base.enabled && on(l.doc.skill_metadata?.enabled) };
}

export function buildTree() {
  const root = manifestsDir();
  const first = (dir: string) => jsonFiles(join(root, dir))[0];

  const agentFile = first('agent');
  const a = agentFile ? load(root, `agent/${agentFile}`) : null;
  let agent = null;
  if (a?.doc) {
    const m = metaOf(a.doc);
    const skills = objects(a.doc.skill_sequence).map((e) => skillNode(root, e)).sort((x, y) => x.sequence - y.sequence);
    agent = { path: a.path, id: m.id, name: m.name, version: m.version, status: m.status, hash: a.hash, skills };
  }

  const repFile = first('reporting');
  const r = repFile ? load(root, `reporting/${repFile}`) : null;
  let reporting = null;
  if (r?.doc) {
    const m = metaOf(r.doc);
    reporting = { path: r.path, id: m.id, name: m.name, version: m.version, status: m.status, hash: r.hash, reportCount: Array.isArray(r.doc.reports) ? r.doc.reports.length : 0 };
  }

  const approved = jsonFiles(join(root, 'repo-approved')).map((f) => {
    const l = load(root, `repo-approved/${f}`);
    const m = metaOf(l.doc);
    return { path: l.path, id: m.id, name: m.name, version: m.version, status: m.status, active: m.status === 'APPROVED' };
  });

  const runtime = jsonFiles(root, RUNTIME).map((f) => {
    const doc = load(root, f).doc;
    const m = metaOf(doc);
    const port = doc?.port;
    return { path: f, id: m.id ?? f.replace(/\.json$/, ''), name: m.name, version: m.version, port: typeof port === 'number' ? port : null, readOnly: true as const };
  });

  return { agent, reporting, approved, runtime };
}
