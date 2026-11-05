/**
 * Daemon-side HTTP client to the Python backend for the RFQ chat feature
 * (BuLLMQuote-SRIM). Mints a fresh 60s rfq-scoped JWT (same contract
 * apps/web/src/client/lib/apiAuth.ts uses browser-side — this is the
 * daemon-side port, since the daemon, not the browser, is the caller for
 * this path) immediately before each real call, and calls
 * mcp-tools/rfq-memory/memory_service.py's JWT-verified chat routes.
 *
 * rfq_id is only ever used here after it comes back verified inside the
 * minted token's own round-trip — this file never trusts a bare rfqId
 * string for authorization on its own.
 */

import { log } from '../logger.js';
import type { MessageCitation } from '@accomplish_ai/agent-core';

// The Python bridge (JWT minting, results evidence) and the optional Cognee memory service. The defaults are the
// local bare-metal ports; run-cam34.ps1 / the daemon .env point PYTHON_SERVICE_URL at the compose-published port.
const PYTHON_BRIDGE_URL = (process.env.PYTHON_BRIDGE_URL ?? process.env.PYTHON_SERVICE_URL ?? 'http://localhost:3110').replace(/\/$/, '');
const RFQ_MEMORY_CHAT_URL = (process.env.RFQ_MEMORY_CHAT_URL ?? 'http://localhost:8108').replace(/\/$/, '');

export type { MessageCitation };

export interface RfqChatRetrieveResult {
  matched: boolean;
  chunks: Array<{ text: string; citation: MessageCitation; score?: number }>;
  sessionRecall: string | null;
  warning: string | null;
}

async function mintRfqToken(rfqId: string, timeoutMs = 5000): Promise<string> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${PYTHON_BRIDGE_URL}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rfq_id: rfqId }),
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`token mint failed: HTTP ${res.status}`);
    }
    const data = (await res.json()) as { token: string };
    return data.token;
  } finally {
    clearTimeout(timeout);
  }
}

export interface RfqEvidence {
  chunks: Array<{ text: string; citation: MessageCitation; score?: number }>;
  namedIdentifiers: string[];
  missingIdentifiers: string[];
  /** Rows of the results that matched the question, out of how many the results hold (a list is partial when more matched than were shown). */
  matchedRows: number;
  rowsInResults: number;
  workbook: string | null;
  warning: string | null;
}

/**
 * The RFQ's own results as citable rows (the latest exported workbook's stored values + the RFQ's live state), ranked
 * against the question by the Python bridge (fastapi-router/chat_evidence.py). Null when the bridge cannot be reached.
 */
export async function retrieveRfqEvidence(params: { rfqId: string; question: string; topK?: number; timeoutMs?: number }): Promise<RfqEvidence | null> {
  const { rfqId, question, topK = 12, timeoutMs = 20000 } = params;
  try {
    const token = await mintRfqToken(rfqId);
    const res = await fetch(`${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/chat/evidence`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ question, top_k: topK }),
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) {
      log.warn(`[RfqChat] evidence HTTP ${res.status} for rfqId=${rfqId}`);
      return null;
    }
    const d = (await res.json()) as {
      chunks?: RfqEvidence['chunks'];
      named_identifiers?: string[];
      missing_identifiers?: string[];
      matched_rows?: number;
      rows_in_results?: number;
      workbook?: string | null;
      warning?: string | null;
    };
    return {
      chunks: d.chunks ?? [],
      namedIdentifiers: d.named_identifiers ?? [],
      missingIdentifiers: d.missing_identifiers ?? [],
      matchedRows: d.matched_rows ?? 0,
      rowsInResults: d.rows_in_results ?? 0,
      workbook: d.workbook ?? null,
      warning: d.warning ?? null,
    };
  } catch (err) {
    log.warn(`[RfqChat] evidence failed for rfqId=${rfqId}: ${err}`);
    return null;
  }
}

/**
 * Whether the RFQ has an exported workbook (the bridge's export-status: any of the CBOM, Consolidated BOM or Final Quote).
 * False when the bridge does not answer within the timeout: the picker then shows "no export" rather than a guess.
 */
export async function rfqHasExport(rfqId: string, timeoutMs = 2500): Promise<boolean> {
  try {
    const token = await mintRfqToken(rfqId, timeoutMs);
    const res = await fetch(`${PYTHON_BRIDGE_URL}/api/bom/export-status/${encodeURIComponent(rfqId)}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) return false;
    const d = (await res.json()) as { cbom?: unknown; consolidatedBom?: unknown; quoteSummary?: unknown };
    return !!(d.cbom || d.consolidatedBom || d.quoteSummary);
  } catch {
    return false;
  }
}

/**
 * Retrieves grounding context for a question, scoped to rfqId. Mints its
 * own fresh token (never reuses one across calls — see rfq-chat-client's
 * own module docstring and the 60s TTL this mirrors from apiAuth.ts).
 */
export async function retrieveRfqContext(params: {
  rfqId: string;
  question: string;
  sessionId: string;
  topK?: number;
  nodeSetFilter?: string[];
  timeoutMs?: number;
}): Promise<RfqChatRetrieveResult | null> {
  const { rfqId, question, sessionId, topK, nodeSetFilter, timeoutMs = 10000 } = params;
  try {
    const token = await mintRfqToken(rfqId);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(`${RFQ_MEMORY_CHAT_URL}/rfq/${encodeURIComponent(rfqId)}/chat/retrieve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          question,
          session_id: sessionId,
          top_k: topK,
          node_set_filter: nodeSetFilter ?? null,
        }),
        signal: controller.signal,
      });
      if (!res.ok) {
        log.warn(`[RfqChat] retrieve HTTP ${res.status} for rfqId=${rfqId}`);
        return null;
      }
      const data = (await res.json()) as {
        matched: boolean;
        chunks: Array<{ text: string; citation: MessageCitation; score?: number }>;
        session_recall: string | null;
        warning: string | null;
      };
      return { matched: data.matched, chunks: data.chunks ?? [], sessionRecall: data.session_recall, warning: data.warning };
    } finally {
      clearTimeout(timeout);
    }
  } catch (err) {
    log.warn(`[RfqChat] retrieve failed, falling through: ${err}`);
    return null;
  }
}

/** Fire-and-forget commit of one Q&A turn to session memory. Mints its
 * own fresh token, independent of retrieveRfqContext's — never stretch
 * one token's 60s lifetime across a multi-call turn. */
export function rememberTurn(params: { rfqId: string; sessionId: string; question: string; answer: string }): void {
  const { rfqId, sessionId, question, answer } = params;
  void (async () => {
    try {
      const token = await mintRfqToken(rfqId);
      await fetch(`${RFQ_MEMORY_CHAT_URL}/rfq/${encodeURIComponent(rfqId)}/chat/remember`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ session_id: sessionId, question, answer }),
      });
    } catch (err) {
      log.warn(`[RfqChat] remember failed (non-fatal): ${err}`);
    }
  })();
}
