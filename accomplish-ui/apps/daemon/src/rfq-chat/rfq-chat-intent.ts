/**
 * SPEC-019 routing: what is the user doing? Deterministic rules only; no model is asked here. A message none of the
 * rules recognise is 'unsure' and goes to the ordinary conversation, where the model may hand it back as an RFQ-data
 * question (rfq-chat-general.ts), so the model "classifies" inside the one call it makes anyway.
 */
import { isEditRequest } from './rfq-chat-edit-fields.js';

/** The assistant's controls over the app (rfq-chat-controls.ts); each is answered from rules and the database, no model. */
export type ControlIntent = 'open' | 'status' | 'resume' | 'export' | 'upload' | 'settings' | 'edit' | 'manifest';
export type Intent = 'guide' | 'create' | 'data' | 'unsure' | ControlIntent;

// "hai" is how this team writes hi. A greeting is answered from the guide (what I can do); thanks and the like are plain talk.
const GREETING = /^\s*(hi+|hai|hello|hey|yo|hola|namaste|good (morning|afternoon|evening))\b/i;
const HOW_TO = /\b(how (do|to|can|should|does|would|did)|help|guide|tutorial|instructions?|what can you do|what do you do|who are you|what is (this|cam)|walk me through|get(ting)? started|where (do|can|is|are)|explain (the )?(tool|app|screen|ui))\b/i;
const CREATE = /\b(create|make|add|raise|open|start|set ?up|register)\b[^.?!\n]{0,40}\brfq\b|\b(upload|attach)\b[^.?!\n]{0,30}\b(bom|file|sheet|workbook)\b[^.?!\n]{0,40}\b(create|rfq|quote)\b/i;
const DATA = /\b(rfqs?|boms?|cboms?|parts?|prices?|pricing|costs?|costed|uncosted|suppliers?|vendors?|moq|lead[- ]?times?|spend|a-class|go\s*\/?\s*no-?go|no-?go|status|reports?|manifest|quotes?|quantity|qty|stock|alternates?|exports?|exported|margin|total|summary|review|workbook|cells?|sheet|manufacturer|mpn|cpn)\b/i;
// A part-number-like token: 6+ chars mixing a digit with a letter or hyphen (same shape as rfq-chat-grounded.ts).
const PART_LIKE = /(?<![A-Za-z0-9])(?=[A-Za-z0-9._/-]*\d)(?=[A-Za-z0-9._/-]*[A-Za-z-])[A-Za-z0-9][A-Za-z0-9._/-]{5,}(?![A-Za-z0-9])/;

/** An RFQ id as written in text: RFQ-00001, RFQ-CENTUM-PROOF-24. */
const RFQ_TOKEN = /\bRFQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*/gi;

