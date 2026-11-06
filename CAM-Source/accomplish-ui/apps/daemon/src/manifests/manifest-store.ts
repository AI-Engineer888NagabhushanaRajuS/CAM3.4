/**
 * SPEC-020: read and save one manifest file. Save = conflict check, validate, bump patch, deterministic hash,
 * history copy, audit line, temp file + rename. All fs calls are synchronous on purpose: the check-then-write
 * cannot interleave with another request in this single process (ponytail: a second daemon on the same folder would need a file lock).
 */
import { appendFileSync, copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { canonicalJson, hashText, manifestsDir, type ResolvedPath } from './manifest-paths.js';
import { metaOf, validateManifest, type Doc, type Validation } from './manifest-validate.js';

export const MAX_BYTES = 512 * 1024;
const PLACEHOLDER = 'sha256:COMPUTED_ON_SAVE';

export interface FileView {
  path: string;
  kind: string;
  text: string;
  hash: string;
  deterministicHash: string | null;
  version: string | null;
  status: string | null;
  readOnly: boolean;
  validation: Validation;
}
export interface Reply {
  code: number;
  body: unknown;
}

export const auditFile = (): string => join(process.env.CAM_CHAT_AUDIT_DIR ?? join(homedir(), '.accomplish'), 'manifests-audit.jsonl');

export function readManifest(p: ResolvedPath): FileView | null {
  if (!existsSync(p.abs)) {
    return null;
  }
  const text = readFileSync(p.abs, 'utf8');
  const { doc, validation } = validateManifest(p.kind, text);
  const det = doc?.governance?.deterministic_hash;
  const m = metaOf(doc);
  return { path: p.rel, kind: p.kind, text, hash: hashText(text), deterministicHash: typeof det === 'string' ? det : null, version: m.version, status: m.status, readOnly: p.readOnly, validation };
}

/** Patch +1 from the submitted version, keeping any "-draft" style suffix; versioning.patch follows. */
function bump(doc: Doc): void {
  const meta = doc.agent_metadata ?? doc.skill_metadata;
  const m = /^(\d+)\.(\d+)\.(\d+)(-.*)?$/.exec(meta.version);
  if (!m) {
    return; // the schema has already guaranteed this shape
  }
  const patch = Number(m[3]) + 1;
  meta.version = `${m[1]}.${m[2]}.${patch}${m[4] ?? ''}`;
  meta.updated_at = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  doc.governance.versioning.patch = patch;
}

/** The hash is over the canonical form with the hash field holding the placeholder, so anyone can recompute it. */
export function deterministicHash(doc: Doc): string {
  const saved = doc.governance.deterministic_hash;
  doc.governance.deterministic_hash = PLACEHOLDER;
  const h = hashText(canonicalJson(doc));
  doc.governance.deterministic_hash = saved;
  return h;
}

/** The earlier saved copies of one manifest (SPEC-022): `.history/<name>.<stamp>.json`, newest first. File names are built here from the
 * validated manifest path and a strict stamp pattern: no client-supplied path ever reaches the file system. */
const STAMP = /^\d{8}T\d{9}Z$/;
const HISTORY_LIMIT = 30;
const escapeRegExp = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const stampToIso = (s: string): string => `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(9, 11)}:${s.slice(11, 13)}:${s.slice(13, 15)}.${s.slice(15, 18)}Z`;

export function listHistory(p: ResolvedPath): Array<{ stamp: string; savedAt: string }> {
  const dir = join(manifestsDir(), '.history');
  if (!existsSync(dir)) {
    return [];
  }
  const own = new RegExp('^' + escapeRegExp(basename(p.abs, '.json')) + '\\.(\\d{8}T\\d{9}Z)\\.json$');
  return readdirSync(dir)
    .map((f) => own.exec(f)?.[1])
    .filter((s): s is string => !!s)
    .sort()
    .reverse()
    .slice(0, HISTORY_LIMIT)
    .map((stamp) => ({ stamp, savedAt: stampToIso(stamp) }));
}

export function readHistory(p: ResolvedPath, stamp: unknown): { stamp: string; savedAt: string; text: string; hash: string; version: string | null } | null {
  if (typeof stamp !== 'string' || !STAMP.test(stamp) || !listHistory(p).some((h) => h.stamp === stamp)) {
    return null;
  }
  const text = readFileSync(join(manifestsDir(), '.history', `${basename(p.abs, '.json')}.${stamp}.json`), 'utf8');
  const { doc } = validateManifest(p.kind, text);
  return { stamp, savedAt: stampToIso(stamp), text, hash: hashText(text), version: metaOf(doc).version };
}

export function saveManifest(p: ResolvedPath, text: string, baseHash: unknown, who: string): Reply {
  if (Buffer.byteLength(text, 'utf8') > MAX_BYTES) {
    return { code: 413, body: { error: `Manifest is larger than ${MAX_BYTES / 1024} KB` } };
  }
  if (!existsSync(p.abs)) {
    return { code: 404, body: { error: 'No such manifest (this API edits existing files only)' } };
  }
  const oldHash = hashText(readFileSync(p.abs, 'utf8'));
  if (baseHash !== oldHash) {
    return { code: 409, body: { error: 'The file changed since you opened it', currentHash: oldHash } };
  }
  const { doc, validation } = validateManifest(p.kind, text);
  if (!doc || !validation.ok) {
    return { code: 400, body: { validation } };
  }
  bump(doc);
  doc.governance.deterministic_hash = deterministicHash(doc);
  const saved = JSON.stringify(doc, null, 2) + '\n';
  const newHash = hashText(saved);

  const root = manifestsDir();
  const stamp = new Date().toISOString().replace(/[-:.]/g, ''); // no colons: illegal in Windows file names
  mkdirSync(join(root, '.history'), { recursive: true });
  copyFileSync(p.abs, join(root, '.history', `${basename(p.abs, '.json')}.${stamp}.json`));
  // The temp name does not end in .json, so a crash never leaves a loadable stray manifest.
  const tmp = join(dirname(p.abs), `.${basename(p.abs)}.tmp-${process.pid}`);
  try {
    writeFileSync(tmp, saved, 'utf8');
    // The audit line comes before the commit: if it cannot be written, nothing is saved.
    mkdirSync(dirname(auditFile()), { recursive: true });
    appendFileSync(auditFile(), JSON.stringify({ who, at: new Date().toISOString(), action: 'manifest.save', path: p.rel, oldHash, newHash }) + '\n');
    renameSync(tmp, p.abs);
  } catch (e) {
    if (existsSync(tmp)) {
      unlinkSync(tmp);
    }
    throw e;
  }
  const m = metaOf(doc);
  return { code: 200, body: { path: p.rel, text: saved, hash: newHash, deterministicHash: doc.governance.deterministic_hash, version: m.version, status: m.status, validation } };
}
