/**
 * One entry point for every RFQ-assistant question (HTTP route and task path): picks the RFQ the question is about and
 * answers from that RFQ's results (rfq-chat-grounded.ts). With no RFQ in play it answers from the list of RFQs, which
 * needs no model at all. The model is never asked anything that is not backed by rows.
 */
import { answerFromResults, GREETING, type GroundedDeps } from './rfq-chat-grounded.js';
import type { ChatModel, GroundedAnswer, Turn } from './rfq-chat-types.js';

export interface RfqSummary {
  rfqId: string;
  customer: string | null;
  project: string | null;
  /** Pipeline steps finished (rfq_process_tracking.rfq_process_stage); null before the pipeline started. */
  stage: number | null;
  reviewPending: boolean;
}

export interface ChatServiceDeps extends Omit<GroundedDeps, 'model'> {
  /** Resolved per question: the key saved in Settings can change at any time. */
  model: () => ChatModel;
  listRfqs: () => Promise<RfqSummary[]>;
  /** Fire-and-forget: keep a verified exchange in the Cognee session memory. */
  remember?: (p: { rfqId: string; question: string; answer: string }) => void;
}

export interface ChatReply {
  rfq_id: string | null;
  message: string;
  citations: GroundedAnswer['citations'];
  model: string | null;
}

const RFQ_MENTION = /\bRFQ-\d{3,}\b/gi;
const MAX_QUESTION = 4000; // characters: a question is a sentence, not a document

function table(rfqs: RfqSummary[]): string {
  const rows = rfqs.slice(0, 15).map((r) => `| ${r.rfqId} | ${r.customer ?? '-'} | ${r.project ?? '-'} | ${r.stage ?? '-'} | ${r.reviewPending ? 'yes' : 'no'} |`);
  const more = rfqs.length > 15 ? `\n\n*${rfqs.length - 15} more not shown.*` : '';
  return `| RFQ | Customer | Project | Steps done | Waiting for review |\n|---|---|---|---|---|\n${rows.join('\n')}${more}`;
}

export async function chatReply(p: { rfqId: string | null; messages: Turn[] }, deps: ChatServiceDeps): Promise<ChatReply> {
  const at = p.messages.map((m) => m.role).lastIndexOf('user');
  const question = at >= 0 ? p.messages[at].content.trim().slice(0, MAX_QUESTION) : '';
  if (!question) throw new Error('No user message found');
  const history = p.messages.slice(0, at);

  let rfqId = p.rfqId;
  let rfqs: RfqSummary[] = [];
  if (!rfqId) {
    rfqs = await deps.listRfqs();
    const known = new Map(rfqs.map((r) => [r.rfqId.toLowerCase(), r.rfqId]));
    const recentFirst = [question, ...history.filter((t) => t.role === 'user').map((t) => t.content).reverse()];
    rfqId = recentFirst.flatMap((t) => t.match(RFQ_MENTION) ?? []).map((m) => known.get(m.toLowerCase())).find(Boolean) ?? null;
  }

  if (rfqId) {
    const { model, listRfqs: _list, remember, ...rest } = deps;
    const answer = await answerFromResults({ rfqId, question, history }, { ...rest, model: model() });
    if (answer.citations.length > 0) remember?.({ rfqId, question, answer: answer.message });
    return { rfq_id: rfqId, message: answer.message, citations: answer.citations, model: answer.model };
  }

  const first = rfqs[0]?.rfqId ?? 'RFQ-00001';
  const listing = rfqs.length ? `\n\n${table(rfqs)}` : '\n\nThere are no RFQs yet: create one on the left and upload its files.';
  const message = GREETING.test(question)
    ? `Hi! Pick an RFQ on the left, or name one (for example **${first}**), and I will answer from its results.${listing}`
    : /\b(rfqs?|list|which|how many|status|all|show)\b/i.test(question)
      ? `Here ${rfqs.length === 1 ? 'is the RFQ' : 'are the RFQs'} I can see:${listing}`
      : `Which RFQ do you mean? I answer only from an RFQ's results, so pick one on the left or name it (for example **${first}**).${listing}`;
  return { rfq_id: null, message, citations: [], model: null };
}
