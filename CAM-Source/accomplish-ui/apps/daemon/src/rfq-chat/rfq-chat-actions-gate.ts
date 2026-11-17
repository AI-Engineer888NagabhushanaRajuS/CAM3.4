/**
 * The price-source gate from the chat, through the price-gate MCP server (mcp-tools/price-gate). Reading the conflicts is free;
 * recording a source for them is a write, so it is a confirmation card like every other write here: planResolveConflicts
 * builds the card, runResolveConflicts runs when the person presses Confirm. It resumes the run only when nothing is pending.
 */
import type { ActionConfirmResponse } from './rfq-chat-contract.js';
import { callMcpTool } from './rfq-chat-mcp-client.js';

export const PRICE_GATE_MCP_URL = process.env.PRICE_GATE_MCP_URL ?? 'http://localhost:18110/mcp';

export const GATE_SOURCES = ['costing', 'erp', 'qw'] as const;
export type GateSource = (typeof GATE_SOURCES)[number];
export const GATE_LABEL: Record<GateSource, string> = { costing: 'Costing sheet', erp: 'ERP', qw: 'QuoteWin' };

export interface GateItem {
  conflict_id: string;
  cpn: string | null;
  volume_no: string | null;
  available_sources: Partial<Record<GateSource, { price_conv?: number | null }>> | null;
}

export interface ResolveConflictsParams {
  rfqId: string;
  source: GateSource;
  conflictIds: string[];
  parts: number;
}

interface Page {
  items: GateItem[];
  next_cursor: string | null;
}

/** Every pending conflict of the RFQ, page by page (the review screen reads the same way). */
export async function readAllConflicts(rfqId: string): Promise<GateItem[]> {
  const out: GateItem[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < 50; page += 1) {
    const args: Record<string, unknown> = { rfq_id: rfqId, limit: 500 };
    if (cursor) args.cursor = cursor;
    const res: Page = await callMcpTool<Page>(PRICE_GATE_MCP_URL, 'list_price_conflicts', args);
    out.push(...res.items);
    if (!res.next_cursor) break;
    cursor = res.next_cursor;
  }
  return out;
}

const priceOf = (item: GateItem, source: GateSource): number | null => {
  const v = item.available_sources?.[source]?.price_conv;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
};

/** The card for "use <source> for the price conflicts of RFQ-x", or the reason there is none to issue. */
export async function planResolveConflicts(rfqId: string, source: GateSource): Promise<{ message: string; params?: ResolveConflictsParams; summary?: string }> {
  const items = await readAllConflicts(rfqId);
  if (items.length === 0) {
    return { message: `Nothing is waiting at the price-source gate for ${rfqId}, so there is nothing to resolve.` };
  }
  const without = items.filter((i) => priceOf(i, source) === null);
  if (without.length > 0) {
    return {
      message: `${without.length} of the ${items.length} conflicts have no ${GATE_LABEL[source]} price, so ${GATE_LABEL[source]} cannot be used for them. Choose another source, or resolve them row by row on the review screen.`,
    };
  }
  const parts = new Set(items.map((i) => i.cpn ?? '')).size;
  const params: ResolveConflictsParams = { rfqId, source, conflictIds: items.map((i) => i.conflict_id), parts };
  return {
    message: `Use the ${GATE_LABEL[source]} price for all ${items.length} conflicts (${parts} parts) in ${rfqId}. Press Confirm to record it and carry the run on; nothing happens until you do.`,
    params,
    summary: `Record ${GATE_LABEL[source]} as the price source for ${items.length} conflicts of ${rfqId}, then resume the run if nothing else is pending.`,
  };
}

/** Runs when Confirm is pressed: re-check what is pending, record the source, resume only when the gate is clear. */
export async function runResolveConflicts(
  p: ResolveConflictsParams,
  actor: { email: string } | undefined,
  audit: (action: string, result: string) => Promise<void>,
): Promise<ActionConfirmResponse> {
  const steps: ActionConfirmResponse['steps'] = [];
  const stop = async (name: string, why: string, message: string): Promise<ActionConfirmResponse> => {
    steps.push({ step: name, status: 'failed', detail: why });
    await audit(`resolve_conflicts.${name}`, `failed: ${why}`);
    return { ok: false, rfqId: p.rfqId, message, steps };
  };
  if (!actor?.email) {
    return stop('check_state', 'no signed-in email', 'Stopped: the decisions are recorded with the signed-in email, and none is known. Nothing was changed.');
  }
  let pending: GateItem[];
  try {
    pending = await readAllConflicts(p.rfqId);
  } catch (err) {
    return stop('check_state', err instanceof Error ? err.message : String(err), `Stopped at check_state: ${err instanceof Error ? err.message : err}. Nothing was changed.`);
  }
  const still = new Set(pending.map((i) => i.conflict_id));
  const todo = p.conflictIds.filter((id) => still.has(id));
  if (todo.length === 0) {
    return { ok: true, rfqId: p.rfqId, message: `The conflicts of ${p.rfqId} were already resolved; nothing was changed.`, steps };
  }
  steps.push({ step: 'check_state', status: 'done', detail: `${todo.length} conflicts still pending` });
  await audit('resolve_conflicts.check_state', 'done');

  try {
    await callMcpTool(PRICE_GATE_MCP_URL, 'resolve_price_conflicts', {
      rfq_id: p.rfqId,
      resolutions: todo.map((conflict_id) => ({ conflict_id, resolved_source: p.source })),
      resolved_by: actor.email,
    });
  } catch (err) {
    return stop('resolve', err instanceof Error ? err.message : String(err), `Stopped at resolve: ${err instanceof Error ? err.message : err}. Nothing was resumed.`);
  }
  steps.push({ step: 'resolve', status: 'done', detail: `${GATE_LABEL[p.source]} recorded for ${todo.length} conflicts` });
  await audit('resolve_conflicts.resolve', `done: ${todo.length} ${p.source}`);

  const after = await readAllConflicts(p.rfqId).catch(() => null);
  if (!after) {
    return { ok: true, rfqId: p.rfqId, message: `Recorded ${GATE_LABEL[p.source]} for ${todo.length} conflicts of ${p.rfqId}. I could not re-read the gate, so the run was not resumed; check the review screen.`, steps };
  }
  if (after.length > 0) {
    return { ok: true, rfqId: p.rfqId, message: `Recorded ${GATE_LABEL[p.source]} for ${todo.length} conflicts of ${p.rfqId}. ${after.length} are still pending, so the run stays at the gate.`, steps };
  }
  try {
    const started = await callMcpTool<{ status?: string; outcome?: string }>(PRICE_GATE_MCP_URL, 'resume_price_gate', { rfq_id: p.rfqId });
    steps.push({ step: 'resume', status: 'done', detail: started.outcome ?? started.status ?? 'sent' });
    await audit('resolve_conflicts.resume', `done: ${started.outcome ?? started.status ?? 'sent'}`);
    return { ok: true, rfqId: p.rfqId, message: `Recorded ${GATE_LABEL[p.source]} for every conflict of ${p.rfqId} and resumed the run. Follow the steps in the right pane.`, steps };
  } catch (err) {
    return stop('resume', err instanceof Error ? err.message : String(err), `The conflicts are recorded, but the run did not resume: ${err instanceof Error ? err.message : err}. Resume it from the left pane.`);
  }
}
