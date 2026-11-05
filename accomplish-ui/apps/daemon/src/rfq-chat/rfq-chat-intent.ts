/**
 * SPEC-019 routing: what is the user doing? Deterministic rules only; no model is asked here. A message none of the
 * rules recognise is 'unsure' and goes to the ordinary conversation, where the model may hand it back as an RFQ-data
 * question (rfq-chat-general.ts), so the model "classifies" inside the one call it makes anyway.
 */

export type Intent = 'guide' | 'create' | 'data' | 'unsure';

// "hai" is how this team writes hi. A greeting is answered from the guide (what I can do); thanks and the like are plain talk.
const GREETING = /^\s*(hi+|hai|hello|hey|yo|hola|namaste|good (morning|afternoon|evening))\b/i;
const HOW_TO = /\b(how (do|to|can|should|does|would|did)|help|guide|tutorial|instructions?|what can you do|what do you do|who are you|what is (this|cam)|walk me through|get(ting)? started|where (do|can|is|are)|explain (the )?(tool|app|screen|ui))\b/i;
const CREATE = /\b(create|make|add|raise|open|start|set ?up|register)\b[^.?!\n]{0,40}\brfq\b|\b(upload|attach)\b[^.?!\n]{0,30}\b(bom|file|sheet|workbook)\b[^.?!\n]{0,40}\b(create|rfq|quote)\b/i;
const DATA = /\b(rfqs?|boms?|cboms?|parts?|prices?|pricing|costs?|costed|uncosted|suppliers?|vendors?|moq|lead[- ]?times?|spend|a-class|go\s*\/?\s*no-?go|no-?go|status|reports?|manifest|quotes?|quantity|qty|stock|alternates?|exports?|exported|margin|total|summary|review|workbook|cells?|sheet|manufacturer|mpn|cpn)\b/i;
// A part-number-like token: 6+ chars mixing a digit with a letter or hyphen (same shape as rfq-chat-grounded.ts).
const PART_LIKE = /(?<![A-Za-z0-9])(?=[A-Za-z0-9._/-]*\d)(?=[A-Za-z0-9._/-]*[A-Za-z-])[A-Za-z0-9][A-Za-z0-9._/-]{5,}(?![A-Za-z0-9])/;

/** An RFQ id as written in text: RFQ-00001, RFQ-CENTUM-PROOF-24. */
const RFQ_TOKEN = /\bRFQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*/gi;

export function classify(question: string): Intent {
  const hasId = RFQ_TOKEN.test(question) || PART_LIKE.test(question);
  RFQ_TOKEN.lastIndex = 0; // a global regex keeps its position between test() calls
  if (!hasId && HOW_TO.test(question)) {
    return 'guide';
  }
  if (CREATE.test(question)) {
    return 'create';
  }
  if (hasId || DATA.test(question)) {
    return 'data';
  }
  return GREETING.test(question) && question.trim().split(/\s+/).length <= 5 ? 'guide' : 'unsure';
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** RFQ ids the text names: the ones that exist, and the RFQ-looking ones that do not. */
export function rfqMentions(text: string, known: string[]): { known: string[]; unknown: string[] } {
  const byLower = new Map(known.map((id) => [id.toLowerCase(), id]));
  const found = new Set<string>();
  for (const id of known) {
    if (new RegExp(`(?<![A-Za-z0-9-])${escape(id)}(?![A-Za-z0-9-])`, 'i').test(text)) {
      found.add(id);
    }
  }
  const unknown = new Set<string>();
  for (const token of text.match(RFQ_TOKEN) ?? []) {
    if (!byLower.has(token.toLowerCase())) {
      unknown.add(token);
    }
  }
  return { known: [...found], unknown: [...unknown] };
}
