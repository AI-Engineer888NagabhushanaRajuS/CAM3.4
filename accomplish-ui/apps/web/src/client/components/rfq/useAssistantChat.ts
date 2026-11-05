import { useCallback, useEffect, useRef, useState } from 'react';
import type { MessageCitation } from '@accomplish_ai/agent-core';
import { backendUrl } from '@/config/endpoints';
import { clearSession, getSessionToken } from '@/lib/session';

export interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: MessageCitation[];
  /** Which model phrased the answer; null/undefined when none was needed (a refusal, a list of RFQs, a greeting). */
  model?: string | null;
  at: number;
  /** A failure of the chat service itself, not an answer. */
  failed?: boolean;
}

const KEEP = 60; // messages kept per conversation
const SENT = 12; // messages sent with each question
const store = new Map<string, ChatMsg[]>(); // one conversation per RFQ (and one for "no RFQ"), kept while the page lives
const scopeOf = (rfqId: string | null) => rfqId ?? '__all__';

function load(scope: string): ChatMsg[] {
  const mem = store.get(scope);
  if (mem) return mem;
  try {
    const raw = sessionStorage.getItem(`rfq-chat:${scope}`);
    const parsed = raw ? (JSON.parse(raw) as ChatMsg[]) : [];
    store.set(scope, parsed);
    return parsed;
  } catch {
    return [];
  }
}

function save(scope: string, messages: ChatMsg[]) {
  const kept = messages.slice(-KEEP);
  store.set(scope, kept);
  try {
    sessionStorage.setItem(`rfq-chat:${scope}`, JSON.stringify(kept));
  } catch {
    /* storage can be full or blocked: the conversation then lives in memory only */
  }
}

const newId = () => (globalThis.crypto?.randomUUID?.() ?? `m_${Date.now()}_${Math.random().toString(36).slice(2)}`);

/**
 * The conversation with the RFQ assistant. It never ends by itself: every answer, refusal or failure is just another
 * message, and the composer stays available. `rfqId` null = the assistant that lists RFQs and routes to the one named.
 */
export function useAssistantChat(rfqId: string | null) {
  const scope = scopeOf(rfqId);
  const [messages, setMessages] = useState<ChatMsg[]>(() => load(scope));
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const live = useRef(scope);
  live.current = scope;

  useEffect(() => {
    abort.current?.abort();
    setRunning(false);
    setMessages(load(scope));
  }, [scope]);

  const push = useCallback((at: string, msg: ChatMsg) => {
    const next = [...load(at), msg];
    save(at, next);
    if (live.current === at) setMessages(next);
  }, []);

  const send = useCallback(async (text: string) => {
    const question = text.trim();
    if (!question || abort.current) return;
    const at = scope;
    push(at, { id: newId(), role: 'user', content: question, at: Date.now() });
    const history = load(at).slice(-SENT).filter((m) => !m.failed).map(({ role, content }) => ({ role, content }));
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    try {
      const token = getSessionToken();
      const res = await fetch(backendUrl(rfqId ? `/api/rfq/${encodeURIComponent(rfqId)}/chat` : '/api/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ messages: history }),
        signal: controller.signal,
      });
      if (res.status === 401) {
        clearSession();
        window.location.hash = '#/login';
        push(at, { id: newId(), role: 'assistant', content: 'Your session has expired. Please sign in again.', at: Date.now(), failed: true });
        return;
      }
      const data = (await res.json().catch(() => ({}))) as { message?: string; error?: string; citations?: MessageCitation[]; model?: string | null };
      if (!res.ok || !data.message) {
        push(at, { id: newId(), role: 'assistant', content: data.error ?? `The assistant service answered HTTP ${res.status}.`, at: Date.now(), failed: true });
        return;
      }
      push(at, { id: newId(), role: 'assistant', content: data.message, citations: data.citations?.length ? data.citations : undefined, model: data.model, at: Date.now() });
    } catch (err) {
      if (controller.signal.aborted) return; // the user pressed Stop or switched RFQ: nothing to report
      push(at, {
        id: newId(), role: 'assistant', at: Date.now(), failed: true,
        content: `I couldn't reach the assistant service (${err instanceof Error ? err.message : 'network error'}). Nothing was guessed. Check that the CAM daemon is running, then try again.`,
      });
    } finally {
      if (abort.current === controller) abort.current = null;
      if (live.current === at) setRunning(false);
    }
  }, [scope, rfqId, push]);

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setRunning(false);
  }, []);

  const reset = useCallback(() => {
    stop();
    save(scope, []);
    setMessages([]);
  }, [scope, stop]);

  return { messages, running, send, stop, reset };
}
