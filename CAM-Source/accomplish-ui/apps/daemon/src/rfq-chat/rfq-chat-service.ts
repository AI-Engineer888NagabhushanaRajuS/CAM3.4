/**
 * One entry point for every assistant message (HTTP routes and task path). It is a normal chat first (SPEC-019):
 *
 *   greeting / how-to / help        -> the user guide, cited (rfq-chat-guide.ts); no RFQ facts
 *   create an RFQ                   -> the action service, which answers with a confirmation card (never writes here)
 *   open / status / resume / export / upload / settings of an RFQ -> the controls (rfq-chat-controls.ts): database answers,
 *                                      buttons for the user to press, and a confirmation card for the one write (resume)
 *   report or data question         -> needs a scope: none -> RFQ picker; one RFQ -> grounded answer (rfq-chat-grounded.ts);
 *                                      several or all -> per-RFQ table (rfq-chat-multi.ts); unknown RFQ -> choose
 *   anything else                   -> ordinary conversation by the model, checked for data claims (rfq-chat-general.ts)
 *
 * Rules decide first (rfq-chat-intent.ts); the model only chats, phrases guide or evidence rows, or hands a message back
 * as an RFQ-data question. Lists, tables, pickers and refusals need no model.
 */
import { openRouterFailureReason } from './rfq-chat-models.js';
import { answerFromResults, type GroundedDeps } from './rfq-chat-grounded.js';
import { answerFromGuide, loadGuide } from './rfq-chat-guide.js';
import { converse } from './rfq-chat-general.js';
import { controlReply, quoted, unknownRfqReply } from './rfq-chat-controls.js';
import { classify, classifyBase, CREATE_PENDING, filesIntent, mentionsSettings, rfqMentions } from './rfq-chat-intent.js';
import { answerAcrossRfqs, MAX_RFQS, pickRfqDirective } from './rfq-chat-multi.js';
import type { ChatActionDeps, ChatScope } from './rfq-chat-contract.js';
import type { LoadManifests } from './rfq-chat-manifests.js';
import type { RfqStatus } from './rfq-chat-status.js';
import type { ChatModel, ChatReply, RfqSummary, Turn } from './rfq-chat-types.js';

export type { ChatReply, RfqSummary } from './rfq-chat-types.js';

export interface ChatServiceDeps extends Omit<GroundedDeps, 'model'> {
  /** Resolved per question: the key saved in Settings can change at any time. */
  model: () => ChatModel;
  listRfqs: () => Promise<RfqSummary[]>;
  /** Adds hasExport to the options of a picker; only called when a picker is shown. Absent = options say no export. */
  withExports?: (rfqs: RfqSummary[]) => Promise<RfqSummary[]>;
  /** Fire-and-forget: keep a verified exchange in the Cognee session memory. */
  remember?: (p: { rfqId: string; question: string; answer: string }) => void;
  /** Create-RFQ flow (rfq-chat-actions.ts). Absent = the chat says it cannot create RFQs here. */
  actions?: ChatActionDeps;
  /** Who is chatting: binds confirmation tokens to the session. */
  sessionKey?: string;
  /** Pipeline progress of one RFQ from the database (rfq-chat-status.ts). Absent = "where is it?" cannot be answered here. */
  pipelineStatus?: (rfqId: string) => Promise<RfqStatus>;
  /** Manifest tree for "open the ... manifest" (rfq-chat-manifests.ts). */
  manifests?: LoadManifests;
}

export interface ChatParams {
  /** Legacy per-RFQ route: the RFQ in the URL. Same as scope { rfqs, [rfqId] }. */
  rfqId: string | null;
  scope?: ChatScope;
  fileRefs?: Array<{ attachmentId: string; name: string; rfqId?: string }>;
  messages: Turn[];
}

const MAX_QUESTION = 4000; // characters: a question is a sentence, not a document
const LIST_QUESTION = /\b(which|list|how many|show)\b[^.?!]*\brfqs?\b/i;


