import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const fetchAllRuns = vi.fn();
vi.mock('@/lib/runHistory', async (orig) => ({ ...(await orig<typeof import('@/lib/runHistory')>()), fetchAllRuns: (o: unknown) => fetchAllRuns(o) }));

import { UserCard } from '@/components/settings/users/UserCard';

const user = { id: 'u1', uid: 'dana', fullName: 'Dana Fox', email: 'dana@x.test', role: 'user', isActive: true } as never;
const run = (rfq: string, status: string) => ({ run_id: rfq + status, rfq_id: rfq, status, started_at: '2026-11-06T08:00:00Z', closed_at: null, duration_ms: 12000, started_by: 'Dana Fox', failure: null, can_rerun: false, failed_step: null });
const card = () => render(<UserCard user={user} onToggleActive={() => {}} onResetPassword={() => {}} onDelete={() => {}} />);

beforeEach(() => fetchAllRuns.mockReset());

describe('Users: Activity', () => {
  it('loads nothing until opened, then lists the runs this user started', async () => {
    fetchAllRuns.mockResolvedValue([run('RFQ-000018', 'waiting'), run('RFQ-000017', 'passed')]);
    card();
    expect(fetchAllRuns).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Activity' }));
    const list = await screen.findByTestId('user-activity');
    expect(fetchAllRuns).toHaveBeenCalledWith({ by: 'dana@x.test', limit: 10 });
    expect(list.textContent).toContain('RFQ-000018');
    expect(list.textContent).toContain('Waiting for your review');
    expect(list.textContent).toContain('RFQ-000017');
    fireEvent.click(screen.getByRole('button', { name: 'Hide activity' }));
    expect(screen.queryByTestId('user-activity')).toBeNull();
  });

  it('says so when the user has started nothing, and when the history cannot be read', async () => {
    fetchAllRuns.mockResolvedValueOnce([]);
    const v = card();
    fireEvent.click(screen.getByRole('button', { name: 'Activity' }));
    expect(await screen.findByText(/No runs started by this user yet/)).toBeTruthy();
    v.unmount();
    fetchAllRuns.mockRejectedValueOnce(new Error('HTTP 502'));
    card();
    fireEvent.click(screen.getByRole('button', { name: 'Activity' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('HTTP 502'));
  });
});
