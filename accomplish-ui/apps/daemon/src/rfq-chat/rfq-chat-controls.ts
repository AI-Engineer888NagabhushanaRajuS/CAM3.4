/**
 * The assistant's controls over the app (SPEC-019 section A, "assistant controls the app"): open an RFQ, say where its
 * pipeline is, resume it, open its downloads, pick files, open Settings. Rules decide (rfq-chat-intent.ts) and the answer
 * comes from the database or a fixed one-liner, never from a model. Every write goes through the confirmation card of the
 * action service; the other controls only hand the UI a button (open_rfq, open_export, ask_upload, open_settings) that the
 * user presses. A handler returns null when it cannot act (the service then treats the message as before).
 */
import type { ChatActionDeps, ChatScope, UiDirective } from './rfq-chat-contract.js';
import { rfqMentions, type ControlIntent } from './rfq-chat-intent.js';
import { describeStatus, type RfqStatus } from './rfq-chat-status.js';
import type { ChatReply, RfqSummary } from './rfq-chat-types.js';

export interface ControlDeps {
  listRfqs: () => Promise<RfqSummary[]>;
  withExports?: (rfqs: RfqSummary[]) => Promise<RfqSummary[]>;
  actions?: ChatActionDeps;
  sessionKey?: string;
  /** Pipeline progress of one RFQ from the database; absent = the chat cannot read it here. */
  pipelineStatus?: (rfqId: string) => Promise<RfqStatus>;
}

export const quoted = (items: string[]): string => items.map((i) => `\`${i}\``).join(', ');
const detail = (r: RfqSummary) => [r.customer, r.project].filter(Boolean).join(' · ') || undefined;
const choices = (rfqs: RfqSummary[]): UiDirective => ({
  type: 'disambiguate',
  prompt: 'Which RFQ do you mean?',
  options: rfqs.slice(0, 8).map((r) => ({ id: r.rfqId, label: r.rfqId, detail: detail(r) })),
});

/** An RFQ-looking id that is not in the list: say so and offer the real ones (shared with the data path). */
export function unknownRfqReply(unknown: string[], rfqs: RfqSummary[]): Pick<ChatReply, 'message' | 'rfq_id' | 'scope' | 'ui'> {
  return {
    message: `I can't find ${quoted(unknown)} in the RFQ list. Choose one of these, or check the spelling.`,
    rfq_id: null,
    scope: { mode: 'none' },
    ui: rfqs.length ? choices(rfqs) : undefined,
  };
}

const ACCEPT = ['.xlsx', '.xls', '.csv', '.pdf', '.docx', '.txt'];
const PURPOSE = 'Choose the files to attach. Both security engines (BuLL*Sav and Repel) scan every file first, and only clean files reach the chat.';
const SETTINGS_NOTE = 'The Local / OpenRouter / Auto switch is in the assistant header; the OpenRouter API key is saved in Settings, Providers.';

type Found = { rfq: RfqSummary } | { reply: Partial<ChatReply> & { message: string } };

/** The RFQ a control is about: the one the message names, else the single scoped RFQ; a reply when it is unknown or unclear. */
function pickRfq(question: string, incoming: ChatScope, rfqs: RfqSummary[], what: string): Found | null {
  const mention = rfqMentions(question, rfqs.map((r) => r.rfqId));
  if (mention.unknown.length > 0) {
    return { reply: unknownRfqReply(mention.unknown, rfqs) };
  }
  let named = mention.known;
  if (named.length === 0 && incoming.mode === 'rfqs' && incoming.rfqIds.length === 1) {
    named = incoming.rfqIds; // "what stage is it at?": the one RFQ the chat is scoped to
  }
  if (named.length === 1) {
    const rfq = rfqs.find((r) => r.rfqId === named[0]);
    return rfq ? { rfq } : { reply: unknownRfqReply(named, rfqs) };
  }
  if (named.length > 1) {
    return { reply: { message: `That names ${named.length} RFQs; I ${what} one at a time. Which one?`, ui: choices(rfqs.filter((r) => named.includes(r.rfqId))) } };
  }
  return null;
}

export async function controlReply(
  intent: ControlIntent,
  c: { deps: ControlDeps; question: string; incoming: ChatScope },
): Promise<Partial<ChatReply> & { message: string } | null> {
  const { deps, question, incoming } = c;
  if (intent === 'upload') {
    return { message: `${PURPOSE} Press the button to choose them.`, ui: { type: 'ask_upload', accept: ACCEPT, purpose: PURPOSE } };
  }
  if (intent === 'settings') {
    return { message: `Press the button to open Settings, Providers. ${SETTINGS_NOTE}`, ui: { type: 'open_settings', section: 'providers' } };
  }
  const rfqs = await deps.listRfqs();
  const found = pickRfq(question, incoming, rfqs, { open: 'open', status: 'check', resume: 'start', export: 'export' }[intent]);
  if (!found) {
    // Nothing named and nothing scoped. A list question ("which RFQs are waiting for review?") stays a data question.
    if (intent === 'status' && /\brfqs\b/i.test(question)) {
      return null;
    }
    if (rfqs.length === 0) {
      return { message: 'There are no RFQs yet. Create one first (ask me to create one, or use Upload file in the left pane).' };
    }
    return { message: `Which RFQ? Choose one, or name it in your message (for example "${intent} ${rfqs[0].rfqId}").`, ui: choices(rfqs) };
  }
  if ('reply' in found) {
    return found.reply;
  }
  const { rfq } = found;
  const label = `${rfq.rfqId}${detail(rfq) ? ` (${detail(rfq)})` : ''}`;
  const mine = { rfq_id: rfq.rfqId };

  if (intent === 'open') {
    return { ...mine, message: `Press the button to open ${label} in the left and right panes. I do not change the screen myself.`, ui: { type: 'open_rfq', rfqId: rfq.rfqId } };
  }
  if (intent === 'status') {
    if (!deps.pipelineStatus) {
      return { ...mine, message: `I can't read the pipeline status of ${rfq.rfqId} here.` };
    }
    return { ...mine, message: describeStatus(await deps.pipelineStatus(rfq.rfqId)) };
  }
  if (intent === 'export') {
    const [withExport] = deps.withExports ? await deps.withExports([rfq]) : [rfq];
    return withExport?.hasExport
      ? { ...mine, message: `${label} has exported reports. Press the button to open the downloads.`, ui: { type: 'open_export', rfqId: rfq.rfqId } }
      : { ...mine, message: `${label} has no exported reports yet, so there is nothing to download. They appear when the pipeline reaches Quote Readiness.` };
  }
  if (!deps.actions) {
    return { ...mine, message: 'Starting a pipeline from the chat is not available here. Open the RFQ in the left pane and press Continue.' };
  }
  const r = await deps.actions.proposeStartPipeline({ sessionKey: deps.sessionKey ?? 'local', rfqId: rfq.rfqId });
  return { ...mine, message: r.message, ui: r.ui };
}
