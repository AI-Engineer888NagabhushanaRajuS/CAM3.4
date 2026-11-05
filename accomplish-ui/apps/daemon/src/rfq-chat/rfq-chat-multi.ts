/**
 * Several RFQs or "All context": each RFQ's own evidence (retrieveRfqEvidence, one call per RFQ), shown as a per-RFQ
 * table with the RFQ id in every citation. No model is involved: the table copies the best-matching rows verbatim, and
 * every cell is re-checked against its row with rfq-chat-verify.ts. Conflicts (same part, different values) are stated
 * with both sides cited and handed back to the user as a choice; a part named in the question that no RFQ has is refused.
 */
import { retrieveRfqEvidence, type RfqEvidence } from './rfq-chat-client.js';
import { identifiers, retrievalQuery, type GroundedDeps } from './rfq-chat-grounded.js';
import { findConflicts, type Conflict, type EvidenceRow } from './rfq-chat-conflicts.js';
import { unverifiedByLine } from './rfq-chat-verify.js';
import type { UiDirective } from './rfq-chat-contract.js';
import type { ChatReply, RfqSummary, Turn } from './rfq-chat-types.js';

export const MAX_RFQS = 25; // SPEC-019 V: more than this in one answer and the user is asked to narrow (checked by the service)
const FETCH_ROWS = 6; // best-matching rows asked of each RFQ (conflicts are looked for in all of them)
const SHOWN_ROWS = 2; // rows displayed per RFQ in the table
const CELL_CHARS = 160;
const BATCH = 5; // RFQs queried at once: the bridge mints a token and runs a search per RFQ

export function pickRfqDirective(rfqs: RfqSummary[], reason: string): UiDirective {
  return { type: 'pick_rfq', reason, options: rfqs.map((r) => ({ ...r, hasExport: r.hasExport ?? false })), allowAll: true, allowMultiple: true };
}

/** Whole `key=value` fields only, so a figure is never cut in half. */
function clip(text: string): string {
  const fields = text.replace(/^[^:]*: /, '').split('; ');
  let out = fields[0];
  for (const f of fields.slice(1)) {
    if (out.length + 2 + f.length > CELL_CHARS) {
      break;
    }
    out += `; ${f}`;
  }
  return out;
}

const cell = (s: string) => s.replace(/\|/g, '\\|').replace(/\s*\n\s*/g, ' ');
const quoted = (items: string[]) => items.map((i) => `\`${i}\``).join(', ');

interface Got {
  rfqId: string;
  ev: RfqEvidence | null;
  rows: EvidenceRow[];
}

async function fetchAll(ids: string[], question: string, deps: Pick<GroundedDeps, 'retrieve'>): Promise<Got[]> {
  const retrieve = deps.retrieve ?? retrieveRfqEvidence;
  const out: Got[] = [];
  for (let i = 0; i < ids.length; i += BATCH) {
    out.push(...(await Promise.all(ids.slice(i, i + BATCH).map(async (rfqId) => {
      const ev = await retrieve({ rfqId, question, topK: FETCH_ROWS });
      const rows = (ev?.chunks ?? [])
        .filter((c) => c.citation.label !== 'Workbook tabs')
        .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
        .map((c) => ({ rfqId, text: c.text, citation: { ...c.citation, label: `${rfqId} · ${c.citation.label}`, identifier: { ...c.citation.identifier, rfqId } } }));
      return { rfqId, ev, rows };
    }))));
  }
  return out;
}

function conflictBlock(conflicts: Conflict[]): string {
  const lines = conflicts.slice(0, 6).flatMap((c) =>
    c.sides.map((s) => `| ${cell(c.part)} | ${cell(c.field)} | ${s.rfqId} | ${cell(s.value)} | ${cell(s.citation.label)} |`));
  return `**The results disagree.** The same part has different values:\n\n| Part | Field | RFQ | Value | Source |\n|---|---|---|---|---|\n${lines.join('\n')}`;
}

