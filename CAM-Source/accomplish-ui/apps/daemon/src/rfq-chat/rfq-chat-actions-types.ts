/**
 * Types and small helpers shared by the Create-RFQ action (rfq-chat-actions*.ts). Every network and database call the
 * action makes goes through ActionDeps, so unit tests run with fakes and the real wiring (rfq-chat-actions-deps.ts)
 * loads db.ts lazily (it throws at import without its env vars).
 */
import { createHash } from 'node:crypto';
import type { RfqStatus } from './rfq-chat-status.js';

export type FileRole = 'BOM' | 'VOLUME';

export interface FileParam {
  role: FileRole;
  name: string;
  attachmentId: string;
  sha256: string | null;
  /** The RFQ id (or chat staging id) the file was scanned under, where its bytes are read from. */
  sourceScope: string;
}

/** The exact parameters the user confirms; hashed into the token, so nothing here can change after the card is shown. */
export interface CreateRfqParams {
  rfqId: string;
  customer: { id: string; name: string };
  project: { id: string; name: string };
  files: FileParam[];
  profile: string;
}

/** The parameters of a confirmed "resume the pipeline" card. */
export interface StartPipelineParams {
  rfqId: string;
  /** Stage n of 9 when the card was issued. */
  stage: number | null;
  customer: string | null;
  project: string | null;
}

/** The parameters of a confirmed "change one value and regenerate the reports" card (SPEC-020). */
export interface EditValueParams {
  rfqId: string;
  bomItemId: string;
  /** Part number (or description) shown to the user. */
  label: string;
  field: string;
  fieldLabel: string;
  /** The value on the card: the one shared by every row, or "Volume 1: x; Volume 2: y" when the volumes differ. */
  before: string | number | null;
  after: string | number;
  /** Set when the user named one volume ("volume 2"); null = every volume row of the bom item id. */
  volumeNo: number | null;
  /** Current value per volume row the edit touches; Confirm checks each one again. */
  volumes: Array<{ volumeNo: number | null; before: string | number | null }>;
}

/** One costed-BOM row as the preview endpoint returns it, reduced to what the edit needs. */
export interface BomRow {
  bomItemId: string;
  /** Volume the row belongs to (the same bom item id can have a row per volume); null when the bridge does not say. */
  volumeNo: number | null;
  cpn: string;
  mpn: string;
  fg: string;
  description: string;
  /** The final_* values of the row, as stored. */
  values: Record<string, string | number | null>;
}

/** What the bridge answers for POST /api/rfq/{id}/edit-and-regenerate. */
export interface EditResult {
  applied: number;
  before: { filename: string } | null;
  after: { filename: string; generated_at?: string };
  diff: { total_changed_cells: number; sheets: Array<{ sheet: string; changed: number }> } | null;
}

/** The signed-in person who pressed Confirm: the run history shows them as the one who started the run (the assistant only acted for them). */
export interface ActionActor {
  name: string;
  email: string;
}

export interface Attachment {
  attachmentId: string;
  name: string;
  sha256: string | null;
  /** What the bridge found IN the released file (SPEC-022): scrub_bom, bom, volume, quotewin, document or unknown. Absent on older bridges. */
  role?: string;
  /** Plain-words reasons the run would reject this file (for example no SCRUB BOM sheet). */
  problems?: string[];
  /** SPEC-023 pre-flight of a BOM workbook: cells that would be NaN / empty / an Excel error in the output. Absent on older bridges. */
  check?: { checked: boolean; ok: boolean; errors: number; warnings: number };
}

export interface ScanVerdict {
  name: string;
  decision: 'released' | 'quarantined' | 'error';
  attachmentId: string | null;
}

export interface AuditLine {
  who: string;
  when: string;
  action: string;
  paramHash: string;
  result: string;
}

/** An upload whose outcome the caller cannot know (network error or timeout): the server may have finished it. */
export class UnknownOutcomeError extends Error {}

export interface ActionDeps {
  now(): number;
  newToken(): string;
  listCustomers(): Promise<Array<{ customerId: string; customerName: string }>>;
  listProjects(): Promise<Array<{ projectId: string; customerId: string; projectName: string }>>;
  nextRfqId(): Promise<string>;
  /** Released (passed both engines) attachments stored under `scope`. */
  listAttachments(scope: string): Promise<Attachment[]>;
  readAttachment(scope: string, attachmentId: string): Promise<Uint8Array>;
  /** Same insert as projectTracking.createRfq; throws when the id exists. */
  createRfq(p: { rfqId: string; customerId: string; projectId: string }): Promise<void>;
  /** Scans under the new RFQ id with both engines; released files get an attachment id. */
  scanFiles(rfqId: string, files: Array<{ name: string; bytes: Uint8Array }>): Promise<ScanVerdict[]>;
  deleteAttachment(rfqId: string, attachmentId: string): Promise<void>;
  /** POST /api/rfq/upload exactly as the intake modal does; it also starts the pipeline and reports its status. */
  upload(rfqId: string, bom: { name: string; bytes: Uint8Array }, volume: { name: string; bytes: Uint8Array }, actor?: ActionActor): Promise<{ pipelineStatus: string }>;
  /** Removes the tracking and file rows of an RFQ this run created. */
  deleteRfqRows(rfqId: string): Promise<void>;
  appendAudit(line: AuditLine): Promise<void>;
  /** Pipeline progress of an RFQ from the database (rfq-chat-status.ts). */
  pipelineState(rfqId: string): Promise<RfqStatus>;
  /** GET {RFQ_UPLOAD_URL}/api/dify/start/{rfqId}, the call the UI makes to resume; throws UnknownOutcomeError when the answer is unknown. */
  startPipeline(rfqId: string, actor?: ActionActor): Promise<{ status: string; outcome?: string }>;
  /** Costed-BOM rows of an RFQ whose bom item id, CPN or manufacturer part number equals `target` (case-insensitive). */
  findBomRows(rfqId: string, target: string): Promise<BomRow[]>;
  /** POST {bridge}/api/rfq/{rfqId}/edit-and-regenerate; throws UnknownOutcomeError when the answer is unknown, Error with the bridge's detail on a refusal. */
  editAndRegenerate(rfqId: string, edit: { bomItemId: string; field: string; value: string | number; volumeNo?: number }, note: string): Promise<EditResult>;
}

/** JSON with sorted keys, so the same parameters always hash the same. */
export function canonicalJson(v: unknown): string {
  if (Array.isArray(v)) {
    return `[${v.map(canonicalJson).join(',')}]`;
  }
  if (v !== null && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${canonicalJson(o[k])}`).join(',')}}`;
  }
  return JSON.stringify(v) ?? 'null';
}

export const hashParams = (p: unknown): string => createHash('sha256').update(canonicalJson(p)).digest('hex');

/** Where a file attached before any RFQ exists is scanned and kept: one scratch scope per chat session. */
export const chatStagingId = (sessionKey: string): string =>
  `CHAT-${createHash('sha256').update(sessionKey).digest('hex').slice(0, 20)}`;

/** The attachment id the bridge gives a released file: the first 12 hex digits of its sha256. */
export const sha12 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex').slice(0, 12);