const ID = String.raw`RFQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*`;
const HOW = /\bhow (do|to|can|should|does|would|did)\b/i; // a how-to question goes to the guide, whatever it mentions
const MAKE = /\b(create|make|raise|register|set ?up)\b|\bnew rfq\b/i; // a create request stays the create action
// Words of a figure question: "total export cost" is a workbook question, not a download request.
const FIGURES = /\b(total|spend|costs?|prices?|margin|moq|lead[- ]?times?|suppliers?|qty|quantity|how (many|much))\b/i;
// "open RFQ-x" and nothing else after the id: "show RFQ-x costs" is a data question.
const OPEN = new RegExp(String.raw`\b(open|show|go to|select|switch to|take me to|load)\s+(?:me\s+)?(?:the\s+)?(?:rfq\s+)?(${ID})\s*(?:please|now|again)?\s*[.!?]*\s*$`, 'i');
const RESUME = new RegExp(String.raw`\b(resume|restart|re-?run|continue|kick off|trigger)\b[^.?!\n]{0,40}\b(pipeline|workflow|run|processing)\b|\b(start|run|begin|resume|restart|continue)\b[^.?!\n]{0,25}\b(pipeline|workflow)\b|\b(start|run|begin|resume|restart|continue)\s+(?:the\s+)?${ID}`, 'i');
const STATUS = /\b(pipeline|workflow|hitl|stuck|progress|waiting (for|on) (a |the )?(human |my )?(review|approval)|(which|what|current|at what) (stage|step)|stage (is|of|are)|(is|still|currently|has) (it |this |that |the \w+ )?(running|finished|stopped)|where (is|are) (it|this|that|rfq|the rfq)|how far)\b/i;
const EXPORT = /\b(export|download)\b/i;
const UPLOAD = /\b(upload|attach)\b[^.?!\n]{0,25}\b(files?|bom|volume|workbook|spreadsheet|sheets?|csv|xlsx?|pdf|docx)\b|\badd\s+(?:a|an|another|more)\s+(?:new\s+)?(?:\w+\s+)?(files?|bom|volume)\b/i;
// SPEC-020: "open the Input Standardization manifest", "show skill 4 json". Not with an RFQ id: that is the workbook's Manifest sheet.
const MANIFEST = /\b(open|show|view|display|edit|go to|take me to|pull up)\b[^.?!\n]{0,60}\b(manifests?|skills?|json)\b/i;
const SETTINGS = /\b(openrouter|api[- ]?key|settings|providers?)\b|\b(change|switch|use|pick|select)\b[^.?!\n]{0,20}\b(model|provider)\b/i;

/** Starts every assistant reply that waits for a customer or project; the next turn is read together with the earlier ones. */
export const CREATE_PENDING = 'To create the RFQ I still need this.';

// SPEC-023: files are attached and the user says go ("can u process this files", "use these", "run it"). Decided by rules, no model.
const FILES_VERB = /\b(process|run|ingest|start|use|go|select|pick|map|upload|handle|analy[sz]e|read|proceed|begin|continue|create|make|do|check|parse)\b/i;
const FILES_NOUN = /\b(files?|these|them|this|those|it|bom|attached|attachments?|dump|uploaded|sheets?|workbooks?)\b/i;
const GO = /^\s*(go|run|run it|start|proceed|process|do it|go ahead|continue)\W*$/i;

/** True when the message asks to work on the files attached to this turn (callers check that files are attached). */
export const filesIntent = (question: string): boolean =>
  !new RegExp(ID, 'i').test(question) && !HOW.test(question) && (GO.test(question) || (FILES_VERB.test(question) && FILES_NOUN.test(question)));

/** True when a question is about Settings / the model / the OpenRouter key: a guide answer to it also gets the Open Settings button. */
export const mentionsSettings = (question: string): boolean => SETTINGS.test(question);

/** Which control the user asked for, or null. Order matters: an explicit id beats the pipeline words, a figure word keeps it a data question. */
export function controlIntent(question: string): ControlIntent | null {
  if (HOW.test(question) || MAKE.test(question)) {
    return null;
  }
  const hasId = new RegExp(ID, 'i').test(question);
  if (isEditRequest(question)) {
    return 'edit'; // "set the MOQ of PN-100 to 500": a value edit behind a confirmation card (SPEC-020)
  }
  if (!hasId && MANIFEST.test(question)) {
    return 'manifest';
  }
  if (OPEN.test(question)) {
    return 'open';
  }
  if (RESUME.test(question)) {
    return 'resume';
  }
  if (STATUS.test(question)) {
    return 'status';
  }
  if (!hasId && HOW_TO.test(question)) {
    return null; // "where can I download the reports?", "help me change the model": the guide answers (status above keeps "where is it?")
  }
  if (EXPORT.test(question) && !FIGURES.test(question)) {
    return 'export';
  }
  if (UPLOAD.test(question) && !FIGURES.test(question)) {
    return 'upload';
  }
  return SETTINGS.test(question) && !hasId ? 'settings' : null;
}

/** The full route: a control when one is asked for, else the earlier rules. A control the service cannot carry out falls back to classifyBase. */
export function classify(question: string): Intent {
  return controlIntent(question) ?? classifyBase(question);
}

export function classifyBase(question: string): Intent {
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
