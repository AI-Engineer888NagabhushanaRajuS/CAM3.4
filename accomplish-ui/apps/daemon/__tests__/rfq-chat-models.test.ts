import { describe, it, expect, vi, afterEach } from 'vitest';

const ENV = ['RFQ_CHAT_PROVIDER', 'RFQ_CHAT_CLOUD_FALLBACK', 'OPENROUTER_API_KEY', 'RFQ_CHAT_OPENROUTER_MODEL'];
async function load(env: Record<string, string> = {}) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) process.env[k] = v;
  return import('../src/rfq-chat/rfq-chat-models.js');
}
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const http = (status: number) => ({ ok: false, status, json: async () => ({}) }) as Response;
const ask = [{ role: 'user' as const, content: 'q' }];

afterEach(() => {
  vi.unstubAllGlobals();
  for (const k of ENV) delete process.env[k];
});

describe('which model answers: the key saved in Settings decides', () => {
  it('uses only the local model when there is no key', async () => {
    const { resolveChatModel } = await load();
    expect(resolveChatModel({}).label).toMatch(/^[^>]+\(local\)$/);
  });

  it('asks OpenRouter first when a key is saved, then the local model', async () => {
    const { resolveChatModel } = await load();
    expect(resolveChatModel({ settingsKey: 'k' }).label).toBe('anthropic/claude-haiku-5.5 (OpenRouter) -> qwen3:8b (local)');
  });

  it('uses the OpenRouter model selected in Settings, without its openrouter/ prefix', async () => {
    const { resolveChatModel } = await load();
    const m = resolveChatModel({ settingsKey: 'k', selected: { provider: 'openrouter', model: 'openrouter/google/gemini-2.5-flash' } });
    expect(m.label).toContain('google/gemini-2.5-flash (OpenRouter)');
  });

  it('ignores a selected model of another provider', async () => {
    const { resolveChatModel } = await load();
    expect(resolveChatModel({ settingsKey: 'k', selected: { provider: 'ollama', model: 'llama3' } }).label).toContain('claude-haiku-5.5 (OpenRouter)');
  });

  it('RFQ_CHAT_PROVIDER=local keeps the data on this machine even with a key', async () => {
    const { resolveChatModel } = await load({ RFQ_CHAT_PROVIDER: 'local' });
    expect(resolveChatModel({ settingsKey: 'k' }).label).not.toContain('OpenRouter');
  });

  it('an env key counts only when cloud use is switched on', async () => {
    const off = await load({ OPENROUTER_API_KEY: 'env-key' });
    expect(off.resolveChatModel({}).label).not.toContain('OpenRouter');
    const on = await load({ OPENROUTER_API_KEY: 'env-key', RFQ_CHAT_CLOUD_FALLBACK: '1' });
    expect(on.resolveChatModel({}).label).toContain('OpenRouter');
  });
});

describe('the chain of models', () => {
  it('sends the Settings key to OpenRouter and reports who answered', async () => {
    const fetchMock = vi.fn(async () => ok({ choices: [{ message: { content: 'cloud answer' } }] }));
    vi.stubGlobal('fetch', fetchMock);
    const { resolveChatModel } = await load();
    const out = await resolveChatModel({ settingsKey: 'secret-key' }).complete(ask);
    expect(out).toEqual({ text: 'cloud answer', model: 'anthropic/claude-haiku-5.5 (OpenRouter)' });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('openrouter.ai');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-key');
    expect(JSON.parse(init.body as string).temperature).toBe(0.1);
  });

  it('falls back to the local model when OpenRouter fails, and says so', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (url.includes('openrouter') ? http(404) : ok({ message: { content: 'local answer' } }))));
    const { resolveChatModel } = await load();
    const out = await resolveChatModel({ settingsKey: 'k' }).complete(ask);
    expect(out?.text).toBe('local answer');
    expect(out?.model).toContain('(local)');
  });

  it('returns null, never a made-up reply, when every model is down', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('ECONNREFUSED'); }));
    const { resolveChatModel } = await load();
    expect(await resolveChatModel({ settingsKey: 'k' }).complete(ask)).toBeNull();
  });

  it('asks the local model without its reasoning and with a window big enough for the evidence', async () => {
    const fetchMock = vi.fn(async () => ok({ message: { content: '<think>hmm</think>The MOQ is 5000 [2].' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { localModel } = await load();
    const out = await localModel().complete(ask);
    expect(out?.text).toBe('The MOQ is 5000 [2].');
    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(body).toMatchObject({ think: false, stream: false, options: { temperature: 0.1, num_ctx: 12288 } });
  });

  it('stops asking models once the user pressed Stop', async () => {
    const fetchMock = vi.fn(async () => ok({ message: { content: 'x' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { resolveChatModel } = await load();
    const stop = new AbortController();
    stop.abort();
    expect(await resolveChatModel({ settingsKey: 'k' }).complete(ask, stop.signal)).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
