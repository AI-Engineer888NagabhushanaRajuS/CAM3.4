/**
 * How-to and greeting answers come from the version-controlled user guide (docs/CAM-3.4-USER-GUIDE.md), never from the
 * model's memory: the guide's sections are the evidence, they are cited, and the guide holds no RFQ data. The model only
 * phrases the sections it is given; if it is unreachable or its text does not verify, the sections are shown as written.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import type { MessageCitation } from '@accomplish_ai/agent-core';
import { resolveCitations, unverifiedByLine } from './rfq-chat-verify.js';
import type { ChatMessage, ChatModel, GroundedAnswer, Turn } from './rfq-chat-types.js';

export interface GuideSection {
  heading: string;
  body: string;
}

const GUIDE_FILE = join('docs', 'CAM-3.4-USER-GUIDE.md');
const SECTIONS_SHOWN = 3;
const SECTION_CHARS = 1400;
let cached: GuideSection[] | null | undefined;

/** The guide sits in the repo's docs folder; look upward from the working directory and from this file (tsup bundles to CJS, so no import.meta). */
function findGuide(): string | null {
  const override = process.env.RFQ_CHAT_GUIDE_PATH;
  if (override && existsSync(override)) {
    return override;
  }
  for (const start of [process.cwd(), typeof __dirname === 'string' ? __dirname : ''].filter(Boolean)) {
    let dir = resolve(start);
    for (let i = 0; i < 8; i++) {
      const candidate = join(dir, GUIDE_FILE);
      if (existsSync(candidate)) {
        return candidate;
      }
      dir = dirname(dir);
    }
  }
  return null;
}

export function parseGuide(markdown: string): GuideSection[] {
  return markdown.split(/^## /m).slice(1).map((part) => {
    const [heading, ...rest] = part.split('\n');
    return { heading: heading.trim(), body: rest.join('\n').trim() };
  });
}

/** Cached after the first read: the file only changes with a release. Null when the guide cannot be found. */
export function loadGuide(): GuideSection[] | null {
  if (cached === undefined) {
    const file = findGuide();
    cached = file ? parseGuide(readFileSync(file, 'utf8')) : null;
  }
  return cached;
}

const STOP = new Set(['the', 'and', 'how', 'what', 'can', 'you', 'this', 'that', 'use', 'tool', 'with', 'for', 'are', 'does', 'please', 'help', 'hai', 'hello']);

/** The sections whose words overlap the question most; with no overlap (a greeting) the overview and the assistant section. */
export function pickSections(question: string, sections: GuideSection[]): GuideSection[] {
  const abilities = sections.find((s) => /what the assistant can do/i.test(s.heading));
  if (abilities && /what (can|do) you do|what are you able/i.test(question)) {
    return [abilities, sections[0]];
  }
  const words = (question.toLowerCase().match(/[a-z]{3,}/g) ?? []).filter((w) => !STOP.has(w));
  const scored = sections.map((s) => {
    const head = s.heading.toLowerCase();
    const body = s.body.toLowerCase();
    return { s, score: words.reduce((n, w) => n + (head.includes(w) ? 3 : 0) + (body.includes(w) ? 1 : 0), 0) };
  }).filter((x) => x.score > 0).sort((a, b) => b.score - a.score);
  if (scored.length > 0) {
    return scored.slice(0, SECTIONS_SHOWN).map((x) => x.s);
  }
  return [sections[0], sections.find((s) => /ask the assistant/i.test(s.heading))].filter((s): s is GuideSection => !!s);
}

const sectionNumber = (s: GuideSection) => s.heading.match(/^\d+/)?.[0] ?? s.heading;

/** `sourceType` has no 'user_guide' member yet (agent-core types.task.ts is outside this change): typed as string, then widened. */
function guideCitation(s: GuideSection): MessageCitation {
  const sourceType: string = 'user_guide';
  return { sourceType, label: `User guide: ${s.heading}`, identifier: { file: GUIDE_FILE.replace('\\', '/'), section: sectionNumber(s) } } as MessageCitation;
}

const GUIDE_PROMPT = [
  'You are the assistant inside CAM4, a tool that turns a customer BOM into a costed quote. You answer using ONLY the numbered Guide sections you are given.',
  'Rules:',
  '1. If the user greets you, greet back in one short sentence, then say what you can help with, from the Guide.',
  '2. For how-to questions give short numbered steps using the Guide\'s own button and screen names. Never invent a button, screen or step.',
  '3. After each step or claim cite the section as [n] on the same line.',
  '4. Say nothing about any specific RFQ, part, price or figure; you have no such data here. If asked for one, say you will open the RFQ picker.',
  '5. If the Guide does not cover the question, say so plainly and name what the Guide does cover.',
  '6. Be concise: the user wants the steps, not an essay.',
].join('\n');

export async function answerFromGuide(
  p: { question: string; history?: Turn[]; sections: GuideSection[] },
  deps: { model: ChatModel; signal?: AbortSignal },
): Promise<GroundedAnswer> {
  const chosen = pickSections(p.question, p.sections);
  const chunks = chosen.map((s) => ({ text: s.body.slice(0, SECTION_CHARS), citation: guideCitation(s) }));
  const citations = chunks.map((c) => c.citation);
  const shown = () => ({
    message: `Here is what the user guide says:\n\n${chosen.map((s) => `**${s.heading}**\n${s.body.slice(0, SECTION_CHARS)}`).join('\n\n')}`,
    citations,
    grounded: true as const,
    model: null,
  });

  const recent = (p.history ?? []).slice(-4).map((t) => `${t.role === 'user' ? 'User' : 'Assistant'}: ${t.content.slice(0, 400)}`).join('\n');
  const messages: ChatMessage[] = [
    { role: 'system', content: GUIDE_PROMPT },
    { role: 'user', content: `Guide:\n${chunks.map((c, i) => `[${i + 1}] (${c.citation.label}) ${c.text}`).join('\n\n')}\n\n${recent ? `Conversation so far (not evidence):\n${recent}\n\n` : ''}User message: ${p.question}` },
  ];
  const answer = await deps.model.complete(messages, deps.signal);
  if (answer === null) {
    return shown();
  }
  const bad = unverifiedByLine(answer.text, chunks, p.question);
  const { text, cited } = resolveCitations(answer.text, chunks);
  if (bad.length > 0 || cited.length === 0) {
    return shown(); // one call only: the guide itself is the fallback
  }
  return { message: text, citations: cited.map((i) => citations[i]), grounded: true, model: answer.model };
}
