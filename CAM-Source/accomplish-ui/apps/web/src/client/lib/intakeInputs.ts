/**
 * The QuoteWin and costing sheet of an RFQ, kept on the server (upload service, rfq_input_staging) from the moment they are dropped in the
 * intake until the BOM is uploaded, when the server attaches them to that version. Memory of what went where is also written to Cognee
 * (rfq-memory-server) by the server itself. The browser holds no copy.
 */
import { RFQ_UPLOAD_URL } from '../config/endpoints';
import { authFetch } from './apiAuth';

export type StagedRole = 'quotewin' | 'costing';

export interface StagedInput {
  file_name: string;
  staged_at: string | null;
}

/** Keeps the file for this RFQ and role on the server. Throws with the server's reason when it is refused. */
export async function stageInput(rfqId: string, role: StagedRole, file: File): Promise<StagedInput> {
  const rfq = rfqId.trim();
  const body = new FormData();
  body.append('file', file);
  const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/${encodeURIComponent(rfq)}/inputs/${role}`, rfq, { method: 'POST', body });
  if (!res.ok) {
    const detail = ((await res.json().catch(() => null)) as { detail?: string | { message?: string } } | null)?.detail;
    const message = typeof detail === 'string' ? detail : detail?.message ?? `status ${res.status}`;
    throw new Error(`${file.name} was not kept: ${message}`);
  }
  return { file_name: file.name, staged_at: null };
}

/** Forgets the staged file of this role. */
export async function unstageInput(rfqId: string, role: StagedRole): Promise<void> {
  const rfq = rfqId.trim();
  const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/${encodeURIComponent(rfq)}/inputs/${role}`, rfq, { method: 'DELETE' });
  if (!res.ok) { throw new Error(`The staged ${role} file could not be removed (status ${res.status}).`); }
}

/** The inputs already kept for this RFQ, by role. An empty object when none is kept or the server cannot be reached. */
export async function listStaged(rfqId: string): Promise<Partial<Record<StagedRole, StagedInput>>> {
  const rfq = rfqId.trim();
  if (!rfq) { return {}; }
  try {
    const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/${encodeURIComponent(rfq)}/inputs`, rfq);
    if (!res.ok) { return {}; }
    const body = (await res.json()) as { staged?: Partial<Record<StagedRole, StagedInput>> };
    return body.staged ?? {};
  } catch {
    return {};
  }
}
