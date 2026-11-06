import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const fetchRuns = vi.fn();
vi.mock('@/lib/runHistory', async (orig) => ({ ...(await orig<typeof import('@/lib/runHistory')>()), fetchRuns: (id: string) => fetchRuns(id) }));

import { FailedRunNotice, RunHistory, RightViewToggle } from '@/components/rfq/RunHistory';
import { badgeWord, formatDuration, type RunEntry } from '@/lib/runHistory';

const run = (over: Partial<RunEntry>): RunEntry => ({
  run_id: 'r', status: 'passed', started_at: '2026-11-06T08:00:00Z', closed_at: '2026-11-06T08:01:35Z', duration_ms: 95000,
  started_by: 'Dana', failed_step: null, failure: null, can_rerun: false, ...over,
});
const failure = (kind: 'invalid_input' | 'tool_error', can: boolean) => ({
  kind, title: kind === 'invalid_input' ? 'Invalid input: no ‘SCRUB BOM’ sheet' : 'Export reports failed', cause: 'cause text', next_step: 'next step text',
  step: 'Step', can_rerun: can, raw: 'raw text',
});

beforeEach(() => fetchRuns.mockReset());

describe('formatting', () => {
  it('durations read in seconds, minutes, hours; unknown (running) is a dash', () => {
    expect(formatDuration(12000)).toBe('12 s');
    expect(formatDuration(185000)).toBe('3 min 05 s');
    expect(formatDuration(3720000)).toBe('1 h 02 min');
    expect(formatDuration(null)).toBe('—');
  });
  it('a failure says what kind it is', () => {
    expect(badgeWord(run({ status: 'failed', failure: failure('invalid_input', false) }))).toBe('Invalid input');
    expect(badgeWord(run({ status: 'failed', failure: failure('tool_error', true) }))).toBe('Failed');
    expect(badgeWord(run({ status: 'replaced' }))).toMatch(/Replaced/);
    expect(badgeWord(run({ status: 'waiting' }))).toBe('Waiting for your review');
  });
});

describe('RunHistory', () => {
  it('lists runs with who, how long and the cause of a failure; a wrong file is never offered a rerun', async () => {
    fetchRuns.mockResolvedValue([run({ run_id: 'a', status: 'failed', failure: failure('invalid_input', false) }), run({ run_id: 'b' })]);
    render(<RunHistory rfqId="RFQ-1" onRerun={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId('run-row')).toHaveLength(2));
    expect(screen.getByText('Invalid input')).toBeTruthy();
    expect(screen.getByText(/no ‘SCRUB BOM’ sheet/)).toBeTruthy();
    expect(screen.getByText('next step text')).toBeTruthy();
    expect(screen.getAllByText('1 min 35 s')).toHaveLength(2);
    expect(screen.getAllByText('by Dana')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /Run again/ })).toBeNull();
  });

  it('offers Run again only on the newest run, and calls the resume handler for this RFQ', async () => {
    fetchRuns.mockResolvedValue([run({ run_id: 'new', status: 'failed', can_rerun: true, failure: failure('tool_error', true) }), run({ run_id: 'old', status: 'failed', can_rerun: true, failure: failure('tool_error', true) })]);
    const onRerun = vi.fn().mockResolvedValue(undefined);
    render(<RunHistory rfqId="RFQ-1" onRerun={onRerun} />);
    const buttons = await screen.findAllByRole('button', { name: /Run again/ });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(onRerun).toHaveBeenCalledWith('RFQ-1'));
  });

  it('says so in words when there are no runs or the history cannot be read', async () => {
    fetchRuns.mockResolvedValueOnce([]);
    const { unmount } = render(<RunHistory rfqId="RFQ-1" onRerun={() => {}} />);
    expect(await screen.findByText(/No runs yet/)).toBeTruthy();
    unmount();
    fetchRuns.mockRejectedValueOnce(new Error('HTTP 502'));
    render(<RunHistory rfqId="RFQ-1" onRerun={() => {}} />);
    expect((await screen.findByRole('alert')).textContent).toContain('HTTP 502');
  });
});

describe('RightViewToggle', () => {
  it('marks the current view and switches', () => {
    const onChange = vi.fn();
    render(<RightViewToggle view="workflow" onChange={onChange} />);
    expect(screen.getByRole('button', { name: 'Workflow' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    expect(onChange).toHaveBeenCalledWith('history');
  });
});

describe('FailedRunNotice', () => {
  it('appears only when the newest run failed, with the next step and a way to the history', () => {
    const open = vi.fn();
    const { rerender } = render(<FailedRunNotice run={run({ status: 'failed', failure: failure('invalid_input', false) })} onOpenHistory={open} />);
    expect(screen.getByRole('alert').textContent).toContain('next step text');
    fireEvent.click(screen.getByRole('button', { name: 'See history' }));
    expect(open).toHaveBeenCalled();
    rerender(<FailedRunNotice run={run({ status: 'passed' })} onOpenHistory={open} />);
    expect(screen.queryByRole('alert')).toBeNull();
    rerender(<FailedRunNotice run={null} onOpenHistory={open} />);
    expect(screen.queryByTestId('failed-run-notice')).toBeNull();
  });
});
