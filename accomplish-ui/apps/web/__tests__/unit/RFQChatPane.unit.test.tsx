import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}`, PYTHON_BRIDGE_URL: 'http://bridge' }));

// The real composer needs speech, model and i18n plumbing; the pane only relies on its props.
vi.mock('@/components/landing/TaskInputBar', () => ({
  TaskInputBar: (p: { value: string; onChange: (v: string) => void; onSubmit: () => void; isLoading?: boolean; placeholder?: string; toolbarLeft?: React.ReactNode }) => (
    <div>
      <textarea data-testid="task-input-textarea" value={p.value} placeholder={p.placeholder} disabled={p.isLoading} onChange={(e) => p.onChange(e.target.value)} />
      {p.toolbarLeft}
      <button type="button" data-testid="task-input-submit" onClick={p.onSubmit}>{p.isLoading ? 'Stop' : 'Submit'}</button>
    </div>
  ),
}));

const listAttachments = vi.hoisted(() => vi.fn(async () => [] as unknown[]));
vi.mock('@/lib/rfqAttachments', async (orig) => ({ ...(await orig<typeof import('@/lib/rfqAttachments')>()), listAttachments, deleteAttachment: vi.fn(async () => undefined) }));

import { RFQChatPane } from '@/components/rfq/RFQChatPane';

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear();
  listAttachments.mockResolvedValue([]);
  fetchMock = vi.fn(async () => ok({ message: 'The status is **GO** (Manifest!A32:C32).', citations: [{ sourceType: 'excel_export', label: 'Manifest!A32:C32', identifier: {} }], model: 'qwen3:8b (local)' }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const type = (text: string) => {
  fireEvent.change(screen.getByTestId('task-input-textarea'), { target: { value: text } });
  fireEvent.click(screen.getByTestId('task-input-submit'));
};

describe('RFQChatPane: one persistent conversation', () => {
  it('shows the message list as a live log with the composer, and the RFQ it answers about', () => {
    render(<RFQChatPane rfqId="UI-A1" isOpen inline />);
    expect(screen.getByRole('log')).toBeTruthy();
    expect(screen.getByTestId('task-input-textarea')).toBeTruthy();
    expect(screen.getByText('UI-A1')).toBeTruthy();
    expect(screen.getByText(/Answers come only from the RFQ/)).toBeTruthy();
  });

  it('keeps the composer and the whole conversation after an answer, and takes a second question', async () => {
    render(<RFQChatPane rfqId="UI-A2" isOpen inline />);
    type('what is the status?');
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(1));
    expect(screen.getByTestId('task-input-textarea')).toBeTruthy(); // it used to disappear here
    expect((screen.getByTestId('task-input-textarea') as HTMLTextAreaElement).disabled).toBe(false);
    type('and who supplies it?');
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(2));
    expect(screen.getAllByTestId('user-message')).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shows where an answer came from', async () => {
    render(<RFQChatPane rfqId="UI-A3" isOpen inline />);
    type('status?');
    await waitFor(() => expect(screen.getByText('Manifest!A32:C32', { selector: 'span' })).toBeTruthy());
    expect(screen.getByText(/Every figure checked against the cited row · qwen3:8b \(local\)/)).toBeTruthy();
  });

  it('answers a suggestion card with its prompt', async () => {
    render(<RFQChatPane rfqId="UI-A4" isOpen inline />);
    fireEvent.click(screen.getByRole('button', { name: /Uncosted parts/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.messages.at(-1)).toEqual({ role: 'user', content: 'Which parts have no pricing (uncosted) in this RFQ?' });
  });

  it('is the same assistant without an RFQ: it posts to the general route and cannot take files', async () => {
    render(<RFQChatPane rfqId={null} isOpen inline />);
    expect((screen.getByRole('button', { name: 'Add files' }) as HTMLButtonElement).disabled).toBe(true);
    type('which RFQs do I have?');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe('http://daemon/api/chat');
  });

  it('turns an error into a message and stays usable', async () => {
    fetchMock.mockRejectedValueOnce(new Error('Failed to fetch'));
    render(<RFQChatPane rfqId="UI-A5" isOpen inline />);
    type('hello?');
    await waitFor(() => expect(screen.getByText(/couldn't reach the assistant service/)).toBeTruthy());
    expect((screen.getByTestId('task-input-textarea') as HTMLTextAreaElement).disabled).toBe(false);
  });

  it('lists the files the assistant may read and lets you remove one', async () => {
    listAttachments.mockResolvedValue([{ attachment_id: 'abc123', name: 'quote.xlsx', size: 10, sha256: 'x', released_at: '2026-11-05T10:00:00Z' }]);
    render(<RFQChatPane rfqId="UI-A6" isOpen inline />);
    expect(await screen.findByText('quote.xlsx')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Remove quote.xlsx' })).toBeTruthy();
  });

  it('renders nothing when closed in floating mode', () => {
    const { container } = render(<RFQChatPane rfqId="UI-A7" isOpen={false} />);
    expect(container.firstChild).toBeNull();
  });
});
