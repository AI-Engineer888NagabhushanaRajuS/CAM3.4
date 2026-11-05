import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ScopeChips } from '@/components/rfq/ScopeChips';

describe('scope chips', () => {
  it('shows each RFQ and removes just that one', () => {
    const onRemove = vi.fn();
    render(<ScopeChips scope={{ mode: 'rfqs', rfqIds: ['RFQ-1', 'RFQ-2'] }} onRemove={onRemove} />);
    expect(screen.getByRole('list', { name: 'Conversation scope' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove RFQ-2 from scope' }));
    expect(onRemove).toHaveBeenCalledWith('RFQ-2');
  });

  it('shows All context as a removable chip', () => {
    const onRemove = vi.fn();
    render(<ScopeChips scope={{ mode: 'all' }} onRemove={onRemove} />);
    expect(screen.getByText('All context')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove All context from scope' }));
    expect(onRemove).toHaveBeenCalledWith('all');
  });

  it('says so when no RFQ is chosen', () => {
    render(<ScopeChips scope={{ mode: 'none' }} onRemove={() => {}} />);
    expect(screen.getByText('No RFQ chosen')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
