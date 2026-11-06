/** Run history of an RFQ's pipeline (SPEC-021): GET {upload service}/api/rfq/{id}/runs, read from Temporal. */
import { backendUrl, RFQ_UPLOAD_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { getSessionToken } from '@/lib/session';

export type RunStatus = 'running' | 'waiting' | 'passed' | 'failed' | 'stopped' | 'replaced' | 'cancelled';
export type FailureKind = 'invalid_input' | 'configuration' | 'tool_error';

export interface RunFailure {
  kind: FailureKind;
  title: string;
  cause: string;
  next_step: string;
  step: string;
  can_rerun: boolean;
  raw: string;
}

export interface RunEntry {
  run_id: string;
  /** Set on the all-RFQs listing. */
  rfq_id?: string;
  status: RunStatus;
  started_at: string | null;
  closed_at: string | null;
  duration_ms: number | null;
  started_by: string;
  started_by_email?: string | null;
  failed_step: string | null;
  /** Set while status is 'waiting': the step that is parked at a human review. */
  waiting_on?: string | null;
  failure: RunFailure | null;
  can_rerun: boolean;
}

export async function fetchRuns(rfqId: string): Promise<RunEntry[]> {
  const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/${encodeURIComponent(rfqId)}/runs`, rfqId);
  if (!res.ok) {
    let detail = '';
    try { detail = ((await res.json()) as { detail?: string }).detail ?? ''; } catch { /* body is not JSON */ }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return ((await res.json()) as { runs: RunEntry[] }).runs;
}

/**
 * Recent runs of every RFQ, through the daemon, which decides who may see what: an admin sees everybody's (or one user's, with `by`),
 * anybody else only the runs they started themselves.
 */
export async function fetchAllRuns(opts: { by?: string; limit?: number } = {}): Promise<RunEntry[]> {
  const q = new URLSearchParams({ limit: String(opts.limit ?? 50), ...(opts.by ? { by: opts.by } : {}) });
  const token = getSessionToken();
  const res = await fetch(backendUrl(`/api/runs?${q.toString()}`), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let detail = '';
    try { detail = ((await res.json()) as { error?: string }).error ?? ''; } catch { /* body is not JSON */ }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return ((await res.json()) as { runs: RunEntry[] }).runs;
}

/** Who started the runs, with how each went: one entry per person, most active first (the tracking summary above the all-RFQs list). */
export function summarizeByUser(runs: RunEntry[]): Array<{ who: string; total: number; passed: number; failed: number; open: number }> {
  const by = new Map<string, { who: string; total: number; passed: number; failed: number; open: number }>();
  for (const r of runs) {
    const e = by.get(r.started_by) ?? { who: r.started_by, total: 0, passed: 0, failed: 0, open: 0 };
    e.total++;
    if (r.status === 'passed') e.passed++;
    else if (r.status === 'failed') e.failed++;
    else if (r.status === 'running' || r.status === 'waiting') e.open++;
    by.set(r.started_by, e);
  }
  return [...by.values()].sort((a, b) => b.total - a.total || a.who.localeCompare(b.who));
}

/** "12 s", "3 min 05 s", "1 h 02 min"; null (still running) reads as an em dash. */
export function formatDuration(ms: number | null): string {
  if (ms === null) return '—';
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, '0')} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`;
}

/** The badge word of a run: a failure says what kind it is, because "wrong file" and "tool broke" need different reactions. */
export function badgeWord(r: Pick<RunEntry, 'status' | 'failure'>): string {
  if (r.status === 'failed') {
    return r.failure?.kind === 'invalid_input' ? 'Invalid input' : r.failure?.kind === 'configuration' ? 'Needs setup' : 'Failed';
  }
  return { running: 'Running', waiting: 'Waiting for your review', passed: 'Passed', stopped: 'Stopped at review', replaced: 'Replaced by a newer run', cancelled: 'Cancelled' }[r.status as Exclude<RunStatus, 'failed'>];
}