function table(rfqs: RfqSummary[]): string {
  const rows = rfqs.slice(0, 15).map((r) => `| ${r.rfqId} | ${r.customer ?? '-'} | ${r.project ?? '-'} | ${r.stage ?? '-'} | ${r.reviewPending ? 'yes' : 'no'} |`);
  const more = rfqs.length > 15 ? `\n\n*${rfqs.length - 15} more not shown.*` : '';
  return `| RFQ | Customer | Project | Steps done | Waiting for review |\n|---|---|---|---|---|\n${rows.join('\n')}${more}`;
}

const picker = async (deps: ChatServiceDeps, rfqs: RfqSummary[], reason: string) =>
  pickRfqDirective(deps.withExports ? await deps.withExports(rfqs) : rfqs, reason);

type Talk = (message: string, over?: Partial<ChatReply>) => ChatReply;
interface Ctx {
  deps: ChatServiceDeps;
  question: string;
  history: Turn[];
  incoming: ChatScope;
  talk: Talk;
}

export async function chatReply(p: ChatParams, deps: ChatServiceDeps): Promise<ChatReply> {
  const at = p.messages.map((m) => m.role).lastIndexOf('user');
  const question = at >= 0 ? p.messages[at].content.trim().slice(0, MAX_QUESTION) : '';
  if (!question) {
    throw new Error('No user message found');
  }
  const history = p.messages.slice(0, at);
  const incoming: ChatScope = p.scope ?? (p.rfqId ? { mode: 'rfqs', rfqIds: [p.rfqId] } : { mode: 'none' });
  const talk: Talk = (message, over = {}) => ({
    rfq_id: incoming.mode === 'rfqs' && incoming.rfqIds.length === 1 ? incoming.rfqIds[0] : null,
    message, citations: [], model: null, scope: incoming, ...over,
  });

  // Files are attached and the user says go (or answers the customer/project question): no model decides, the files do.
  const files = p.fileRefs ?? [];
  const single = incoming.mode === 'rfqs' && incoming.rfqIds.length === 1;
  const pending = history.filter((t) => t.role !== 'user').at(-1)?.content.startsWith(CREATE_PENDING) === true;
  let intent = classify(question);
  let request = question;
  if (files.length > 0 && !single && (filesIntent(question) || (pending && ['unsure', 'data', 'create'].includes(intent)))) {
    intent = 'create';
    if (pending) {
      // "customer Acme" or a pressed button is only half a request: read it together with the user's earlier turns.
      request = [...history.filter((t) => t.role === 'user').slice(-4).map((t) => t.content), question].join('\n');
    }
  }
  if (intent === 'open' || intent === 'status' || intent === 'resume' || intent === 'export' || intent === 'upload' || intent === 'settings' || intent === 'edit' || intent === 'manifest' || intent === 'dashboard' || intent === 'price_gate') {
    const done = await controlReply(intent, { deps, question, incoming });
    if (done) {
      return talk(done.message, done);
    }
    intent = classifyBase(question); // nothing to act on (for example a list question): the earlier rules decide
  }
  if (intent === 'guide') {
    const sections = loadGuide();
    if (!sections) {
      return talk("The user guide file is missing on this machine (docs/CAM-3.4-USER-GUIDE.md), so I can't answer how-to questions from it.");
    }
    const a = await answerFromGuide({ question, history, sections }, { model: deps.model(), signal: deps.signal });
    // "how do I add my OpenRouter key?": the steps AND the button that opens the place they point to
    return talk(a.message, { citations: a.citations, model: a.model, ...(mentionsSettings(question) ? { ui: { type: 'open_settings' as const, section: 'providers' as const } } : {}) });
  }
  if (intent === 'create') {
    if (!deps.actions) {
      return talk('Creating an RFQ from the chat is not available here. In the left pane open **Upload file**, then **Create RFQ** (the user guide has the steps).');
    }
    const r = await deps.actions.proposeCreateRfq({ sessionKey: deps.sessionKey ?? 'local', request, fileRefs: files });
    return talk(r.message, { ui: r.ui });
  }
  if (intent === 'unsure') {
    const g = await converse({ question, history, attached: files.map((f) => f.name) }, { model: deps.model(), signal: deps.signal });
    if (g.kind === 'reply') {
      return talk(g.message, { model: g.model });
    }
    if (g.kind === 'offline') {
      const why = openRouterFailureReason();
      return talk(`${why ? `${why} ` : ''}The language model isn't reachable right now, so I can't chat freely. I can still answer how-to questions from the user guide, list your RFQs, and answer from an RFQ's results.`);
    }
    if (g.kind === 'withheld') {
      const rfqs = await deps.listRfqs();
      return talk(`I was about to state ${quoted(g.claims)}, which I can't back with an RFQ's results, so I did not show it. If you meant an RFQ, tell me which one.`, rfqs.length ? { ui: await picker(deps, rfqs, 'Pick the RFQ you mean') } : {});
    }
    // g.kind === 'needs_data': the model says this is an RFQ-data question
  }
  return dataReply({ deps, question, history, incoming, talk });
}

