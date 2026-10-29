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

// NetBird mesh IP (stable regardless of physical LAN IP changes), matching
// manage_backend.py's SERVICES entries for python_bridge/rfq_memory_server.
const PYTHON_BRIDGE_URL = (process.env.PYTHON_BRIDGE_URL ?? 'http://100.121.36.255:3110').replace(/\/$/, '');
const RFQ_MEMORY_CHAT_URL = (process.env.RFQ_MEMORY_CHAT_URL ?? 'http://100.121.36.255:8108').replace(/\/$/, '');

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
