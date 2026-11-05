import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}` }));

import { ConfirmActionCard } from '@/components/rfq/ConfirmActionCard';
import type { UiDirective } from '@/lib/chatContract';

const soon = () => new Date(Date.now() + 5 * 60_000).toISOString();
const pipeline = (params: Record<string, unknown>, expiresAt = soon()): Extract<UiDirective, { type: 'confirm_action' }> => ({
  type: 'confirm_action', action: 'start_pipeline', summary: 'Resume the pipeline', confirmToken: 'tok-2', expiresAt, params,
});
const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;
const onSettle = vi.fn();

beforeEach(() => {
  onSettle.mockReset();
  fetchMock = vi.fn(async () => reply({ ok: true, message: 'Started.', rfqId: 'RFQ-000017', steps: [{ step: 'start_pipeline', status: 'done' }] }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('start_pipeline card', () => {
  it('says in words what will happen and lists RFQ id, stage, customer and project', () => {
    render(<ConfirmActionCard ui={pipeline({ rfqId: 'RFQ-000017', stage: 2, customer: 'Acme', project: 'Pump' })} onSettle={onSettle} />);
    expect(screen.getByText('Start or resume the pipeline for RFQ-000017')).toBeTruthy();
    for (const t of ['RFQ id', 'RFQ-000017', 'Stage', 'Stage 2', 'Customer', 'Acme', 'Project', 'Pump']) {
      expect(screen.getByText(t)).toBeTruthy();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows a missing stage, customer and project as words, not as null', () => {
    render(<ConfirmActionCard ui={pipeline({ rfqId: 'RFQ-000017', stage: null, customer: null, project: null })} onSettle={onSettle} />);
    expect(screen.getByText('Not started yet')).toBeTruthy();
    expect(screen.getAllByText('Not set')).toHaveLength(2);
    expect(screen.queryByText('null')).toBeNull();
  });

  it('keeps single-click confirm', async () => {
    render(<ConfirmActionCard ui={pipeline({ rfqId: 'RFQ-000017', stage: 1, customer: 'A', project: 'B' })} onSettle={onSettle} />);
    const confirm = screen.getByRole('button', { name: 'Confirm' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(onSettle).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
  });

  it('keeps the expiry behaviour', () => {
    render(<ConfirmActionCard ui={pipeline({ rfqId: 'RFQ-000017', stage: 1, customer: 'A', project: 'B' }, new Date(Date.now() - 1000).toISOString())} onSettle={onSettle} />);
    expect(screen.getByText(/Expired/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull();
  });
});