/** A question about RFQ data: decide the scope, then answer from the results or ask the user to choose. */
async function dataReply({ deps, question, history, incoming, talk }: Ctx): Promise<ChatReply> {
  const rfqs = await deps.listRfqs();
  const ids = rfqs.map((r) => r.rfqId);
  const mention = rfqMentions(question, ids);
  if (mention.unknown.length > 0) {
    const u = unknownRfqReply(mention.unknown, rfqs);
    return talk(u.message, u);
  }

  // an RFQ the question names wins over the chips; otherwise the chips; otherwise one named earlier ("and the MOQ again?")
  let scope: ChatScope = mention.known.length ? { mode: 'rfqs', rfqIds: mention.known } : incoming;
  if (scope.mode === 'none') {
    for (const turn of [...history].reverse().filter((t) => t.role === 'user')) {
      const earlier = rfqMentions(turn.content, ids).known[0];
      if (earlier) { scope = { mode: 'rfqs', rfqIds: [earlier] }; break; }
    }
  }

  if (scope.mode === 'none' || (scope.mode === 'rfqs' && scope.rfqIds.length === 0) || (scope.mode === 'all' && rfqs.length === 0)) {
    if (rfqs.length === 0) {
      return talk('There are no RFQs yet. Create one in the left pane (Upload file, then Create RFQ), or ask me to create one.', { rfq_id: null, scope: { mode: 'none' } });
    }
    const listing = LIST_QUESTION.test(question) ? `Here ${rfqs.length === 1 ? 'is the RFQ' : 'are the RFQs'} I can see:\n\n${table(rfqs)}\n\n` : '';
    return talk(`${listing}Which RFQ do you mean? Pick one or more in the list, or press **All context**, and then ask.`, {
      rfq_id: null,
      scope: { mode: 'none' },
      ui: await picker(deps, rfqs, 'Which RFQs should I look at?'),
    });
  }

  if (scope.mode === 'rfqs' && scope.rfqIds.length === 1) {
    const rfqId = scope.rfqIds[0];
    const { model, listRfqs: _list, withExports: _w, remember, actions: _actions, sessionKey: _key, pipelineStatus: _status, manifests: _manifests, ...rest } = deps;
    const answer = await answerFromResults({ rfqId, question, history }, { ...rest, model: model() });
    if (answer.citations.length > 0) {
      remember?.({ rfqId, question, answer: answer.message });
    }
    return { rfq_id: rfqId, message: answer.message, citations: answer.citations, model: answer.model, scope };
  }

  const chosen = scope.mode === 'rfqs' ? scope.rfqIds : ids;
  if (chosen.length > MAX_RFQS) {
    return talk(`That is ${chosen.length} RFQs, and one answer can span at most ${MAX_RFQS}. Pick fewer, or name the customer or project you care about.`, {
      rfq_id: null,
      scope: { mode: 'none' },
      ui: await picker(deps, rfqs, `Choose up to ${MAX_RFQS} RFQs`),
    });
  }
  return answerAcrossRfqs(
    { ids: chosen, all: scope.mode === 'all', question, history, named: mention.known.length > 1 },
    { retrieve: deps.retrieve },
  );
}
