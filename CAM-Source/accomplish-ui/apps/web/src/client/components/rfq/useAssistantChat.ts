import { useCallback, useEffect, useRef, useState } from 'react';
import type { MessageCitation } from '@accomplish_ai/agent-core';
import { backendUrl } from '@/config/endpoints';
import { getAccomplish } from '@/lib/accomplish';
import { clearSession, getSessionToken } from '@/lib/session';
import {
  defaultScope, isRfqId, parseScope, parseUi, scopeFromIds,
  type ActionConfirmResponse, type ChatProviderMode, type ChatResponse, type ChatScope, type DisambiguateOption, type FileRef, type UiDirective,
} from '@/lib/chatContract';
import { setChatProvider, useChatProvider } from '@/lib/chatProvider';

/** How a confirmation card ended; kept on the message so it survives a reload and cannot be clicked twice. */
export interface ConfirmOutcome {
  state: 'confirmed' | 'cancelled' | 'failed';
  response?: ActionConfirmResponse;
  error?: string;
}

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
  /** Instruction from the daemon to draw next to the text (picker, option buttons, confirmation, upload). */
  ui?: UiDirective;
  /** The user's question that made the daemon ask for a choice; it is sent again once the choice is made. */
  question?: string;
  /** What the user chose for this directive; set once, then the directive stops offering choices. */
  done?: string;
  confirm?: ConfirmOutcome;
}

const KEEP = 60; // messages kept per conversation
const SENT = 12; // messages sent with each question
// One conversation per left-list selection (an RFQ, or "none"), each with its own scope, kept while the page lives.
const store = new Map<string, ChatMsg[]>();
const scopes = new Map<string, ChatScope>();
const convoOf = (rfqId: string | null) => rfqId ?? '__all__';

function load(convo: string): ChatMsg[] {
  const mem = store.get(convo);
  if (mem) return mem;
  try {
    const raw = sessionStorage.getItem(`rfq-chat:${convo}`);
    const parsed = raw ? (JSON.parse(raw) as ChatMsg[]) : [];
    store.set(convo, parsed);
    return parsed;
  } catch {
    return [];
  }
}

// The conversation of an RFQ is also kept on the daemon (rfq_chat_history): reopening it from History or in a new session shows the same chat.
const pendingSave = new Map<string, ReturnType<typeof setTimeout>>();
function saveToServer(convo: string) {
  if (convo === '__all__') return;
  clearTimeout(pendingSave.get(convo));
  pendingSave.set(convo, setTimeout(() => {
    pendingSave.delete(convo);
    void getAccomplish().chatSaveHistory({ rfqId: convo, messages: load(convo) }).catch(() => undefined);
  }, 800));
}

function save(convo: string, messages: ChatMsg[]) {
  const kept = messages.slice(-KEEP);
  store.set(convo, kept);
  try {
    sessionStorage.setItem(`rfq-chat:${convo}`, JSON.stringify(kept));
  } catch {
    /* storage can be full or blocked: the conversation then lives in memory only */
  }
  saveToServer(convo);
}

/** The RFQ's saved conversation when this browser has none (a new session, or a History entry from before). */
async function restoreFromServer(convo: string): Promise<ChatMsg[] | null> {
  if (convo === '__all__' || load(convo).length > 0) return null;
  try {
    const { messages } = await getAccomplish().chatLoadHistory({ rfqId: convo });
    return messages.length > 0 ? (messages as ChatMsg[]) : null;
  } catch {
    return null; // signed out or daemon down: the chat starts empty, as before
  }
}

function loadScope(convo: string): ChatScope | undefined {
  const mem = scopes.get(convo);
  if (mem) return mem;
  try {
    const raw = sessionStorage.getItem(`rfq-chat-scope:${convo}`);
    return raw ? parseScope(JSON.parse(raw)) : undefined;
  } catch {
    return undefined;
  }
}

function saveScope(convo: string, scope: ChatScope) {
  scopes.set(convo, scope);
  try {
    sessionStorage.setItem(`rfq-chat-scope:${convo}`, JSON.stringify(scope));
  } catch {
    /* in memory only */
  }
}

const newId = () => (globalThis.crypto?.randomUUID?.() ?? `m_${Date.now()}_${Math.random().toString(36).slice(2)}`);

/**
 * The conversation with the assistant. It never ends by itself: every answer, refusal or failure is just another
 * message, and the composer stays available. `rfqId` is the RFQ selected in the left list (null = none); it sets the
 * scope when it changes, and the daemon's replies may change the scope after that.
 */