export async function answerAcrossRfqs(
  p: { ids: string[]; all: boolean; question: string; history: Turn[]; named: boolean },
  deps: Pick<GroundedDeps, 'retrieve'>,
): Promise<ChatReply> {
  const scope = p.all ? ({ mode: 'all' } as const) : ({ mode: 'rfqs', rfqIds: p.ids } as const);
  const base = { rfq_id: null, model: null, scope };
  const got = await fetchAll(p.ids, retrievalQuery(p.question, p.history), deps);
  // lower-cased for comparing, shown as the user wrote it
  const shown = new Map([...identifiers(p.question), ...got.flatMap((g) => g.ev?.namedIdentifiers ?? [])].map((n) => [n.toLowerCase(), n] as const).reverse());
  const named = [...shown.keys()];
  const label = (n: string) => shown.get(n.toLowerCase()) ?? n;
  const reachable = got.filter((g) => g.ev !== null);
  if (reachable.length === 0) {
    return { ...base, message: "I can't reach the results service right now, so I can't answer across these RFQs. Nothing was guessed. Please try again in a moment.", citations: [] };
  }
  const missingEverywhere = (g: Got) => named.length > 0 && named.every((n) => (g.ev?.missingIdentifiers ?? []).some((m) => m.toLowerCase() === n));
  if (reachable.every(missingEverywhere)) {
    return { ...base, message: `I can't find ${quoted(named.map(label))} in the results of any of the ${got.length} RFQs (${got.map((g) => g.rfqId).join(', ')}). Check the spelling, or ask what the results do contain.`, citations: [] };
  }

  const citations: ChatReply['citations'] = [];
  const lines = got.map((g) => {
    if (g.ev === null) {
      return `| ${g.rfqId} | Results service not reachable | - |`;
    }
    if (missingEverywhere(g)) {
      return `| ${g.rfqId} | Not in this RFQ's results: ${cell(quoted(named.map(label)))} | - |`;
    }
    if (g.rows.length === 0) {
      return `| ${g.rfqId} | ${cell(g.ev.warning ?? 'No results I can read yet')} | - |`;
    }
    const shown = g.rows.slice(0, SHOWN_ROWS);
    const cells = shown.map((r) => {
      const text = clip(r.text);
      return unverifiedByLine(text, [r]).length === 0 ? text : '(a figure in this row could not be verified; see the source cell)';
    });
    citations.push(...shown.map((r) => r.citation));
    return `| ${g.rfqId} | ${cells.map(cell).join('<br>')} | ${shown.map((r) => cell(r.citation.label.replace(`${g.rfqId} · `, ''))).join('<br>')} |`;
  });
  const head = p.all ? `Across all ${got.length} RFQs` : `Across ${got.length} RFQ${got.length === 1 ? '' : 's'}`;
  let message = `${head}, the best-matching rows for your question (copied from the cited cells):\n\n| RFQ | Result | Source |\n|---|---|---|\n${lines.join('\n')}`;

  const conflicts = findConflicts(got.flatMap((g) => g.rows), named);
  let ui: UiDirective | undefined;
  if (conflicts.length > 0) {
    message += `\n\n${conflictBlock(conflicts.map((c) => ({ ...c, part: label(c.part) })))}\n\nWhich RFQ should I use? Choose one below, or tell me which value is right.`;
    for (const c of conflicts.slice(0, 6)) {
      citations.push(...c.sides.map((s) => s.citation));
    }
    const options = new Map(conflicts.flatMap((c) => c.sides.map((s) => [s.rfqId, { id: s.rfqId, label: s.rfqId, detail: `${label(c.part)}: ${c.field}=${s.value}` }] as const)));
    ui = { type: 'disambiguate', prompt: 'The results disagree. Which RFQ do you want to use?', options: [...options.values()] };
  } else if (p.named && p.ids.length > 1) {
    message += '\n\nYou named more than one RFQ. Choose one to continue with it alone, or keep asking across all of them.';
    ui = { type: 'disambiguate', prompt: 'Continue with one RFQ?', options: p.ids.map((id) => ({ id, label: id })) };
  }
  return { ...base, message, citations: [...new Map(citations.map((c) => [c.label, c])).values()], ui };
}
