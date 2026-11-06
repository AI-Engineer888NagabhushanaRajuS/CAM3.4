import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const fetchRuns = vi.fn();
const fetchAllRuns = vi.fn();
vi.mock('@/lib/runHistory', async (orig) => ({ ...(await orig<typeof import('@/lib/runHistory')>()), fetchRuns: (id: string) => fetchRuns(id), fetchAllRuns: (o?: unknown) => fetchAllRuns(o) }));

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

beforeEach(() => { fetchRuns.mockReset(); fetchAllRuns.mockReset(); });

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

describe('RunHistory tracking across RFQs', () => {
  it('with no RFQ open it lists the runs of every RFQ, each naming its RFQ and who started it, and opens an RFQ on click', async () => {
    fetchAllRuns.mockResolvedValue([run({ run_id: 'a', rfq_id: 'RFQ-000018', started_by: 'Lee', started_by_email: 'lee@x.test' }), run({ run_id: 'b', rfq_id: 'RFQ-000017', started_by: 'Dana' })]);
    const onOpenRfq = vi.fn();
    render(<RunHistory rfqId={null} onRerun={() => {}} onOpenRfq={onOpenRfq} isAdmin />);
    expect((await screen.findAllByTestId('run-row'))).toHaveLength(2);
    expect(screen.getByText('all RFQs, all users')).toBeTruthy();
    expect(screen.getByText('by Lee').getAttribute('title')).toBe('lee@x.test');
    expect(screen.queryByRole('group', { name: 'Which runs' })).toBeNull(); // no RFQ open: nothing to switch between
    fireEvent.click(screen.getByRole('button', { name: 'RFQ-000018' }));
    expect(onOpenRfq).toHaveBeenCalledWith('RFQ-000018');
    expect(fetchRuns).not.toHaveBeenCalled();
  });

  it('with an RFQ open it starts on that RFQ and can switch to everyone (admin) or my runs (anybody else)', async () => {
    fetchRuns.mockResolvedValue([run({ run_id: 'x' })]);
    fetchAllRuns.mockResolvedValue([run({ run_id: 'y', rfq_id: 'RFQ-000019' })]);
    const view = render(<RunHistory rfqId="RFQ-000017" onRerun={() => {}} onOpenRfq={() => {}} isAdmin={false} />);
    await screen.findAllByTestId('run-row');
    expect(fetchRuns).toHaveBeenCalledWith('RFQ-000017');
    fireEvent.click(screen.getByRole('button', { name: 'My runs' }));
    expect(await screen.findByRole('button', { name: 'RFQ-000019' })).toBeTruthy();
    expect(screen.getByText('the runs you started')).toBeTruthy();
    view.unmount();
    render(<RunHistory rfqId="RFQ-000017" onRerun={() => {}} isAdmin />);
    expect(screen.getByRole('button', { name: 'All RFQs' })).toBeTruthy();
  });

  it('shows a person chip per user with their counts and narrows the list to one person', async () => {
    fetchAllRuns.mockResolvedValue([
      run({ run_id: '1', rfq_id: 'RFQ-1', started_by: 'Dana', status: 'passed' }),
      run({ run_id: '2', rfq_id: 'RFQ-2', started_by: 'Dana', status: 'failed', failure: failure('tool_error', true) }),
      run({ run_id: '3', rfq_id: 'RFQ-3', started_by: 'Lee', status: 'waiting' }),
    ]);
    render(<RunHistory rfqId={null} onRerun={() => {}} onOpenRfq={() => {}} isAdmin />);
    await screen.findAllByTestId('run-row');
    expect(screen.getByRole('button', { name: 'Everyone (3)' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Dana (2)' }));
    expect(screen.getAllByTestId('run-row')).toHaveLength(2);
    expect(screen.getByTestId('user-summary').textContent).toContain('Dana: 2 runs · 1 passed · 1 failed · 0 open');
    fireEvent.click(screen.getByRole('button', { name: 'Lee (1)' }));
    expect(screen.getByTestId('user-summary').textContent).toContain('1 open');
    fireEvent.click(screen.getByRole('button', { name: 'Everyone (3)' }));
    expect(screen.getAllByTestId('run-row')).toHaveLength(3);
  });

  it('says so when nobody has run anything yet', async () => {
    fetchAllRuns.mockResolvedValue([]);
    render(<RunHistory rfqId={null} onRerun={() => {}} />);
    expect(await screen.findByText(/No runs recorded yet/)).toBeTruthy();
  });
});
