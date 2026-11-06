/**
 * SPEC-020: where the design manifests live and which paths the API may touch.
 * Manifest files are DATA: nothing here executes them.
 */
import { createHash } from 'node:crypto';
import { existsSync, realpathSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';

export type ManifestKind = 'agent' | 'skill' | 'reporting' | 'approved' | 'runtime';

/** Read on every call (not at import) so tests and operators can point it elsewhere. */
export const manifestsDir = (): string => process.env.CAM_MANIFESTS_DIR ?? resolve(process.cwd(), '../../../manifests');

const FOLDER_KIND: Record<string, ManifestKind> = { agent: 'agent', skills: 'skill', reporting: 'reporting', 'repo-approved': 'approved' };
/** One strict shape for every path: no `..`, no absolute path, no drive letter or `:` stream, no nesting, no `.history`. */
const EDITABLE = /^(agent|skills|reporting|repo-approved)\/[A-Za-z0-9._-]+\.json$/;
/** The six live routing manifests (SPEC-013, owned by scripts/import_manifest.py): readable, never writable here. */
export const RUNTIME = /^centum_[a-z0-9_]+\.json$/;

export interface ResolvedPath {
  rel: string;
  abs: string;
  kind: ManifestKind;
  readOnly: boolean;
}

/** Null means "refuse with 403". Does not check that the file exists. */
export function resolveManifestPath(input: unknown): ResolvedPath | null {
  if (typeof input !== 'string' || input.length === 0 || input.length > 300 || input.includes('\0')) {
    return null;
  }
  const rel = input.replaceAll('\\', '/');
  const folder = EDITABLE.exec(rel)?.[1];
  let kind: ManifestKind | undefined = folder ? FOLDER_KIND[folder] : undefined;
  if (!kind && RUNTIME.test(rel)) {
    kind = 'runtime';
  }
  if (!kind) {
    return null;
  }
  const root = manifestsDir();
  const abs = join(root, rel);
  // A symlink inside manifests/ must not lead outside it.
  if (existsSync(abs) && !realpathSync(abs).startsWith(realpathSync(root) + sep)) {
    return null;
  }
  return { rel, abs, kind, readOnly: kind === 'runtime' };
}

export const hashText = (text: string): string => 'sha256:' + createHash('sha256').update(text, 'utf8').digest('hex');

/** Sorted keys at every depth. Object.fromEntries (not assignment) so a "__proto__" key stays plain data. */
function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) {
    return v.map(sortKeys);
  }
  if (v && typeof v === 'object') {
    return Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, x]) => [k, sortKeys(x)]));
  }
  return v;
}

export const canonicalJson = (doc: unknown): string => JSON.stringify(sortKeys(doc), null, 2);
