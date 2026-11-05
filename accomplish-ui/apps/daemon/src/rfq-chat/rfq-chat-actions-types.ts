/**
 * Types and small helpers shared by the Create-RFQ action (rfq-chat-actions*.ts). Every network and database call the
 * action makes goes through ActionDeps, so unit tests run with fakes and the real wiring (rfq-chat-actions-deps.ts)
 * loads db.ts lazily (it throws at import without its env vars).
 */
import { createHash } from 'node:crypto';

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

export interface Attachment {
  attachmentId: string;
  name: string;
  sha256: string | null;
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
  upload(rfqId: string, bom: { name: string; bytes: Uint8Array }, volume: { name: string; bytes: Uint8Array }): Promise<{ pipelineStatus: string }>;
  /** Removes the tracking and file rows of an RFQ this run created. */
  deleteRfqRows(rfqId: string): Promise<void>;
  appendAudit(line: AuditLine): Promise<void>;
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
