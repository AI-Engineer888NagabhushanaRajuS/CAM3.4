import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}`, PYTHON_BRIDGE_URL: 'http://bridge' }));
vi.mock('@/components/rfq/ProviderSwitch', () => ({ ProviderSwitch: () => null }));
vi.mock('@/components/landing/TaskInputBar', () => ({
  TaskInputBar: (p: { value: string; onChange: (v: string) => void; onSubmit: () => void; isLoading?: boolean }) => (
    <div>
      <textarea data-testid="task-input-textarea" value={p.value} disabled={p.isLoading} onChange={(e) => p.onChange(e.target.value)} />
      <button type="button" data-testid="task-input-submit" onClick={p.onSubmit}>{p.isLoading ? 'Stop' : 'Submit'}</button>
    </div>
  ),
}));
const authDownload = vi.hoisted(() => vi.fn(async () => undefined));
vi.mock('@/lib/apiAuth', () => ({ authDownload }));
vi.mock('@/lib/rfqAttachments', async (orig) => ({ ...(await orig<typeof import('@/lib/rfqAttachments')>()), listAttachments: vi.fn(async () => []), deleteAttachment: vi.fn(async () => undefined) }));

import { RFQChatPane } from '@/components/rfq/RFQChatPane';

const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;
let next: unknown[] = [];
const answer = { message: 'Here you go.', citations: [], model: null, rfq_id: null };

beforeEach(() => {
  sessionStorage.clear();
  authDownload.mockReset();
  authDownload.mockImplementation(async () => undefined);
  next = [];
  fetchMock = vi.fn(async () => reply(next.shift() ?? answer));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const ask = (ui: unknown, props: Partial<React.ComponentProps<typeof RFQChatPane>> = {}) => {
  next = [{ ...answer, ui }];
  render(<RFQChatPane rfqId={null} isOpen inline {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Reset conversation' }));
  fireEvent.change(screen.getByTestId('task-input-textarea'), { target: { value: 'do it' } });
  fireEvent.click(screen.getByTestId('task-input-submit'));
};

describe('open_rfq', () => {
  it('selects the RFQ once with its id, then shows it as done (a second press is impossible)', async () => {
    const onSelectRfq = vi.fn();
    ask({ type: 'open_rfq', rfqId: 'RFQ-000017' }, { onSelectRfq });
    const button = await screen.findByRole('button', { name: 'Open RFQ-000017' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(onSelectRfq).toHaveBeenCalledTimes(1);
    expect(onSelectRfq).toHaveBeenCalledWith('RFQ-000017');
    expect(screen.queryByRole('button', { name: 'Open RFQ-000017' })).toBeNull();
    expect(screen.getByText('Opened RFQ-000017')).toBeTruthy();
  });

  it('draws no button when the host cannot select an RFQ', async () => {
    ask({ type: 'open_rfq', rfqId: 'RFQ-000017' });
    await screen.findByText('Here you go.');
    expect(screen.queryByRole('button', { name: /Open RFQ/ })).toBeNull();
  });

  it('ignores a directive without an id', async () => {
    ask({ type: 'open_rfq' }, { onSelectRfq: vi.fn() });
    await screen.findByText('Here you go.');
    expect(screen.queryByRole('button', { name: /Open RFQ/ })).toBeNull();
  });
});

describe('open_export', () => {
  it('downloads the RFQ reports through the authenticated helper', async () => {
    ask({ type: 'open_export', rfqId: 'RFQ-000017' });
    fireEvent.click(await screen.findByRole('button', { name: 'Download reports for RFQ-000017' }));
    await waitFor(() => expect(screen.getByText('Download started for RFQ-000017.')).toBeTruthy());
    expect(authDownload).toHaveBeenCalledTimes(1);
    expect(authDownload).toHaveBeenCalledWith('http://bridge/api/bom/export/RFQ-000017/download', 'RFQ-000017');
  });

  it('writes a visible error line when the download is refused, and allows another try', async () => {
    authDownload.mockImplementation(async () => { throw new Error('Download failed: HTTP 404'); });
    ask({ type: 'open_export', rfqId: 'RFQ-000017' });
    fireEvent.click(await screen.findByRole('button', { name: 'Download reports for RFQ-000017' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not download the reports for RFQ-000017');
    expect(alert.textContent).toContain('HTTP 404');
    authDownload.mockImplementation(async () => undefined);
    fireEvent.click(screen.getByRole('button', { name: 'Download reports for RFQ-000017' }));
    await waitFor(() => expect(authDownload).toHaveBeenCalledTimes(2));
  });
});

describe('open_settings', () => {
  it('opens Settings -> Providers through onOpenModelSettings', async () => {
    const onOpenModelSettings = vi.fn();
    ask({ type: 'open_settings', section: 'providers' }, { onOpenModelSettings });
    fireEvent.click(await screen.findByRole('button', { name: 'Open Settings' }));
    expect(onOpenModelSettings).toHaveBeenCalledTimes(1);
  });
});

describe('start_pipeline confirmation', () => {
  it('shows the RFQ, stage, customer and project, and confirms with one request', async () => {
    ask({
      type: 'confirm_action', action: 'start_pipeline', summary: 'Resume RFQ-000017', confirmToken: 'tp-1',
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
      params: { rfqId: 'RFQ-000017', stage: 3, customer: 'Centum', project: null },
    });
    expect(await screen.findByText('Start or resume the pipeline for RFQ-000017')).toBeTruthy();
    for (const t of ['RFQ id', 'Stage', 'Stage 3', 'Customer', 'Centum', 'Project', 'Not set']) {
      expect(screen.getByText(t)).toBeTruthy();
    }
    fetchMock.mockImplementation(async () => reply({ ok: true, message: 'Started.', rfqId: 'RFQ-000017', steps: [{ step: 'start_pipeline', status: 'done' }] }));
    const confirm = screen.getByRole('button', { name: 'Confirm' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.getByText('Confirmed.')).toBeTruthy());
    const confirms = fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/api/chat/actions/confirm'));
    expect(confirms).toHaveLength(1);
    expect(JSON.parse(confirms[0][1].body as string)).toEqual({ confirmToken: 'tp-1', decision: 'confirm' });
  });
});