export function useAssistantChat(rfqId: string | null, getFileRefs?: () => FileRef[]) {
  const convo = convoOf(rfqId);
  // The Local / OpenRouter / Auto switch lives in one store shared with the model menu; sent with every question.
  const provider = useChatProvider();
  const providerRef = useRef(provider);
  providerRef.current = provider;
  const setProvider = useCallback((next: ChatProviderMode) => setChatProvider(next), []);
  const [messages, setMessages] = useState<ChatMsg[]>(() => load(convo));
  const [scope, setScopeState] = useState<ChatScope>(() => loadScope(convo) ?? defaultScope(rfqId));
  const [pickerFor, setPickerFor] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const live = useRef(convo);
  live.current = convo;
  const scopeRef = useRef(scope); // the latest scope, readable inside callbacks that run before a re-render
  const lastConvo = useRef(convo);

  const setScope = useCallback((next: ChatScope, at: string) => {
    saveScope(at, next);
    if (live.current !== at) return;
    scopeRef.current = next;
    setScopeState(next);
  }, []);

  useEffect(() => {
    abort.current?.abort();
    setRunning(false);
    setPickerFor(null);
    setMessages(load(convo));
    void restoreFromServer(convo).then((msgs) => {
      if (msgs && live.current === convo) { save(convo, msgs); setMessages(msgs); }
    });
    const selected = lastConvo.current !== convo; // picking another RFQ in the left list resets the scope to it
    lastConvo.current = convo;
    setScope((selected ? undefined : loadScope(convo)) ?? defaultScope(rfqId), convo);
  }, [convo, rfqId, setScope]);

  const push = useCallback((at: string, msg: ChatMsg) => {
    const next = [...load(at), msg];
    save(at, next);
    if (live.current === at) setMessages(next);
  }, []);

  /** Records what the user did with a directive on its message. */
  const settle = useCallback((id: string, patch: Partial<ChatMsg>) => {
    const at = live.current;
    const next = load(at).map((m) => (m.id === id ? { ...m, ...patch } : m));
    save(at, next);
    setMessages(next);
  }, []);

  const send = useCallback(async (text: string, useScope?: ChatScope) => {
    const question = text.trim();
    if (!question || abort.current) return;
    const at = convo;
    const sendScope = useScope ?? scopeRef.current;
    push(at, { id: newId(), role: 'user', content: question, at: Date.now() });
    const history = load(at).slice(-SENT).filter((m) => !m.failed).map(({ role, content }) => ({ role, content }));
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    try {
      const token = getSessionToken();
      const res = await fetch(backendUrl('/api/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        // Released files ride along so "create an RFQ from this" can name them; the daemon re-checks them with the bridge.
        body: JSON.stringify({ messages: history, scope: sendScope, fileRefs: getFileRefs?.() ?? [], provider: providerRef.current }),
        signal: controller.signal,
      });
      if (res.status === 401) {
        clearSession();
        window.location.hash = '#/login';
        push(at, { id: newId(), role: 'assistant', content: 'Your session has expired. Please sign in again.', at: Date.now(), failed: true });
        return;
      }
      const data = (await res.json().catch(() => ({}))) as Partial<ChatResponse> & { error?: string };
      if (!res.ok || !data.message) {
        push(at, { id: newId(), role: 'assistant', content: data.error ?? `The assistant service answered HTTP ${res.status}.`, at: Date.now(), failed: true });
        return;
      }
      const answered = parseScope(data.scope);
      if (answered) setScope(answered, at);
      const ui = parseUi(data.ui);
      const asksChoice = ui?.type === 'pick_rfq' || ui?.type === 'disambiguate';
      const msg: ChatMsg = {
        id: newId(), role: 'assistant', content: data.message, citations: data.citations?.length ? data.citations : undefined,
        model: data.model, at: Date.now(), ui, question: asksChoice ? question : undefined,
      };
      push(at, msg);
      if (ui?.type === 'pick_rfq' && live.current === at) setPickerFor(msg.id);
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
  }, [convo, push, setScope, getFileRefs]);

  /** The picker's answer: set the scope, then ask the question that triggered the picker again, now with that scope. */
  const applyPick = useCallback((msg: ChatMsg, next: ChatScope) => {
    const label = next.mode === 'rfqs' ? next.rfqIds.join(', ') : 'All context';
    setPickerFor(null);
    setScope(next, convo);
    settle(msg.id, { done: label });
    if (msg.question) void send(msg.question, next);
  }, [convo, send, setScope, settle]);

  /** An option button: an RFQ option sets the scope and asks the question again; any other is sent as the next turn. */
  const choose = useCallback((msg: ChatMsg, option: DisambiguateOption) => {
    settle(msg.id, { done: option.label });
    if (isRfqId(option.id)) {
      const next = scopeFromIds([option.id]);
      setScope(next, convo);
      if (msg.question) void send(msg.question, next);
      return;
    }
    void send(option.send ?? option.label);
  }, [convo, send, setScope, settle]);

  const removeFromScope = useCallback((rfq: string | 'all') => {
    const cur = scopeRef.current;
    const ids = cur.mode === 'rfqs' && rfq !== 'all' ? cur.rfqIds.filter((i) => i !== rfq) : [];
    setScope(scopeFromIds(ids), convo);
  }, [convo, setScope]);

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setRunning(false);
  }, []);

  const reset = useCallback(() => {
    stop();
    save(convo, []);
    setMessages([]);
    setPickerFor(null);
    setScope(defaultScope(rfqId), convo);
  }, [convo, rfqId, stop, setScope]);

  const picker = pickerFor ? messages.find((m) => m.id === pickerFor) : undefined;
  const openPicker = useCallback((id: string) => setPickerFor(id), []);
  const closePicker = useCallback(() => setPickerFor(null), []);
  return { messages, running, scope, picker, provider, setProvider, send, stop, reset, applyPick, choose, settle, removeFromScope, openPicker, closePicker };
}
