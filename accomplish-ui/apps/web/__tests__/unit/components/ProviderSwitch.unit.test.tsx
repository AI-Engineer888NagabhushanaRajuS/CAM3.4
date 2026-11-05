import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok' }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}` }));

import { ProviderSwitch } from '@/components/rfq/ProviderSwitch';

const info = (hasKey: boolean) => ({ local: { model: 'qwen3:8b' }, openrouter: { hasKey, model: 'anthropic/claude-haiku-5.5' }, defaultMode: 'auto' });
const answer = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => { fetchMock = vi.fn(async () => answer(info(true))); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => vi.unstubAllGlobals());

describe('Local / OpenRouter switch', () => {
  it('shows three choices with the current one checked and asks the daemon what it can offer, with the session token', async () => {
    render(<ProviderSwitch mode="local" onChange={() => {}} />);
    expect(screen.getByRole('radiogroup', { name: 'Model provider' })).toBeTruthy();
    expect(screen.getByRole('radio', { name: /Local/ }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('radio', { name: /Auto/ }).getAttribute('aria-checked')).toBe('false');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://daemon/api/chat/providers');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
  });

  it('switches to OpenRouter when a key is saved', async () => {
    const onChange = vi.fn();
    render(<ProviderSwitch mode="auto" onChange={onChange} />);
    await waitFor(() => expect(screen.getByRole('radio', { name: /OpenRouter/ }).getAttribute('title')).toContain('claude-haiku-5.5'));
    fireEvent.click(screen.getByRole('radio', { name: /OpenRouter/ }));
    expect(onChange).toHaveBeenCalledWith('openrouter');
  });

  it('opens Settings instead of switching when no OpenRouter key is saved, and says so in words', async () => {
    fetchMock.mockImplementation(async () => answer(info(false)));
    const onChange = vi.fn();
    const onOpenSettings = vi.fn();
    render(<ProviderSwitch mode="auto" onChange={onChange} onOpenSettings={onOpenSettings} />);
    const radio = screen.getByRole('radio', { name: /OpenRouter/ });
    await waitFor(() => expect(radio.textContent).toContain('no API key saved')); // said in words for screen readers, not only by the amber dot
    fireEvent.click(radio);
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
    expect(radio.getAttribute('title')).toContain('no API key saved');
  });

  it('local and auto always work, even when the daemon cannot say whether a key exists', async () => {
    fetchMock.mockImplementation(async () => { throw new Error('ECONNREFUSED'); });
    const onChange = vi.fn();
    render(<ProviderSwitch mode="auto" onChange={onChange} />);
    fireEvent.click(screen.getByRole('radio', { name: /Local/ }));
    expect(onChange).toHaveBeenCalledWith('local');
  });

  it('tells the user that OpenRouter sends the RFQ rows off the machine', async () => {
    render(<ProviderSwitch mode="auto" onChange={() => {}} />);
    await waitFor(() => expect(screen.getByRole('radio', { name: /OpenRouter/ }).getAttribute('title')).toContain('sent to OpenRouter'));
  });
});
