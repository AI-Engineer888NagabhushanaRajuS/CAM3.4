import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

const session = vi.hoisted(() => ({ token: 'tok-1', clear: vi.fn() }));
vi.mock('@/lib/session', () => ({ getSessionToken: () => session.token, clearSession: session.clear }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}`, PYTHON_BRIDGE_URL: 'http://bridge' }));

import { useAssistantChat } from '@/components/rfq/useAssistantChat';

const reply = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear();
  session.clear.mockReset();
  fetchMock = vi.fn(async () => reply({ message: 'UBR03225 has an MOQ of 5000 (CBOM!A5:E5).', citations: [{ sourceType: 'excel_export', label: 'CBOM!A5:E5', identifier: {} }], model: 'qwen3:8b (local)' }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('the conversation does not end after an answer', () => {
  it('keeps every message and accepts the next question (it used to close after the first one)', async () => {
    const { result } = renderHook(() => useAssistantChat('RFQ-T1'));
    await act(() => result.current.send('MOQ of UBR03225?'));
    await act(() => result.current.send('and the lead time?'));
    expect(result.current.messages.map((m) => m.role)).toEqual(['user', 'assistant', 'user', 'assistant']);
    expect(result.current.running).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const second = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(second.messages.map((m: { content: string }) => m.content)).toEqual(['MOQ of UBR03225?', 'UBR03225 has an MOQ of 5000 (CBOM!A5:E5).', 'and the lead time?']);
  });

  it('posts to /api/chat with the session token and the scope: the selected RFQ, or none', async () => {
    const one = renderHook(() => useAssistantChat('RFQ-T2'));
    await act(() => one.result.current.send('hi'));
    expect(fetchMock.mock.calls[0][0]).toBe('http://daemon/api/chat');
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer tok-1');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string).scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-T2'] });
    const all = renderHook(() => useAssistantChat(null));
    await act(() => all.result.current.send('which RFQs do I have?'));
    expect(fetchMock.mock.calls[1][0]).toBe('http://daemon/api/chat');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string).scope).toEqual({ mode: 'none' });
  });

  it('carries the sources and the model of an answer', async () => {
    const { result } = renderHook(() => useAssistantChat('RFQ-T3'));
    await act(() => result.current.send('MOQ?'));
    const answer = result.current.messages[1];
    expect(answer.citations?.[0].label).toBe('CBOM!A5:E5');
    expect(answer.model).toBe('qwen3:8b (local)');
  });

  it('keeps a separate conversation per RFQ and brings it back when you return', async () => {
    const { result, rerender } = renderHook(({ id }) => useAssistantChat(id), { initialProps: { id: 'RFQ-T4A' as string | null } });
    await act(() => result.current.send('first RFQ question'));
    rerender({ id: 'RFQ-T4B' });
    await waitFor(() => expect(result.current.messages).toHaveLength(0));
    rerender({ id: 'RFQ-T4A' });
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[0].content).toBe('first RFQ question');
  });

  it('reset clears the conversation', async () => {
    const { result } = renderHook(() => useAssistantChat('RFQ-00009'));
    await act(() => result.current.send('hello'));
    act(() => result.current.reset());
    expect(result.current.messages).toEqual([]);
  });
});

describe('scope and directives', () => {
  it('takes the scope from the answer and keeps the pending question on a pick_rfq message', async () => {
    const ui = { type: 'pick_rfq', reason: 'Which?', options: [], allowAll: true, allowMultiple: true };
    fetchMock.mockImplementationOnce(async () => reply({ message: 'Which RFQs?', citations: [], model: null, rfq_id: null, scope: { mode: 'none' }, ui }));
    const { result } = renderHook(() => useAssistantChat(null));
    await act(() => result.current.send('go / no-go?'));
    expect(result.current.picker?.question).toBe('go / no-go?');
    await act(async () => { result.current.applyPick(result.current.picker!, { mode: 'all' }); });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(result.current.scope).toEqual({ mode: 'all' });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toMatchObject({ scope: { mode: 'all' }, messages: expect.arrayContaining([{ role: 'user', content: 'go / no-go?' }]) });
    expect(result.current.picker).toBeUndefined();
  });

  it('keeps the scope with the conversation', async () => {
    const { result, rerender } = renderHook(({ id }) => useAssistantChat(id), { initialProps: { id: null as string | null } });
    act(() => result.current.removeFromScope('all'));
    await act(async () => { result.current.applyPick({ id: 'x', role: 'assistant', content: '', at: 0 }, { mode: 'rfqs', rfqIds: ['RFQ-S1', 'RFQ-S2'] }); });
    rerender({ id: 'RFQ-S3' });
    await waitFor(() => expect(result.current.scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-S3'] }));
    rerender({ id: null });
    await waitFor(() => expect(result.current.scope).toEqual({ mode: 'none' })); // selecting resets to the selection
  });
});

describe('failures are messages, not the end', () => {
  it('shows the service error and lets the user ask again', async () => {
    fetchMock.mockResolvedValueOnce(reply({ error: 'Chat backend error: boom' }, 503));
    const { result } = renderHook(() => useAssistantChat('RFQ-00003'));
    await act(() => result.current.send('q1'));
    expect(result.current.messages[1]).toMatchObject({ role: 'assistant', failed: true, content: 'Chat backend error: boom' });
    await act(() => result.current.send('q2'));
    expect(result.current.messages[3]).toMatchObject({ role: 'assistant' });
    expect(result.current.messages[3].failed).toBeUndefined();
    // a failed turn is not sent back as conversation history
    const sent = JSON.parse(fetchMock.mock.calls[1][1].body as string).messages.map((m: { content: string }) => m.content);
    expect(sent).not.toContain('Chat backend error: boom');
  });

  it('says plainly that the service is unreachable', async () => {
    fetchMock.mockRejectedValueOnce(new Error('Failed to fetch'));
    const { result } = renderHook(() => useAssistantChat('RFQ-00004'));
    await act(() => result.current.send('q'));
    expect(result.current.messages[1].content).toContain("couldn't reach the assistant service");
    expect(result.current.messages[1].content).toContain('Nothing was guessed');
  });

  it('on an expired session clears it, goes to the login page and says so', async () => {
    fetchMock.mockResolvedValueOnce(reply({ error: 'Unauthorized — please log in' }, 401));
    const { result } = renderHook(() => useAssistantChat('RFQ-00005'));
    await act(() => result.current.send('q'));
    expect(session.clear).toHaveBeenCalled();
    expect(window.location.hash).toBe('#/login');
    expect(result.current.messages[1].content).toContain('session has expired');
  });

  it('Stop ends the wait without adding a message, and the next question still works', async () => {
    fetchMock.mockImplementationOnce((_url: string, init: RequestInit) => new Promise((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')));
    }));
    const { result } = renderHook(() => useAssistantChat('RFQ-00006'));
    let pending!: Promise<void>;
    act(() => { pending = result.current.send('slow question'); });
    await waitFor(() => expect(result.current.running).toBe(true));
    act(() => result.current.stop());
    await act(async () => { await pending; });
    expect(result.current.running).toBe(false);
    expect(result.current.messages.map((m) => m.role)).toEqual(['user']);
    await act(() => result.current.send('next'));
    expect(result.current.messages.at(-1)?.role).toBe('assistant');
  });
});
