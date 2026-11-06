/** Run history of an RFQ's pipeline (SPEC-021): GET {upload service}/api/rfq/{id}/runs, read from Temporal. */
import { RFQ_UPLOAD_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';

export type RunStatus = 'running' | 'passed' | 'failed' | 'stopped' | 'replaced' | 'cancelled';
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
  status: RunStatus;
  started_at: string | null;
  closed_at: string | null;
  duration_ms: number | null;
  started_by: string;
  failed_step: string | null;
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
  return { running: 'Running', passed: 'Passed', stopped: 'Stopped at review', replaced: 'Replaced by a newer run', cancelled: 'Cancelled' }[r.status as Exclude<RunStatus, 'failed'>];
}
