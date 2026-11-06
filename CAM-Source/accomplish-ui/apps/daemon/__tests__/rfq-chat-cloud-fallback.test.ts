import { describe, it, expect, vi, afterEach } from 'vitest';

const chunk = { text: 'A-class spend: 1234.56', citation: { source: 'cbom', id: 'C1' } } as const;

async function load(env: Record<string, string>) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) process.env[k] = v;
  return import('../src/rfq-chat/rfq-chat-prompt.js');
}

function ok(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  for (const k of ['RFQ_CHAT_CLOUD_FALLBACK', 'OPENROUTER_API_KEY']) delete process.env[k];
});

describe('RFQ chat answer: local model first, OpenRouter only when opted in', () => {
  it('answers from the local model and never calls OpenRouter', async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url.includes('/api/chat') ? ok({ message: { content: 'Local answer' } }) : ok({}));
    vi.stubGlobal('fetch', fetchMock);
    const { synthesizeAnswer } = await load({ RFQ_CHAT_CLOUD_FALLBACK: '1', OPENROUTER_API_KEY: 'k' });
    const out = await synthesizeAnswer({ question: 'q', chunks: [chunk] });
    expect(out.answer).toBe('Local answer');
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('openrouter'))).toBe(false);
  });

  it('falls back to OpenRouter when Ollama is down and the flag and key are set', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('/api/chat')) throw new Error('ECONNREFUSED');
      return ok({ choices: [{ message: { content: 'Cloud answer' } }] });
    });
    vi.stubGlobal('fetch', fetchMock);
    const { synthesizeAnswer } = await load({ RFQ_CHAT_CLOUD_FALLBACK: '1', OPENROUTER_API_KEY: 'secret-key' });
    const out = await synthesizeAnswer({ question: 'q', chunks: [chunk] });
    expect(out.answer).toBe('Cloud answer');
    const call = fetchMock.mock.calls.find(([u]) => String(u).includes('openrouter.ai'));
    expect(call).toBeDefined();
    expect((call![1] as RequestInit).headers).toMatchObject({ Authorization: 'Bearer secret-key' });
  });

  it('never leaves the machine unless the flag is on, even with a key', async () => {
    const fetchMock = vi.fn(async () => { throw new Error('ECONNREFUSED'); });
    vi.stubGlobal('fetch', fetchMock);
    const { synthesizeAnswer } = await load({ OPENROUTER_API_KEY: 'k' });
    const out = await synthesizeAnswer({ question: 'q', chunks: [chunk] });
    expect(out.answer).toBeNull();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('openrouter'))).toBe(false);
  });
});
