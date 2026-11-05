/**
 * Files attached to the RFQ assistant: which ones may be sent (triage), and the calls to the Python bridge that scan
 * them with two engines (BuLL*Sav / ClamAV and Repel Shield), list the released ones and remove them.
 * Only files that BOTH engines clear are released; the assistant can read nothing else.
 */
import { PYTHON_BRIDGE_URL } from '../config/endpoints';
import { authFetch } from './apiAuth';

export const ACCEPTED_EXTENSIONS = ['.xlsx', '.xls', '.csv', '.tsv', '.txt', '.md', '.json', '.docx', '.pdf'];
export const MAX_FILES = 10;
export const MAX_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 60 * 1024 * 1024;

export type RejectReason = 'system' | 'unsupported' | 'empty' | 'too_large' | 'duplicate';

export const REJECT_TEXT: Record<RejectReason, string> = {
  system: 'System or temporary file',
  unsupported: `Unsupported type (accepted: ${ACCEPTED_EXTENSIONS.join(' ')})`,
  empty: 'Empty file',
  too_large: `Larger than ${MAX_FILE_BYTES / 1024 / 1024} MB`,
  duplicate: 'Already in this selection or already attached',
};

export interface Triage {
  usable: File[];
  rejected: Array<{ file: File; reason: RejectReason }>;
}

const SYSTEM_FILE = /^(\..*|~\$.*|thumbs\.db|desktop\.ini)$/i;
const extOf = (name: string) => (name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : '');

/** Sorts a pick into files that may be sent and files that are turned away, each with its reason. Never throws. */
export function triageFiles(files: ArrayLike<File>, alreadyAttached: string[] = []): Triage {
  const seen = new Set(alreadyAttached.map((n) => n.toLowerCase()));
  const out: Triage = { usable: [], rejected: [] };
  for (const file of Array.from(files)) {
    const key = `${file.name.toLowerCase()}`;
    const reason: RejectReason | null = SYSTEM_FILE.test(file.name) ? 'system'
      : !ACCEPTED_EXTENSIONS.includes(extOf(file.name)) ? 'unsupported'
      : file.size === 0 ? 'empty'
      : file.size > MAX_FILE_BYTES ? 'too_large'
      : seen.has(key) ? 'duplicate'
      : null;
    if (reason) {
      out.rejected.push({ file, reason });
    } else {
      seen.add(key);
      out.usable.push(file);
    }
  }
  return out;
}

/** Whether the chosen files may go in one scan request; the reason when they may not. */
export function fitsOneScan(chosen: File[]): { ok: boolean; reason?: string } {
  if (chosen.length === 0) return { ok: false, reason: 'Select at least one file' };
  if (chosen.length > MAX_FILES) return { ok: false, reason: `${chosen.length} selected; at most ${MAX_FILES} per scan. Untick ${chosen.length - MAX_FILES}.` };
  const bytes = chosen.reduce((n, f) => n + f.size, 0);
  if (bytes > MAX_TOTAL_BYTES) return { ok: false, reason: `${formatBytes(bytes)} selected; at most ${formatBytes(MAX_TOTAL_BYTES)} per scan.` };
  return { ok: true };
}

/** Most files one attach action will take in total, however many waves that makes. */
export const MAX_PICK = 100;

/**
 * Splits an over-limit pick into sequential waves that each fit one scan (10 files, 60 MB), keeping the order.
 * A file over 25 MB can never be scanned, so it is rejected with the usual reason instead of getting a wave.
 */
export function planWaves(files: File[]): { waves: File[][]; rejected: Triage['rejected'] } {
  const out: { waves: File[][]; rejected: Triage['rejected'] } = { waves: [], rejected: [] };
  let bytes = 0;
  for (const file of files) {
    if (file.size > MAX_FILE_BYTES) {
      out.rejected.push({ file, reason: 'too_large' });
      continue;
    }
    const last = out.waves[out.waves.length - 1];
    if (!last || last.length >= MAX_FILES || bytes + file.size > MAX_TOTAL_BYTES) {
      out.waves.push([]);
      bytes = 0;
    }
    out.waves[out.waves.length - 1].push(file);
    bytes += file.size;
  }
  return out;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export type Verdict = 'clean' | 'threat' | 'error';

export interface EngineStatus {
  id: 'clamav' | 'repel';
  label: string;
  status: 'ok' | 'unavailable';
  version?: string | null;
}

export interface ScanResult {
  name: string;
  size: number;
  sha256: string;
  ext?: string;
  clamav: { verdict: Verdict; detail?: string | null };
  repel: { verdict: Verdict; score?: number; flags?: string[]; detail?: string | null };
  decision: 'released' | 'quarantined' | 'error';
  reason?: string | null;
  attachment_id: string | null;
  ms?: number;
}

export interface ScanResponse {
  rfq_id: string;
  engines: EngineStatus[];
  results: ScanResult[];
}

export interface Attachment {
  attachment_id: string;
  name: string;
  size: number;
  sha256: string;
  released_at: string;
}

const base = (rfqId: string) => `${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/attachments`;

async function failure(res: Response): Promise<Error> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown; error?: string } | null;
  const detail = typeof body?.detail === 'string' ? body.detail : body?.error;
  return new Error(detail ?? `The scan service answered HTTP ${res.status}`);
}

/** Uploads the files to quarantine and scans each with both engines. Nothing is released unless both say clean. */
export async function scanFiles(rfqId: string, files: File[], signal?: AbortSignal): Promise<ScanResponse> {
  const body = new FormData();
  for (const f of files) body.append('files', f, f.name);
  const res = await authFetch(`${base(rfqId)}/scan`, rfqId, { method: 'POST', body, signal });
  if (!res.ok) throw await failure(res);
  return (await res.json()) as ScanResponse;
}

export async function listAttachments(rfqId: string): Promise<Attachment[]> {
  const res = await authFetch(base(rfqId), rfqId);
  if (!res.ok) throw await failure(res);
  return (await res.json()) as Attachment[];
}

export async function deleteAttachment(rfqId: string, attachmentId: string): Promise<void> {
  const res = await authFetch(`${base(rfqId)}/${encodeURIComponent(attachmentId)}`, rfqId, { method: 'DELETE' });
  if (!res.ok) throw await failure(res);
}
