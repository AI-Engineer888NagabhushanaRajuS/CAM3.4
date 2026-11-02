import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { RFQChatPane } from '@/components/rfq/RFQChatPane';

describe('RFQChatPane', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => ({
      json: async () => ({ message: 'ok', citations: [] }),
    }));
    vi.stubGlobal('fetch', fetchMock);
  });

  it('labels the composer and exposes the message list as a live log', () => {
    render(<RFQChatPane rfqId="CE-1" isOpen onClose={() => {}} />);
    expect(screen.getByRole('textbox', { name: 'Ask about this RFQ' })).toBeTruthy();
    expect(screen.getByRole('log')).toBeTruthy();
  });

  it('does not send while an IME composition is confirming on Enter', () => {
    render(<RFQChatPane rfqId="CE-1" isOpen onClose={() => {}} />);
    const input = screen.getByRole('textbox', { name: 'Ask about this RFQ' });
    fireEvent.change(input, { target: { value: 'half composed' } });
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends the prompt of a suggestion chip', async () => {
    render(<RFQChatPane rfqId="CE-1" isOpen onClose={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Uncosted parts' }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.messages.at(-1)).toEqual({
      role: 'user',
      content: 'Which parts have no pricing (uncosted) in this RFQ?',
    });
  });
});
