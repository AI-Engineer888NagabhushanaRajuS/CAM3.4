/** Client for the daemon manifest API (SPEC-020). Every call carries the session token like the assistant chat does. */
import { backendUrl } from '@/config/endpoints';
import { clearSession, getSessionToken } from '@/lib/session';

export type ManifestKind = 'agent' | 'skill' | 'reporting' | 'approved';

export interface SubSkill { id: string; name: string; type: string; stepCount: number; /** Steps the manifest marks Human: a sub-skill with one shows the person icon, otherwise the agent's. */ humanSteps?: number; /** false = switched off in the manifest (SPEC-023); absent on an older daemon. */ enabled?: boolean }
export interface SkillNode {
  path: string; id: string; name: string; sequence: number; version: string; status: string; hash: string;
  missing?: boolean; subSkills: SubSkill[]; /** SPEC-025: the pane's buttons for this stage; absent = the built-in ones. */ uiActions?: Array<{ label: string; action: string }>; /** false = switched off in the manifest: the left pane disables the stage. */ enabled?: boolean;
}
export interface AgentNode { path: string; id: string; name: string; version: string; status: string; hash: string; skills: SkillNode[] }
export interface ReportingNode { path: string; id: string; name: string; version: string; status: string; hash: string; reportCount: number }
export interface ApprovedNode { path: string; id: string; name: string; version: string; active: boolean }
export interface RuntimeNode { path: string; id: string; name: string; version: string; port?: number; readOnly: true }
export interface ManifestTree {
  agent: AgentNode | null; reporting: ReportingNode | null; approved: ApprovedNode[]; runtime: RuntimeNode[];
}

export interface ValidationError { path: string; message: string }
export interface Validation { ok: boolean; errors: ValidationError[] }
export interface ManifestFile {
  path: string; kind: ManifestKind; text: string; hash: string; version: string; status: string;
  readOnly: boolean; validation: Validation;
}
export type SavedFile = Pick<ManifestFile, 'path' | 'text' | 'hash' | 'version' | 'status' | 'validation'>;

export type SaveResult =
  | { type: 'ok'; file: SavedFile }
  | { type: 'invalid'; validation: Validation }
  | { type: 'conflict'; currentHash: string }
  | { type: 'error'; status: number; message: string };

export class ManifestApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const HINTS: Record<number, string> = {
  401: 'Your session has expired. Please sign in again.',
  403: 'Your account may not do this. Saving manifests needs an admin account.',
  413: 'The manifest is too large (limit 512 KB).',
};

async function call(path: string, init?: RequestInit): Promise<Response> {
  const token = getSessionToken();
  let res: Response;
  try {
    res = await fetch(backendUrl(path), {
      ...init,
      headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
  } catch (err) {
    throw new ManifestApiError(0, `Could not reach the CAM daemon (${err instanceof Error ? err.message : 'network error'}). Check that it is running.`);
  }
  if (res.status === 401) {
    clearSession();
    window.location.hash = '#/login';
  }
  return res;
}

async function failure(res: Response): Promise<ManifestApiError> {
  const body = (await res.json().catch(() => ({}))) as { error?: string };
  return new ManifestApiError(res.status, HINTS[res.status] ?? body.error ?? `The manifest service answered HTTP ${res.status}.`);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await call(path);
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

export async function fetchManifestTree(): Promise<ManifestTree> {
  return (await getJson<{ tree: ManifestTree }>('/api/manifests')).tree;
}

export const fetchManifestSchema = (kind: ManifestKind) =>
  getJson<Record<string, unknown>>(`/api/manifests/schema/${encodeURIComponent(kind)}`);

export const fetchManifestFile = (path: string) =>
  getJson<ManifestFile>(`/api/manifests/file?path=${encodeURIComponent(path)}`);

export async function saveManifestFile(req: { path: string; text: string; baseHash: string }): Promise<SaveResult> {
  const res = await call('/api/manifests/file', { method: 'PUT', body: JSON.stringify(req) });
  const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (res.ok) return { type: 'ok', file: body as unknown as SavedFile };
  if (res.status === 400 && body.validation) return { type: 'invalid', validation: body.validation as Validation };
  if (res.status === 409) return { type: 'conflict', currentHash: String(body.currentHash ?? '') };
  return { type: 'error', status: res.status, message: HINTS[res.status] ?? String(body.error ?? `The manifest service answered HTTP ${res.status}.`) };
}

export interface HistoryEntry { stamp: string; savedAt: string }
export interface HistoryVersion extends HistoryEntry { text: string; hash: string; version: string | null }

/** The earlier saved copies of one manifest, newest first (SPEC-022). */
export const fetchManifestHistory = async (path: string) =>
  (await getJson<{ versions: HistoryEntry[] }>(`/api/manifests/history?path=${encodeURIComponent(path)}`)).versions;

export const fetchManifestVersion = (path: string, stamp: string) =>
  getJson<HistoryVersion>(`/api/manifests/history/file?path=${encodeURIComponent(path)}&stamp=${encodeURIComponent(stamp)}`);

/** Short form of "sha256:abcdef..." for the status line. */
export function shortHash(hash: string): string {
  const h = hash.replace(/^sha256:/, '');
  return h.length > 8 ? `${h.slice(0, 8)}...` : h || 'none';
}
