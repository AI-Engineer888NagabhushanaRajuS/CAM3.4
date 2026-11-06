/**
 * SPEC-023: the BOM pre-flight. The bridge lists every cell that would be NaN / empty / an Excel error in the output
 * (GET .../attachments/{id}/check); the user types the corrections, the bridge writes them into a scanned copy that
 * replaces the original (POST .../fix), and the corrected file is downloaded to the user's computer.
 */
import { PYTHON_BRIDGE_URL } from '../config/endpoints';
import { authDownload, authFetch } from './apiAuth';

export interface CheckIssue {
  severity: 'error' | 'warning';
  code: string;
  sheet: string | null;
  row: number | null;
  col: string | null;
  column: string | null;
  value: string | null;
  message: string;
  /** false: no single cell fixes it (a missing sheet or column, a missing FG row): it needs Excel. */
  fixable: boolean;
  /** The number a text cell reads as. */
  suggestion?: string;
}

export interface CheckReport {
  checked: boolean;
  ok: boolean;
  errors: number;
  warnings: number;
  rows: number;
  issues: CheckIssue[];
  truncated: boolean;
  message?: string;
}

export interface CellEdit {
  sheet: string;
  row: number;
  col: string;
  value: string;
}

export interface FixedAttachment {
  attachment_id: string;
  name: string;
  size: number;
  sha256: string;
  cells_changed: number;
  role?: string;
  check?: { checked: boolean; ok: boolean; errors: number; warnings: number };
  report: CheckReport;
}

const base = (scope: string, id: string) => `${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(scope)}/attachments/${encodeURIComponent(id)}`;

async function failure(res: Response, what: string): Promise<Error> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  return new Error(typeof body?.detail === 'string' ? body.detail : `${what} failed (HTTP ${res.status})`);
}

export const cellKey = (i: Pick<CheckIssue, 'sheet' | 'col' | 'row'>): string => `${i.sheet}!${i.col}${i.row}`;
export const cellAddress = (i: Pick<CheckIssue, 'col' | 'row'>): string => `${i.col}${i.row}`;

export async function fetchCheck(scope: string, attachmentId: string): Promise<CheckReport & { name: string }> {
  const res = await authFetch(`${base(scope, attachmentId)}/check`, scope);
  if (!res.ok) throw await failure(res, 'The check');
  return (await res.json()) as CheckReport & { name: string };
}

export async function submitFix(scope: string, attachmentId: string, edits: CellEdit[]): Promise<FixedAttachment> {
  const res = await authFetch(`${base(scope, attachmentId)}/fix`, scope, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ edits }),
  });
  if (!res.ok) throw await failure(res, 'Saving the corrections');
  return (await res.json()) as FixedAttachment;
}

/** Saves the released file to the user's computer (a click started this, so the browser allows it). */
export const downloadAttachment = (scope: string, attachmentId: string, name: string): Promise<void> =>
  authDownload(`${base(scope, attachmentId)}/content`, scope, name);

/** The edits to send: only cells whose box was changed from what the file holds. */
export function collectEdits(issues: CheckIssue[], typed: Record<string, string>): CellEdit[] {
  const out: CellEdit[] = [];
  for (const i of issues) {
    if (!i.fixable || i.sheet == null || i.col == null || i.row == null) continue;
    const key = cellKey(i);
    if (key in typed && typed[key] !== (i.value ?? '')) out.push({ sheet: i.sheet, row: i.row, col: i.col, value: typed[key] });
  }
  return out;
}
