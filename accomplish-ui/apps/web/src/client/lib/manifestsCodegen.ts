/** Bridge preview calls (SPEC-020): lint and code generation for a manifest text. Nothing is executed or written. */
import { PYTHON_BRIDGE_URL } from '../config/endpoints';
import { authFetch } from './apiAuth';
import type { ManifestKind } from './manifestsApi';

export const MANIFESTS_SCOPE = 'MANIFESTS';

export interface LintFinding { level: 'error' | 'warning'; path: string; message: string }
export interface Lint { ok: boolean; findings: LintFinding[] }
export interface Codegen {
  ok: boolean; files: Record<string, string>; bundle_sha256: string; findings: LintFinding[];
  repairs: unknown[]; ast: { ok: boolean; errors: { line: number; message: string }[] };
}

/** Thrown for a 400: the text is not valid JSON. Shown calmly, not as an error. */
export class InvalidJsonError extends Error {}

async function post<T>(path: string, body: unknown, signal: AbortSignal): Promise<T> {
  const res = await authFetch(`${PYTHON_BRIDGE_URL}${path}`, MANIFESTS_SCOPE, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
  if (res.status === 400) {
    const b = (await res.json().catch(() => ({}))) as { detail?: unknown };
    throw new InvalidJsonError(typeof b.detail === 'string' ? b.detail : 'The text is not valid JSON.');
  }
  if (!res.ok) throw new Error(`The preview service answered HTTP ${res.status}.`);
  return (await res.json()) as T;
}

export const lintManifest = (text: string, kind: ManifestKind, signal: AbortSignal) => post<Lint>('/api/manifests/lint', { kind, text }, signal);
export const generateTool = (text: string, subSkillId: string | undefined, signal: AbortSignal) =>
  post<Codegen>('/api/manifests/codegen', { text, ...(subSkillId ? { sub_skill_id: subSkillId } : {}) }, signal);

/** A self-heal repair in words; the bridge sends strings or small objects. */
export function describeRepair(r: unknown): string {
  if (typeof r === 'string') return r;
  if (r && typeof r === 'object') {
    const o = r as Record<string, unknown>;
    const text = o.message ?? o.description ?? o.detail;
    const where = o.path ?? o.field;
    if (typeof text === 'string') return where ? `${String(where)}: ${text}` : text;
    return Object.entries(o).map(([k, v]) => `${k} ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ');
  }
  return String(r);
}
