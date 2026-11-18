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
          // 8k context holds 9000 chars of evidence plus the conversation (about 3.5k tokens) without the KV-cache cost of
          // 12k on an 8 GB card; num_predict stops a runaway generation (answers are short numbered-row phrasings);
          // keep_alive avoids a model reload between questions.
          body: JSON.stringify({
            model: LOCAL_MODEL, messages, stream: false, think: false, keep_alive: '30m',
            options: { temperature: 0.1, num_ctx: 8192, num_predict: 400 },
          }),
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
    /** One turn with tools (the agent). Ollama's tool calls arrive as objects; the turn goes back as the assistant message. */
    async callTools(messages: unknown[], tools: unknown[], signal?: AbortSignal) {
      try {
        const res = await fetch(`${OLLAMA}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: LOCAL_MODEL, messages, tools, stream: false, think: false, keep_alive: '30m',
            options: { temperature: 0.1, num_ctx: 8192, num_predict: 600 },
          }),
          signal: within(150_000, signal),
        });
        if (!res.ok) {
          log.warn(`[RfqChat] Ollama tools HTTP ${res.status}`);
          return null;
        }
        const data = (await res.json()) as {
          message?: { content?: string; tool_calls?: Array<{ function?: { name?: string; arguments?: Record<string, unknown> } }> };
        };
        const message = data.message ?? {};
        return {
          text: stripThink(message.content ?? ''),
          toolCalls: (message.tool_calls ?? []).map((c, i) => ({ id: `call_${i}`, name: c.function?.name ?? '', args: c.function?.arguments ?? {} })),
          model: label,
          assistant: message,
        };
      } catch (err) {
        log.warn(`[RfqChat] Ollama tools failed: ${err}`);
        return null;
      }
    },
  };
}

/** The last reason OpenRouter refused a question, in words a person can act on (never the key). Read by the chat when it cannot answer. */
let lastOpenRouterFailure: string | null = null;
export function openRouterFailureReason(): string | null {
  return lastOpenRouterFailure;
}
export function describeOpenRouterStatus(status: number): string {
  if (status === 402) return "OpenRouter says the account behind the key has no credit left (HTTP 402). Add credit at openrouter.ai, then ask again.";
  if (status === 401 || status === 403) return `OpenRouter rejected the key (HTTP ${status}). Save a valid key in Settings > Providers > OpenRouter.`;
  if (status === 429) return "OpenRouter is rate-limiting this key right now (HTTP 429). Try again in a minute.";
  return `OpenRouter returned HTTP ${status}.`;
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
          lastOpenRouterFailure = describeOpenRouterStatus(res.status);
          return null;
        }
        lastOpenRouterFailure = null;
        const data = (await res.json()) as { choices?: { message?: { content?: string } }[] };
        return { text: stripThink(data.choices?.[0]?.message?.content ?? ''), model: label };
      } catch (err) {
        log.warn(`[RfqChat] OpenRouter failed: ${err}`);
        lastOpenRouterFailure = "OpenRouter could not be reached from this computer (network or timeout).";
        return null;
      }
    },
    /** One turn with tools (the agent). OpenRouter's tool calls carry JSON-text arguments and an id the tool result must return. */
    async callTools(messages: unknown[], tools: unknown[], signal?: AbortSignal) {
      try {
        const res = await fetch(`${OPENROUTER}/chat/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
          body: JSON.stringify({ model: id, messages, tools, stream: false, temperature: 0.1 }),
          signal: within(150_000, signal),
        });
        if (!res.ok) {
          log.warn(`[RfqChat] OpenRouter tools HTTP ${res.status}`);
          lastOpenRouterFailure = describeOpenRouterStatus(res.status);
          return null;
        }
        lastOpenRouterFailure = null;
        const data = (await res.json()) as {
          choices?: { message?: { content?: string | null; tool_calls?: Array<{ id?: string; function?: { name?: string; arguments?: string } }> } }[];
        };
        const message = data.choices?.[0]?.message ?? {};
        return {
          text: stripThink(message.content ?? ''),
          toolCalls: (message.tool_calls ?? []).map((c, i) => {
            let args: Record<string, unknown> = {};
            try {
              args = JSON.parse(c.function?.arguments ?? '{}') as Record<string, unknown>;
            } catch {
              args = {};
            }
            return { id: c.id ?? `call_${i}`, name: c.function?.name ?? '', args };
          }),
          model: label,
          assistant: message,
        };
      } catch (err) {
        log.warn(`[RfqChat] OpenRouter tools failed: ${err}`);
        lastOpenRouterFailure = "OpenRouter could not be reached from this computer (network or timeout).";
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
    async callTools(messages, tools, signal) {
      for (const m of models) {
        if (signal?.aborted) return null;
        if (!m.callTools) continue;
        const turn = await m.callTools(messages, tools, signal);
        if (turn !== null) return turn;
      }
      return null;
    },
  };
}

/** The user's switch in the assistant: auto = OpenRouter when a key exists, else local; the others force one provider. */
export type ChatProviderMode = 'auto' | 'local' | 'openrouter';
export const parseProviderMode = (v: unknown): ChatProviderMode | undefined =>
  v === 'auto' || v === 'local' || v === 'openrouter' ? v : undefined;

export interface ChatProviderInputs {
  /** The OpenRouter key saved in Settings, if any. */
  settingsKey?: string | null;
  /** The model selected in Settings (used when its provider is openrouter). */
  selected?: { provider: string; model: string } | null;
  /** The switch in the assistant UI; falls back to RFQ_CHAT_PROVIDER, then auto. */
  mode?: ChatProviderMode;
}

const cloudModelOf = (selected?: ChatProviderInputs['selected']) =>
  selected?.provider === 'openrouter' && selected.model ? selected.model : DEFAULT_CLOUD_MODEL;

export function resolveChatModel({ settingsKey, selected, mode: asked }: ChatProviderInputs = {}): ChatModel {
  const mode = asked ?? parseProviderMode(process.env.RFQ_CHAT_PROVIDER) ?? 'auto';
  const envKey = process.env.RFQ_CHAT_CLOUD_FALLBACK === '1' ? (process.env.OPENROUTER_API_KEY ?? '') : '';
  const key = settingsKey || envKey;
  const models: ChatModel[] = [];
  if (key && mode !== 'local') models.push(openRouterModel(key, cloudModelOf(selected)));
  if (mode !== 'openrouter' || !key) models.push(localModel());
  return firstAvailable(models);
}

/** What the switch shows: which providers exist right now. Never the key itself. */
export function describeChatProviders({ settingsKey, selected }: ChatProviderInputs = {}) {
  const envKey = process.env.RFQ_CHAT_CLOUD_FALLBACK === '1' ? (process.env.OPENROUTER_API_KEY ?? '') : '';
  return {
    local: { model: LOCAL_MODEL },
    openrouter: { hasKey: Boolean(settingsKey || envKey), model: cloudModelOf(selected) },
    defaultMode: parseProviderMode(process.env.RFQ_CHAT_PROVIDER) ?? 'auto',
  };
}
