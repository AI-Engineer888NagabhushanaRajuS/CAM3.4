import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { RfqPickerDialog } from '@/components/rfq/RfqPickerDialog';
import type { RfqOption } from '@/lib/chatContract';

const options: RfqOption[] = [
  { rfqId: 'RFQ-00001', customer: 'Acme', project: 'Pump', stage: 3, reviewPending: true, hasExport: false },
  { rfqId: 'RFQ-00002', customer: 'Centum', project: 'Radar', stage: 9, reviewPending: false, hasExport: true },
  { rfqId: 'RFQ-00003', customer: null, project: null, stage: null, reviewPending: false, hasExport: false },
];
const onPick = vi.fn();
const onCancel = vi.fn();
const open = (initial: string[] = []) => render(<RfqPickerDialog reason="Which RFQs?" options={options} initial={initial} onPick={onPick} onCancel={onCancel} />);

beforeEach(() => { onPick.mockReset(); onCancel.mockReset(); }); // not returned: vitest would call a returned function as a cleanup

describe('RFQ picker popup', () => {
  it('lists id, customer, project, steps, review and export state in words', () => {
    open();
    expect(screen.getByText('Which RFQs?')).toBeTruthy();
    expect(screen.getByText('Acme · Pump')).toBeTruthy();
    expect(screen.getByText('Steps done: 3')).toBeTruthy();
    expect(screen.getByText('Review pending')).toBeTruthy();
    expect(screen.getByText('Export available')).toBeTruthy();
    expect(screen.getByText('Not started')).toBeTruthy();
  });

  it('filters by id, customer or project', () => {
    open();
    fireEvent.change(screen.getByRole('searchbox', { name: /Search RFQs/ }), { target: { value: 'radar' } });
    expect(screen.getByLabelText(/RFQ-00002/)).toBeTruthy();
    expect(screen.queryByLabelText(/RFQ-00001/)).toBeNull();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zzz' } });
    expect(screen.getByText('No RFQ matches this search.')).toBeTruthy();
  });

  it('multi-selects and uses the selection', () => {
    open();
    const use = screen.getByRole('button', { name: 'Use selected (0)' }) as HTMLButtonElement;
    expect(use.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/RFQ-00001/));
    fireEvent.click(screen.getByLabelText(/RFQ-00003/));
    fireEvent.click(screen.getByRole('button', { name: 'Use selected (2)' }));
    expect(onPick).toHaveBeenCalledWith({ mode: 'rfqs', rfqIds: ['RFQ-00001', 'RFQ-00003'] });
  });

  it('starts with the RFQs already in scope ticked', () => {
    open(['RFQ-00002']);
    expect((screen.getByLabelText(/RFQ-00002/) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('button', { name: 'Use selected (1)' })).toBeTruthy();
  });

  it('All context picks the whole scope without ticking anything', () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: 'All context' }));
    expect(onPick).toHaveBeenCalledWith({ mode: 'all' });
  });

  it('Cancel and Esc close it without picking', () => {
    open();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onPick).not.toHaveBeenCalled();
  });
});
