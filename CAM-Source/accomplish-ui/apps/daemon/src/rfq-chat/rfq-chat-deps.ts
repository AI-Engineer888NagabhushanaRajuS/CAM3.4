/**
 * Wires the RFQ assistant to what the daemon owns: the OpenRouter key and model chosen in Settings, the RFQ tables in
 * Postgres, and the optional Cognee memory service. The route and the task path both build their deps here, so there is
 * one definition of "which model answers" and "what is an RFQ".
 */
import { log } from '../logger.js';
import { resolveChatModel, type ChatProviderMode } from './rfq-chat-models.js';
import { makeChatActions } from './rfq-chat-actions.js';
import { loadManifestTree } from './rfq-chat-manifests.js';
import { fetchRfqStatus, loadStepHistory } from './rfq-chat-status.js';
import { stepChunks } from './rfq-chat-dashboard.js';
import { rememberTurn, retrieveDashboardEvidence, retrieveRfqContext, rfqHasExport } from './rfq-chat-client.js';
import type { ChatActionDeps } from './rfq-chat-contract.js';
import type { ChatServiceDeps, RfqSummary } from './rfq-chat-service.js';

export interface ChatDepsSource {
  getApiKey: (provider: string) => string | null;
  getSelectedModel: () => { provider: string; model: string } | null;
}

async function listRfqs(): Promise<RfqSummary[]> {
  try {
    const { fileMetadataPool } = await import('../db.js'); // loaded on first use: db.ts refuses to load without its env vars
    const { rows } = await fileMetadataPool.query(
      `SELECT COALESCE(p.rfq_id, t.rfq_id) AS rfq_id, p.customer_name, p.project_name, t.rfq_process_stage, t.hitl_required
         FROM rfq_project_tracking p
         FULL OUTER JOIN (SELECT * FROM rfq_process_tracking WHERE is_active) t ON t.rfq_id = p.rfq_id
        ORDER BY 1 DESC LIMIT 500`,
    );
    return rows.map((r) => ({
      rfqId: String(r.rfq_id),
      customer: r.customer_name ?? null,
      project: r.project_name ?? null,
      stage: typeof r.rfq_process_stage === 'number' ? r.rfq_process_stage : null,
      reviewPending: r.hitl_required === true,
    }));
  } catch (err) {
    log.warn(`[RfqChat] could not list RFQs: ${err}`);
    return [];
  }
}

const EXPORT_CHECKED = 60; // ponytail: the 60 newest RFQs only (two bridge calls each); older ones read "no export" until the bridge reports it in one call

/** The picker shows which RFQs have an exported workbook (the only ones whose numbers can be answered). Called only when a picker opens. */
async function withExports(rfqs: RfqSummary[]): Promise<RfqSummary[]> {
  const head = await Promise.all(rfqs.slice(0, EXPORT_CHECKED).map(async (r) => ({ ...r, hasExport: await rfqHasExport(r.rfqId) })));
  return [...head, ...rfqs.slice(EXPORT_CHECKED)];
}

/** One instance for the daemon: its confirmation tokens must survive between the chat request that issues a card and the confirm request. */
let sharedActions: ChatActionDeps | null = null;

/** `sessionKey` keeps two people's conversations about the same RFQ apart in Cognee's session memory. */
export function makeChatDeps(src: ChatDepsSource, sessionKey: string, signal?: AbortSignal, provider?: ChatProviderMode): ChatServiceDeps {
  const sessionId = (rfqId: string) => `rfq-chat-${rfqId}-${sessionKey}`;
  return {
    model: () => resolveChatModel({ settingsKey: src.getApiKey('openrouter'), selected: src.getSelectedModel(), mode: provider }),
    listRfqs,
    withExports,
    actions: (sharedActions ??= makeChatActions(src)),
    // The dashboard's numbers (3D rows, cards, matrix) and the live feed's steps, so "explain this" can be answered from either.
    dashboard: async (rfqId) => [
      ...(await retrieveDashboardEvidence(rfqId)),
      ...stepChunks(rfqId, await loadStepHistory(rfqId).catch(() => [])),
    ],
    sessionKey,
    pipelineStatus: (rfqId) => fetchRfqStatus(rfqId),
    manifests: loadManifestTree,
    signal,
    memory: async ({ rfqId, question }) => {
      // Cognee's search takes seconds with session caching off (see docker-compose.yml); 30 s leaves room under load. It runs beside the DuckDB evidence.
      const r = await retrieveRfqContext({ rfqId, question, sessionId: sessionId(rfqId), topK: 6, timeoutMs: 30000 });
      return r ? { chunks: r.chunks.map((c) => ({ text: c.text, citation: { ...c.citation } })), sessionRecall: r.sessionRecall } : null;
    },
    // Off by default: each write makes Cognee run LLM extraction on the same Ollama that answers the user, and on one
    // 8 GB GPU the queued extraction jobs starve the answer (observed 2026-11-05: 9m50s 500s, answers timing out).
    remember: process.env.RFQ_CHAT_MEMORY_WRITE === '1'
      ? ({ rfqId, question, answer }) => rememberTurn({ rfqId, sessionId: sessionId(rfqId), question, answer })
      : undefined,
  };
}
