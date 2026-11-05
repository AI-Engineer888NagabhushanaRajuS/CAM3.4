import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}`, PYTHON_BRIDGE_URL: 'http://bridge' }));

vi.mock('@/components/landing/TaskInputBar', () => ({
  TaskInputBar: (p: { value: string; onChange: (v: string) => void; onSubmit: () => void; isLoading?: boolean; toolbarLeft?: React.ReactNode }) => (
    <div>
      <textarea data-testid="task-input-textarea" value={p.value} disabled={p.isLoading} onChange={(e) => p.onChange(e.target.value)} />
      {p.toolbarLeft}
      <button type="button" data-testid="task-input-submit" onClick={p.onSubmit}>{p.isLoading ? 'Stop' : 'Submit'}</button>
    </div>
  ),
}));

const listAttachments = vi.hoisted(() => vi.fn(async () => [] as unknown[]));
vi.mock('@/lib/rfqAttachments', async (orig) => ({ ...(await orig<typeof import('@/lib/rfqAttachments')>()), listAttachments, deleteAttachment: vi.fn(async () => undefined) }));

import { RFQChatPane } from '@/components/rfq/RFQChatPane';

const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;
const bodyOf = (i: number) => JSON.parse(fetchMock.mock.calls[i][1].body as string);
let next: unknown[] = [];

const pick = {
  type: 'pick_rfq', reason: 'Which RFQs is this about?', allowAll: true, allowMultiple: true,
  options: [
    { rfqId: 'RFQ-P1', customer: 'Acme', project: 'Pump', stage: 4, reviewPending: true, hasExport: true },
    { rfqId: 'RFQ-P2', customer: 'Centum', project: 'Radar', stage: null, reviewPending: false, hasExport: false },
  ],
};
const answer = { message: 'GO (Manifest!A32:C32).', citations: [], model: null, rfq_id: null };

beforeEach(() => {
  sessionStorage.clear();
  listAttachments.mockResolvedValue([]);
  next = [];
  fetchMock = vi.fn(async () => reply(next.shift() ?? answer));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const type = (text: string) => {
  fireEvent.change(screen.getByTestId('task-input-textarea'), { target: { value: text } });
  fireEvent.click(screen.getByTestId('task-input-submit'));
};
// The conversation without an RFQ lives in a module-level store shared by the tests: start each one from a reset.
const renderNoRfq = () => {
  const view = render(<RFQChatPane rfqId={null} isOpen inline />);
  fireEvent.click(screen.getByRole('button', { name: 'Reset conversation' }));
  return view;
};
const composerReady = () => expect((screen.getByTestId('task-input-textarea') as HTMLTextAreaElement).disabled).toBe(false);

describe('scope', () => {
  it('starts as the RFQ selected in the left list, is sent with every question and follows the answer', async () => {
    next = [{ ...answer, scope: { mode: 'rfqs', rfqIds: ['SC-A', 'SC-B'] } }];
    render(<RFQChatPane rfqId="SC-A" isOpen inline />);
    expect(screen.getByRole('button', { name: 'Remove SC-A from scope' })).toBeTruthy();
    type('status?');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove SC-B from scope' })).toBeTruthy());
    expect(fetchMock.mock.calls[0][0]).toBe('http://daemon/api/chat');
    expect(bodyOf(0).scope).toEqual({ mode: 'rfqs', rfqIds: ['SC-A'] });
    type('and now?');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(bodyOf(1).scope).toEqual({ mode: 'rfqs', rfqIds: ['SC-A', 'SC-B'] });
  });

  it('removing a chip changes the scope sent next; removing the last one is normal chat', async () => {
    render(<RFQChatPane rfqId="SC-C" isOpen inline />);
    fireEvent.click(screen.getByRole('button', { name: 'Remove SC-C from scope' }));
    expect(screen.getByText('No RFQ chosen')).toBeTruthy();
    type('hello');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(bodyOf(0).scope).toEqual({ mode: 'none' });
  });

  it('keeps a scope per conversation and resets to the RFQ when another one is selected on the left', async () => {
    const { rerender } = render(<RFQChatPane rfqId="SC-D" isOpen inline />);
    fireEvent.click(screen.getByRole('button', { name: 'Remove SC-D from scope' }));
    rerender(<RFQChatPane rfqId="SC-E" isOpen inline />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove SC-E from scope' })).toBeTruthy());
  });
});

describe('pick_rfq', () => {
  it('opens the popup, and picking sets the scope and sends the pending question again', async () => {
    next = [{ ...answer, message: 'Which RFQs?', ui: pick, scope: { mode: 'none' } }];
    renderNoRfq();
    type('what is the go / no-go status?');
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByText('Which RFQs is this about?')).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/RFQ-P1/));
    fireEvent.click(screen.getByRole('button', { name: 'Use selected (1)' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(bodyOf(1).scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-P1'] });
    expect(bodyOf(1).messages.at(-1)).toEqual({ role: 'user', content: 'what is the go / no-go status?' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove RFQ-P1 from scope' })).toBeTruthy());
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByText(/Scope set: RFQ-P1/)).toBeTruthy();
    composerReady();
  });

  it('All context sets the All scope and asks again', async () => {
    next = [{ ...answer, message: 'Which RFQs?', ui: pick }];
    renderNoRfq();
    type('compare the suppliers');
    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: 'All context' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(bodyOf(1).scope).toEqual({ mode: 'all' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove All context from scope' })).toBeTruthy());
  });

  it('Esc cancels: the scope stays, nothing is sent, the composer is there and the popup can be reopened', async () => {
    next = [{ ...answer, message: 'Which RFQs?', ui: pick }];
    renderNoRfq();
    type('status?');
    await screen.findByRole('dialog');
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText('No RFQ chosen')).toBeTruthy();
    composerReady();
    fireEvent.click(screen.getByRole('button', { name: 'Choose RFQs' }));
    expect(await screen.findByRole('dialog')).toBeTruthy();
  });
});

describe('disambiguate', () => {
  const ui = { type: 'disambiguate', prompt: 'Which one did you mean?', options: [{ id: 'RFQ-D1', label: 'RFQ-D1 (Acme)', detail: 'Pump' }, { id: 'p-7', label: 'Part A7 in the BOM' }] };

  it('an RFQ option sets the scope and asks the question again', async () => {
    next = [{ ...answer, message: 'Two matches.', ui }];
    renderNoRfq();
    type('price of the pump?');
    fireEvent.click(await screen.findByRole('button', { name: /RFQ-D1 \(Acme\)/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(bodyOf(1).scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-D1'] });
    expect(bodyOf(1).messages.at(-1).content).toBe('price of the pump?');
    expect(screen.getByText('Chosen: RFQ-D1 (Acme)')).toBeTruthy();
    composerReady();
  });

  it('any other option is sent as the next user turn, once', async () => {
    next = [{ ...answer, message: 'Two matches.', ui }];
    renderNoRfq();
    type('which part?');
    const button = await screen.findByRole('button', { name: /Part A7/ });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(bodyOf(1).messages.at(-1)).toEqual({ role: 'user', content: 'Part A7 in the BOM' });
    expect((screen.getByRole('button', { name: /Part A7/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('confirm_action', () => {
  it('draws the card in the bubble and keeps the composer', async () => {
    next = [{ ...answer, message: 'Ready to create it.', ui: {
      type: 'confirm_action', action: 'create_rfq', summary: 'Create RFQ from bom.xlsx', confirmToken: 't-1',
      expiresAt: new Date(Date.now() + 300_000).toISOString(), params: { customer: 'Acme', project: 'Pump', files: ['bom.xlsx'], flow: 'standard' },
    } }];
    renderNoRfq();
    type('create an RFQ from this');
    expect(await screen.findByRole('button', { name: 'Confirm' })).toBeTruthy();
    expect(screen.getByText('Create RFQ from bom.xlsx')).toBeTruthy();
    composerReady();
  });
});

describe('ask_upload', () => {
  it('opens the existing file picker with the accepted types', async () => {
    next = [{ ...answer, message: 'Send the BOM.', ui: { type: 'ask_upload', accept: ['.xlsx', '.csv'], purpose: 'The BOM for the new RFQ' } }];
    const { container } = render(<RFQChatPane rfqId="UP-1" isOpen inline />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const click = vi.spyOn(input, 'click').mockImplementation(() => undefined);
    type('make an RFQ from my file');
    fireEvent.click(await screen.findByRole('button', { name: 'Choose files' }));
    expect(click).toHaveBeenCalledTimes(1);
    expect(input.accept).toBe('.xlsx,.csv');
    composerReady();
  });

  it('opens the file picker even with no RFQ: the files are scanned in a staging scope', async () => {
    next = [{ ...answer, message: 'Send the BOM.', ui: { type: 'ask_upload', accept: ['.xlsx'], purpose: 'The BOM' } }];
    const { container } = renderNoRfq();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const click = vi.spyOn(input, 'click').mockImplementation(() => undefined);
    type('make an RFQ from my file');
    fireEvent.click(await screen.findByRole('button', { name: 'Choose files' }));
    expect(click).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Choose an RFQ first/)).toBeNull();
  });
});

describe('ignores a malformed directive', () => {
  it('shows the text and keeps working', async () => {
    next = [{ ...answer, message: 'Plain answer.', ui: { type: 'pick_rfq' } }];
    renderNoRfq();
    type('hi');
    await screen.findByText('Plain answer.');
    expect(screen.queryByRole('dialog')).toBeNull();
    composerReady();
  });
});
