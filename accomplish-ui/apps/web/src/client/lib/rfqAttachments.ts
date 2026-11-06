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
  /** What the bridge read INSIDE a released file (SPEC-022); absent for files that were not released and on older bridges. */
  role?: FileRole;
  role_label?: string;
  role_reason?: string;
  /** Plain-words reasons the pipeline would reject this file. */
  problems?: string[];
  /** SPEC-023 pre-flight of a BOM workbook: cells that would be NaN / empty / an Excel error in the output. */
  check?: FileCheck;
}

export interface FileCheck {
  checked: boolean;
  ok: boolean;
  errors: number;
  warnings: number;
}

export type FileRole = 'scrub_bom' | 'bom' | 'volume' | 'quotewin' | 'document' | 'unknown';

export interface Readiness {
  ready: boolean;
  /** One sentence for the dialog: what will be used, or why nothing can be created yet. */
  message: string;
  /** The BOM workbook has cells that would be NaN / error in the output: the dialog offers to fix them. */
  fix?: { attachmentId: string; name: string; errors: number; warnings: number };
}

/** Whether the released files are enough to create an RFQ, from their recognised roles (SPEC-022). Mirrors the daemon's create_rfq choice. */
export function intakeReadiness(results: ScanResult[]): Readiness {
  const released = results.filter((r) => r.decision === 'released');
  const of = (role: FileRole) => released.filter((r) => r.role === role);
  const scrub = of('scrub_bom');
  if (scrub.length > 1) return { ready: false, message: `${scrub.map((r) => r.name).join(' and ')} each have a SCRUB BOM sheet. Say which one is the BOM and I will use that.` };
  if (scrub.length === 1 && scrub[0].check?.checked && scrub[0].check.errors > 0 && scrub[0].attachment_id) {
    const n = scrub[0].check.errors;
    return {
      ready: false,
      message: `${scrub[0].name} cannot start a run yet: ${n} cell${n === 1 ? '' : 's'} would give NaN or errors in the output. Fix ${n === 1 ? 'it' : 'them'} here.`,
      fix: { attachmentId: scrub[0].attachment_id, name: scrub[0].name, errors: n, warnings: scrub[0].check.warnings },
    };
  }
  if (scrub.length === 1) {
    const vol = of('volume');
    return {
      ready: vol.length <= 1,
      message: vol.length > 1 ? `Which of ${vol.map((r) => r.name).join(' and ')} is the volume file?`
        : `${scrub[0].name} is the BOM workbook${vol.length === 1 ? ` and ${vol[0].name} the volume file` : '; its Settings sheet carries the volumes'}.`,
    };
  }
  const plain = of('bom');
  if (plain.length > 0) return { ready: false, message: `${plain[0].name} cannot start the pipeline: ${plain[0].problems?.[0] ?? 'it has no SCRUB BOM sheet.'}` };
  if (of('quotewin').length > 0 && released.every((r) => r.role === 'quotewin' || r.role === 'document')) {
    return { ready: false, message: 'A QuoteWin file belongs to the ERP & Quoting tools step of an existing RFQ, not to creating one. Attach the BOM workbook to create an RFQ.' };
  }
  return { ready: false, message: released.length === 0 ? 'No file was released yet.' : 'None of the released files is a BOM workbook (a workbook with a SCRUB BOM sheet).' };
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
  /** What the bridge read inside the file (SPEC-022); absent on older bridges. */
  role?: FileRole;
  role_label?: string;
  problems?: string[];
  check?: FileCheck;
}

/** Short word for a chip: what the file is to the pipeline. `warn` = it cannot start a run. */
export function roleChip(a: Pick<Attachment, 'role' | 'check'>): { text: string; warn: boolean } | null {
  switch (a.role) {
    case 'scrub_bom': return a.check?.checked && a.check.errors > 0 ? { text: `BOM: ${a.check.errors} to fix`, warn: true } : { text: 'BOM', warn: false };
    case 'volume': return { text: 'Volume', warn: false };
    case 'quotewin': return { text: 'QuoteWin', warn: false };
    case 'document': return { text: 'Reference', warn: false };
    case 'bom': return { text: 'BOM: no SCRUB BOM sheet', warn: true };
    case 'unknown': return { text: 'Not recognised', warn: true };
    default: return null;
  }
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
