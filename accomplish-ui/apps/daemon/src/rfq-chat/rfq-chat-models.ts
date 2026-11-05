/**
 * The language models the RFQ assistant may ask, always with temperature 0.1 and always after the evidence has been
 * retrieved (rfq-chat-grounded.ts). The model only phrases what the evidence says; it is never the source of a fact.
 *
 * Provider order: OpenRouter first when a key exists, local Ollama as the fallback and as the only provider when
 * there is no key. The key counts as the owner's opt-in: it is the one saved in the app's Settings (secretsService,
 * provider id 'openrouter'); the env var OPENROUTER_API_KEY with RFQ_CHAT_CLOUD_FALLBACK=1 is the headless alternative.
 * RFQ_CHAT_PROVIDER = local | openrouter | auto (default auto) overrides this.
 */
import { log } from '../logger.js';
import type { ChatMessage, ChatModel } from './rfq-chat-types.js';

const OLLAMA = (process.env.OLLAMA_ENDPOINT ?? process.env.OLLAMA_BASE_URL ?? 'http://localhost:11434').replace(/\/$/, '');
const LOCAL_MODEL = process.env.RFQ_CHAT_MODEL ?? process.env.OLLAMA_MODEL ?? 'qwen3:8b';
const OPENROUTER = (process.env.OPENROUTER_ENDPOINT ?? 'https://openrouter.ai/api/v1').replace(/\/$/, '');
// OpenRouter ids use dots (checked against https://openrouter.ai/api/v1/models on 2026-11-05): a hyphenated id 404s.
const DEFAULT_CLOUD_MODEL = process.env.RFQ_CHAT_OPENROUTER_MODEL ?? 'anthropic/claude-haiku-5.5';

/** A timeout that also ends when the caller aborts (the user pressed Stop). */
const within = (timeoutMs: number, signal?: AbortSignal) =>
  signal ? AbortSignal.any([AbortSignal.timeout(timeoutMs), signal]) : AbortSignal.timeout(timeoutMs);

/** qwen3 may emit its reasoning in <think> tags; that is never part of an answer. */
export function stripThink(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
}

export function localModel(timeoutMs = 120_000): ChatModel {
  const label = `${LOCAL_MODEL} (local)`;
  return {
    label,
    async complete(messages: ChatMessage[], signal?: AbortSignal) {
      try {
        const res = await fetch(`${OLLAMA}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // 12k context: the evidence rows plus the conversation must never push the system prompt out of the window
          body: JSON.stringify({ model: LOCAL_MODEL, messages, stream: false, think: false, options: { temperature: 0.1, num_ctx: 12288 } }),
          signal: within(timeoutMs, signal),
        });
        if (!res.ok) {
          log.warn(`[RfqChat] Ollama HTTP ${res.status}`);
          return null;
        }
        const data = (await res.json()) as { message?: { content?: string } };
        return { text: stripThink(data.message?.content ?? ''), model: label };
      } catch (err) {
        log.warn(`[RfqChat] Ollama failed: ${err}`);
        return null;
      }
    },
  };
}

export function openRouterModel(apiKey: string, model: string, timeoutMs = 60_000): ChatModel {
  const id = model.replace(/^openrouter\//, '');
  const label = `${id} (OpenRouter)`;
  return {
    label,
    async complete(messages: ChatMessage[], signal?: AbortSignal) {
      try {
        const res = await fetch(`${OPENROUTER}/chat/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
          body: JSON.stringify({ model: id, messages, stream: false, temperature: 0.1 }),
          signal: within(timeoutMs, signal),
        });
        if (!res.ok) {
          log.warn(`[RfqChat] OpenRouter HTTP ${res.status}`);
          return null;
        }
        const data = (await res.json()) as { choices?: { message?: { content?: string } }[] };
        return { text: stripThink(data.choices?.[0]?.message?.content ?? ''), model: label };
      } catch (err) {
        log.warn(`[RfqChat] OpenRouter failed: ${err}`);
        return null;
      }
    },
  };
}

/** Tries each model in order; the first usable reply wins. The reply carries the label of whoever produced it. */
export function firstAvailable(models: ChatModel[]): ChatModel {
  return {
    label: models.map((m) => m.label).join(' -> '),
    async complete(messages, signal) {
      for (const m of models) {
        if (signal?.aborted) return null;
        const reply = await m.complete(messages, signal);
        if (reply !== null) return reply;
      }
      return null;
    },
  };
}

export interface ChatProviderInputs {
  /** The OpenRouter key saved in Settings, if any. */
  settingsKey?: string | null;
  /** The model selected in Settings (used when its provider is openrouter). */
  selected?: { provider: string; model: string } | null;
}

export function resolveChatModel({ settingsKey, selected }: ChatProviderInputs = {}): ChatModel {
  const mode = process.env.RFQ_CHAT_PROVIDER ?? 'auto';
  const envKey = process.env.RFQ_CHAT_CLOUD_FALLBACK === '1' ? (process.env.OPENROUTER_API_KEY ?? '') : '';
  const key = settingsKey || envKey;
  const cloudModel = selected?.provider === 'openrouter' && selected.model ? selected.model : DEFAULT_CLOUD_MODEL;
  const models: ChatModel[] = [];
  if (key && mode !== 'local') models.push(openRouterModel(key, cloudModel));
  if (mode !== 'openrouter' || !key) models.push(localModel());
  return firstAvailable(models);
}
