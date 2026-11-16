/**
 * Ordinary conversation: the model talks, but it has no RFQ data here, so it must not state any. A reply is checked in
 * "no data claims" mode (rfq-chat-verify.ts figures and part-number-like tokens, plus RFQ ids): anything that is not in
 * the user's own words is rejected, the model is asked once more, and if it still slips the reply is withheld.
 * The same single call doubles as the classifier for messages the rules were unsure about: a model that sees the user
 * is asking for RFQ data answers NEEDS_RFQ_DATA and the service routes it to the RFQ flow.
 */
import { unverifiedFigures } from './rfq-chat-verify.js';
import type { ChatMessage, ChatModel, Turn } from './rfq-chat-types.js';

export const NEEDS_RFQ_DATA = 'NEEDS_RFQ_DATA';

export const GENERAL_PROMPT = [
  'You are the assistant inside CAM4, a tool that turns a customer BOM into a costed quote. Chat naturally and briefly in the language style of the user.',
  'Rules:',
  '1. You have NO access to any RFQ, BOM, price, supplier, lead time or part here. Never state, guess or recall any fact, figure, part number or RFQ id about them.',
  `2. If the user asks about the contents, status, costs, parts or numbers of a particular RFQ, BOM or report, reply with exactly ${NEEDS_RFQ_DATA} and nothing else.`,
  '3. Questions about how to use the tool are answered from its user guide elsewhere; do not describe screens or buttons yourself.',
  '4. Only repeat numbers or ids the user wrote in their own message.',
].join('\n');

const RFQ_ID = /\bRFQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*/gi;
// "CAM4" is the product name, not a figure; small counts ("2 ways") are ordinary talk, 3+ digits are data-like.
const PRODUCT = 'CAM4';
const SMALL_COUNT = /^\d{1,2}$/;

/** RFQ ids, part-number-like tokens and figures in `reply` that the user did not write themselves. */
export function dataClaims(reply: string, userText: string): string[] {
  const allowed = `${userText}\n${PRODUCT}`;
  const ids = (reply.match(RFQ_ID) ?? []).filter((t) => !allowed.toLowerCase().includes(t.toLowerCase()));
  const rest = unverifiedFigures(reply.replaceAll(PRODUCT, ' '), [], allowed).filter((t) => !SMALL_COUNT.test(t));
  return [...new Set([...ids, ...rest])];
}

/** The model must never say it has no files while the chat shows them: the assistant handles them itself, by rules. */
export const attachedNote = (names: string[]): string =>
  `5. The user has attached ${names.length} file${names.length === 1 ? '' : 's'} (${names.slice(0, 12).join(', ')}), already scanned and released. You cannot read them, but the assistant can: when the user wants them processed or used they say so (for example "process these files") and the assistant reads them itself. Never say the files are missing.`;

export type General = { kind: 'reply'; message: string; model: string } | { kind: 'needs_data' } | { kind: 'offline' } | { kind: 'withheld'; claims: string[] };

export async function converse(
  p: { question: string; history: Turn[]; /** Names of the files the user attached to this turn (already scanned and released). */ attached?: string[] },
  deps: { model: ChatModel; signal?: AbortSignal },
): Promise<General> {
  const userText = [...p.history, { role: 'user', content: p.question }].filter((t) => t.role === 'user').map((t) => t.content).join('\n');
  const base: ChatMessage[] = [
    { role: 'system', content: p.attached?.length ? `${GENERAL_PROMPT}\n${attachedNote(p.attached)}` : GENERAL_PROMPT },
    ...p.history.slice(-4).map((t) => ({ role: (t.role === 'user' ? 'user' : 'assistant') as ChatMessage['role'], content: t.content.slice(0, 600) })),
    { role: 'user', content: p.question },
  ];
  let answer = await deps.model.complete(base, deps.signal);
  let claims: string[] = [];
  for (let attempt = 0; attempt < 2; attempt++) {
    if (answer === null) {
      return { kind: 'offline' };
    }
    if (answer.text.includes(NEEDS_RFQ_DATA)) {
      return { kind: 'needs_data' };
    }
    claims = dataClaims(answer.text, userText);
    if (claims.length === 0) {
      return { kind: 'reply', message: answer.text, model: answer.model };
    }
    if (attempt === 1) {
      break;
    }
    answer = await deps.model.complete([
      ...base,
      { role: 'assistant', content: answer.text },
      { role: 'user', content: `Your reply contains ${claims.join(', ')}, which I did not write and you cannot know. Reply again without any RFQ ids, part numbers or figures, or reply ${NEEDS_RFQ_DATA} if I asked for RFQ data.` },
    ], deps.signal);
  }
  return { kind: 'withheld', claims };
}
