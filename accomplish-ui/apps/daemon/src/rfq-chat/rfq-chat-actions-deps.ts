/**
 * The real calls behind the Create-RFQ action: Postgres (lazy import, db.ts throws without its env vars), the Python
 * bridge (JWT mint, attachments) and upload-server (the same POST /api/rfq/upload the intake modal makes).
 * Audit file: <CAM_CHAT_AUDIT_DIR or ~/.accomplish/rfq-chat>/actions-audit.jsonl, one JSON object per line, no secrets.
 */
import { randomBytes } from 'node:crypto';
import { appendFile, mkdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { UnknownOutcomeError, type ActionDeps } from './rfq-chat-actions-types.js';
import { realEditDeps } from './rfq-chat-edit-deps.js';
import { fetchRfqStatus } from './rfq-chat-status.js';

const bridge = (): string => (process.env.PYTHON_BRIDGE_URL ?? process.env.PYTHON_SERVICE_URL ?? 'http://localhost:3110').replace(/\/$/, '');
// Compose publishes upload-server on 13100; the bare-metal default is 3100 (same as the web client's RFQ_UPLOAD_URL).
const uploadServer = (): string => (process.env.RFQ_UPLOAD_URL ?? 'http://localhost:3100').replace(/\/$/, '');
export const auditFile = (): string => join(process.env.CAM_CHAT_AUDIT_DIR ?? join(homedir(), '.accomplish', 'rfq-chat'), 'actions-audit.jsonl');

async function pool() {
  const { fileMetadataPool } = await import('../db.js');
  return fileMetadataPool;
}

/** Fresh 60 s token scoped to one RFQ id, minted right before each call (see apps/web apiAuth.ts). */
async function authHeader(rfqId: string): Promise<Record<string, string>> {
  const res = await fetch(`${bridge()}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rfq_id: rfqId }),
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) {
    throw new Error(`token mint failed: HTTP ${res.status}`);
  }
  return { Authorization: `Bearer ${((await res.json()) as { token: string }).token}` };
}

async function failure(res: Response, what: string): Promise<Error> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  return new Error(`${what} answered HTTP ${res.status}${typeof body?.detail === 'string' ? `: ${body.detail}` : ''}`);
}

const blob = (b: Uint8Array): Blob => new Blob([new Uint8Array(b)]);

export function realActionDeps(): ActionDeps {
  return {
    now: () => Date.now(),
    newToken: () => randomBytes(24).toString('base64url'),
    async listCustomers() {
      const { rows } = await (await pool()).query('SELECT customer_id, customer_name FROM customers ORDER BY customer_name');
      return rows.map((r) => ({ customerId: String(r.customer_id), customerName: String(r.customer_name) }));
    },
    async listProjects() {
      const { rows } = await (await pool()).query('SELECT project_id, customer_id, project_name FROM projects ORDER BY project_name');
      return rows.map((r) => ({ projectId: String(r.project_id), customerId: String(r.customer_id), projectName: String(r.project_name) }));
    },
    async nextRfqId() {
      // Same query as projectTracking.getNextRfqId: smallest unused RFQ-NNNNNN, no side effect.
      const { rows } = await (await pool()).query(`
        WITH used_ids AS (
          SELECT CAST(SUBSTRING(rfq_id FROM 5) AS INTEGER) AS n FROM rfq_process_tracking WHERE rfq_id ~ '^RFQ-[0-9]{6}$'
          UNION
          SELECT CAST(SUBSTRING(rfq_id FROM 5) AS INTEGER) AS n FROM rfq_project_tracking WHERE rfq_id ~ '^RFQ-[0-9]{6}$'
        )
        SELECT COALESCE(MIN(candidate), 1) AS n FROM generate_series(1, (SELECT COALESCE(MAX(n), 0) FROM used_ids) + 1) AS candidate
        WHERE candidate NOT IN (SELECT n FROM used_ids)`);
      return `RFQ-${String(Number(rows[0].n)).padStart(6, '0')}`;
    },
    async listAttachments(scope) {
      const res = await fetch(`${bridge()}/api/rfq/${encodeURIComponent(scope)}/attachments`, { headers: await authHeader(scope), signal: AbortSignal.timeout(15000) });
      if (!res.ok) {
        throw await failure(res, 'the attachment list');
      }
      const rows = (await res.json()) as Array<{ attachment_id: string; name: string; sha256?: string | null }>;
      return rows.map((r) => ({ attachmentId: r.attachment_id, name: r.name, sha256: r.sha256 ?? null }));
    },
    async readAttachment(scope, attachmentId) {
      // Needs the bridge route GET /api/rfq/{id}/attachments/{attachment_id}/content (not in the bridge yet).
      const res = await fetch(`${bridge()}/api/rfq/${encodeURIComponent(scope)}/attachments/${encodeURIComponent(attachmentId)}/content`, { headers: await authHeader(scope), signal: AbortSignal.timeout(60000) });
      if (!res.ok) {
        throw await failure(res, 'the attachment download');
      }
      return new Uint8Array(await res.arrayBuffer());
    },
    async createRfq({ rfqId, customerId, projectId }) {
      const db = await pool();
      // Same checks and insert as projectTracking.createRfq.
      const dup = await db.query('SELECT 1 FROM rfq_process_tracking WHERE rfq_id = $1 UNION ALL SELECT 1 FROM rfq_project_tracking WHERE rfq_id = $1 LIMIT 1', [rfqId]);
      if ((dup.rowCount ?? 0) > 0) {
        throw new Error(`RFQ ID "${rfqId}" already exists`);
      }
      const pr = await db.query('SELECT p.project_name, c.customer_name FROM projects p JOIN customers c ON c.customer_id = p.customer_id WHERE p.project_id = $1 AND p.customer_id = $2', [projectId, customerId]);
      if (pr.rowCount === 0) {
        throw new Error('the project does not belong to the customer');
      }
      await db.query('INSERT INTO rfq_project_tracking (rfq_id, customer_name, project_name, customer_id, project_id) VALUES ($1, $2, $3, $4, $5)', [rfqId, pr.rows[0].customer_name, pr.rows[0].project_name, customerId, projectId]);
    },
    async scanFiles(rfqId, files) {
      const body = new FormData();
      for (const f of files) {
        body.append('files', blob(f.bytes), f.name);
      }
      const res = await fetch(`${bridge()}/api/rfq/${encodeURIComponent(rfqId)}/attachments/scan`, { method: 'POST', body, headers: await authHeader(rfqId), signal: AbortSignal.timeout(180000) });
      if (!res.ok) {
        throw await failure(res, 'the scan service');
      }
      const out = (await res.json()) as { results: Array<{ name: string; decision: 'released' | 'quarantined' | 'error'; attachment_id: string | null }> };
      return out.results.map((r) => ({ name: r.name, decision: r.decision, attachmentId: r.attachment_id }));
    },
    async deleteAttachment(rfqId, attachmentId) {
      const res = await fetch(`${bridge()}/api/rfq/${encodeURIComponent(rfqId)}/attachments/${encodeURIComponent(attachmentId)}`, { method: 'DELETE', headers: await authHeader(rfqId), signal: AbortSignal.timeout(15000) });
      if (!res.ok && res.status !== 404) {
        throw await failure(res, 'the attachment delete');
      }
    },
    async upload(rfqId, bom, volume) {
      const body = new FormData();
      body.append('bom_file', blob(bom.bytes), bom.name);
      body.append('volume_file', blob(volume.bytes), volume.name);
      body.append('rfq_id', rfqId);
      let res: Response;
      try {
        res = await fetch(`${uploadServer()}/api/rfq/upload`, { method: 'POST', body, headers: await authHeader(rfqId), signal: AbortSignal.timeout(180000) });
      } catch (err) {
        // The server may have received and finished the request: the caller must not delete anything.
        throw new UnknownOutcomeError(`the upload service did not answer (${err instanceof Error ? err.message : String(err)})`);
      }
      if (!res.ok) {
        throw await failure(res, 'the upload service');
      }
      const out = (await res.json()) as { telemetry?: { dify_pipeline_status?: string } };
      return { pipelineStatus: out.telemetry?.dify_pipeline_status ?? '' };
    },
    async deleteRfqRows(rfqId) {
      const db = await pool();
      for (const t of ['rfq_file_telemetry', 'rfq_process_tracking', 'rfq_project_tracking']) {
        await db.query(`DELETE FROM ${t} WHERE rfq_id = $1`, [rfqId]);
      }
    },
    pipelineState: (rfqId) => fetchRfqStatus(rfqId),
    async startPipeline(rfqId) {
      const headers = await authHeader(rfqId); // a failed mint means nothing was sent
      let res: Response;
      try {
        res = await fetch(`${uploadServer()}/api/dify/start/${encodeURIComponent(rfqId)}`, { headers, signal: AbortSignal.timeout(60000) });
      } catch (err) {
        // The server may have started the run before the connection dropped.
        throw new UnknownOutcomeError(`the upload service did not answer (${err instanceof Error ? err.message : String(err)})`);
      }
      if (!res.ok) {
        throw await failure(res, 'the upload service');
      }
      const out = (await res.json()) as { success?: boolean; dify_status?: string; dify_response?: { outcome?: string } };
      return { status: out.dify_status ?? (out.success ? 'SUCCESS' : ''), outcome: out.dify_response?.outcome };
    },
    ...realEditDeps({ bridge, authHeader, failure }),
    async appendAudit(line) {
      const file = auditFile();
      await mkdir(join(file, '..'), { recursive: true });
      await appendFile(file, `${JSON.stringify(line)}\n`, 'utf8');
    },
  };
}
