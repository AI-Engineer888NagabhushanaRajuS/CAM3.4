/**
 * Prompt assembly + single-shot Ollama completion for RFQ chat answer
 * synthesis (BuLLMQuote-SRIM). Deliberately NOT a tool-calling agent
 * session — no `opencode serve`, no per-task runtime, no tool-calling
 * capability given to the model at all. The model is a text-synthesis
 * step only; the daemon (rfq-chat-heuristic.ts + task-service.ts) already
 * decided which MCP tools to call, if any, before this runs. This is the
 * actual read-only enforcement mechanism for this feature (see plan §2):
 * there is no privilege to strip because the model never has any.
 *
 * Citation integrity (plan §0.D): this module never asks the model to
 * produce citations as free text, and the caller (task-service.ts) never
 * treats any part of this function's return value as a citation — citations
 * are attached separately, copied verbatim from the backend's own
 * `chunks[].citation` field.
 */

import { log } from '../logger.js';
import type { MessageCitation } from './rfq-chat-client.js';

const OLLAMA_ENDPOINT = (process.env.OLLAMA_ENDPOINT ?? 'http://localhost:11434').replace(/\/$/, '');
const RFQ_CHAT_MODEL = process.env.RFQ_CHAT_MODEL ?? 'qwen3:8b';

// Cloud fallback (OpenRouter). Off unless RFQ_CHAT_CLOUD_FALLBACK=1 AND OPENROUTER_API_KEY is set. When it runs,
// the RFQ context (BOM part numbers, prices, suppliers) leaves this machine, so it is opt-in by design.
const CLOUD_FALLBACK = process.env.RFQ_CHAT_CLOUD_FALLBACK === '1';
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY ?? '';
const OPENROUTER_ENDPOINT = (process.env.OPENROUTER_ENDPOINT ?? 'https://openrouter.ai/api/v1').replace(/\/$/, '');
const OPENROUTER_MODEL = process.env.RFQ_CHAT_OPENROUTER_MODEL ?? 'anthropic/claude-haiku-5-5';

const NO_ANSWER_SENTINEL = 'NO_ANSWER_FOUND';

const SYSTEM_PROMPT = [
  'You are answering a question about a specific RFQ (Request for Quote) for a BOM/CBOM costing platform.',
  'Answer ONLY using the information in the provided context below.',
  `If the context does not contain enough information to answer, respond with exactly: ${NO_ANSWER_SENTINEL}`,
  'Do not guess, do not invent part numbers, prices, suppliers, or any other detail not present in the context.',
  'Be concise and factual.',
].join(' ');

export interface SynthesizeAnswerParams {
  question: string;
  chunks: Array<{ text: string; citation: MessageCitation }>;
  sessionRecall: string | null;
  structuredContext?: string;
}

export interface SynthesizeAnswerResult {
  answer: string | null;
  citations: MessageCitation[];
}

/** Empty-context short-circuit (plan §10 step 5g) — skips the LLM call
 * entirely rather than let it try to answer from nothing. */
export function hasUsableContext(params: Pick<SynthesizeAnswerParams, 'chunks' | 'structuredContext'>): boolean {
  return params.chunks.length > 0 || !!params.structuredContext;
}

export async function synthesizeAnswer(params: SynthesizeAnswerParams, timeoutMs = 30000): Promise<SynthesizeAnswerResult> {
  const { question, chunks, sessionRecall, structuredContext } = params;

  const contextParts: string[] = [];
  if (structuredContext) {
    contextParts.push(`Authoritative structured data:\n${structuredContext}`);
  }
  if (chunks.length > 0) {
    contextParts.push(`Retrieved context:\n${chunks.map((c, i) => `[${i + 1}] ${c.text}`).join('\n')}`);
  }
  if (sessionRecall) {
    contextParts.push(`Recent conversation context:\n${sessionRecall}`);
  }

  const userPrompt = `${contextParts.join('\n\n')}\n\nQuestion: ${question}`;

  const messages: ChatMessage[] = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'user', content: userPrompt },
  ];

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    // Local model first (the default and the only path when cloud fallback is off).
    let raw = await completeWithOllama(messages, controller.signal);
    if (raw === null && CLOUD_FALLBACK && OPENROUTER_API_KEY) {
      log.warn('[RfqChat] local model unavailable; using OpenRouter fallback');
      raw = await completeWithOpenRouter(messages, controller.signal);
    }
    if (!raw || raw.includes(NO_ANSWER_SENTINEL)) {
      return { answer: null, citations: [] };
    }
    // Citations are every chunk actually fed into the prompt as context --
    // never derived from the model's own output (see module docstring).
    return { answer: raw, citations: chunks.map((c) => c.citation) };
  } finally {
    clearTimeout(timeout);
  }
}

type ChatMessage = { role: 'system' | 'user'; content: string };

/** Returns the model's text, or null when Ollama is unreachable or answers with an error. */
async function completeWithOllama(messages: ChatMessage[], signal: AbortSignal): Promise<string | null> {
  try {
    const res = await fetch(`${OLLAMA_ENDPOINT}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: RFQ_CHAT_MODEL, messages, stream: false }),
      signal,
    });
    if (!res.ok) {
      log.warn(`[RfqChat] Ollama synthesis HTTP ${res.status}`);
      return null;
    }
    const data = (await res.json()) as { message?: { content?: string } };
    return data.message?.content?.trim() ?? '';
  } catch (err) {
    log.warn(`[RfqChat] Ollama synthesis failed: ${err}`);
    return null;
  }
}

/** Returns the model's text, or null when OpenRouter is unreachable or answers with an error. */
async function completeWithOpenRouter(messages: ChatMessage[], signal: AbortSignal): Promise<string | null> {
  try {
    const res = await fetch(`${OPENROUTER_ENDPOINT}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${OPENROUTER_API_KEY}`,
      },
      body: JSON.stringify({ model: OPENROUTER_MODEL, messages, stream: false }),
      signal,
    });
    if (!res.ok) {
      log.warn(`[RfqChat] OpenRouter synthesis HTTP ${res.status}`);
      return null;
    }
    const data = (await res.json()) as { choices?: { message?: { content?: string } }[] };
    return data.choices?.[0]?.message?.content?.trim() ?? '';
  } catch (err) {
    log.warn(`[RfqChat] OpenRouter synthesis failed: ${err}`);
    return null;
  }
}
