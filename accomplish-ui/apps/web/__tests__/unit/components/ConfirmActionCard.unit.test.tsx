import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}` }));

import { ConfirmActionCard } from '@/components/rfq/ConfirmActionCard';
import type { ConfirmOutcome } from '@/components/rfq/useAssistantChat';
import type { UiDirective } from '@/lib/chatContract';

const card = (expiresAt: string): Extract<UiDirective, { type: 'confirm_action' }> => ({
  type: 'confirm_action', action: 'create_rfq', summary: 'Create an RFQ from bom.xlsx', confirmToken: 'tok-1', expiresAt,
  params: { customer: 'Acme', project: 'Pump', files: ['bom.xlsx', { name: 'vol.xlsx' }], flow: 'standard' },
});
const soon = () => new Date(Date.now() + 5 * 60_000).toISOString();
const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;
const onSettle = vi.fn();

beforeEach(() => {
  onSettle.mockReset();
  fetchMock = vi.fn(async () => reply({
    ok: true, message: 'RFQ created.', rfqId: 'RFQ-00042',
    steps: [{ step: 'Create RFQ', status: 'done' }, { step: 'Scan files', status: 'done' }],
  }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('confirmation card', () => {
  it('shows the summary and the exact parameters before anything happens', () => {
    render(<ConfirmActionCard ui={card(soon())} onSettle={onSettle} />);
    expect(screen.getByText('Create an RFQ from bom.xlsx')).toBeTruthy();
    for (const t of ['Customer', 'Acme', 'Project', 'Pump', 'Files', 'bom.xlsx', 'vol.xlsx', 'Flow', 'standard']) {
      expect(screen.getByText(t)).toBeTruthy();
    }
    expect(screen.getByText(/Valid until/)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('confirms once: one request, both buttons gone after the first click', async () => {
    render(<ConfirmActionCard ui={card(soon())} onSettle={onSettle} />);
    const confirm = screen.getByRole('button', { name: 'Confirm' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
    await waitFor(() => expect(onSettle).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('http://daemon/api/chat/actions/confirm');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({ confirmToken: 'tok-1', decision: 'confirm' });
    expect(onSettle.mock.calls[0][0]).toMatchObject({ state: 'confirmed', response: { rfqId: 'RFQ-00042' } });
  });

  it('shows every step in words, the failure detail and the new RFQ id once settled', () => {
    const outcome: ConfirmOutcome = {
      state: 'failed',
      response: {
        ok: false, message: 'Stopped at Start pipeline.', rfqId: 'RFQ-00042',
        steps: [{ step: 'Create RFQ', status: 'done' }, { step: 'Start pipeline', status: 'failed', detail: 'bridge down' }, { step: 'Report', status: 'skipped' }],
      },
    };
    render(<ConfirmActionCard ui={card(soon())} outcome={outcome} onSettle={onSettle} />);
    expect(screen.getByText('Done')).toBeTruthy();
    expect(screen.getByText('Failed')).toBeTruthy();
    expect(screen.getByText('Skipped')).toBeTruthy();
    expect(screen.getByText(/bridge down/)).toBeTruthy();
    expect(screen.getByText('RFQ-00042')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
  });

  it('Cancel sends the cancel decision and says nothing was changed', async () => {
    fetchMock.mockImplementation(async () => reply({ ok: true, message: 'Cancelled.', steps: [] }));
    render(<ConfirmActionCard ui={card(soon())} onSettle={onSettle} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(onSettle).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string).decision).toBe('cancel');
    expect(onSettle.mock.calls[0][0].state).toBe('cancelled');
  });

  it('an expired card offers no buttons and says so', () => {
    render(<ConfirmActionCard ui={card(new Date(Date.now() - 1000).toISOString())} onSettle={onSettle} />);
    expect(screen.getByText(/Expired/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('expires while it is on screen', () => {
    vi.useFakeTimers();
    try {
      render(<ConfirmActionCard ui={card(new Date(Date.now() + 2000).toISOString())} onSettle={onSettle} />);
      expect(screen.getByRole('button', { name: 'Confirm' })).toBeTruthy();
      act(() => { vi.advanceTimersByTime(3000); });
      expect(screen.getByText(/Expired/)).toBeTruthy();
      expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('a network failure is reported and the buttons stay gone (the token is single use)', async () => {
    fetchMock.mockImplementation(async () => { throw new Error('Failed to fetch'); });
    render(<ConfirmActionCard ui={card(soon())} onSettle={onSettle} />);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(onSettle).toHaveBeenCalledWith({ state: 'failed', error: 'Failed to fetch' }));
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull();
  });
});
