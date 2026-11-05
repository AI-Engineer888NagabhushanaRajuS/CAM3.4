import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/config/endpoints', () => ({ PYTHON_BRIDGE_URL: 'http://bridge' }));
vi.mock('@/lib/apiAuth', () => ({ authFetch: vi.fn() }));
const scanFiles = vi.hoisted(() => vi.fn());
vi.mock('@/lib/rfqAttachments', async (orig) => ({ ...(await orig<typeof import('@/lib/rfqAttachments')>()), scanFiles }));

import { AttachFilesDialog } from '@/components/rfq/AttachFilesDialog';

const file = (name: string) => new File([new Uint8Array(100)], name);
const many = (n: number) => Array.from({ length: n }, (_, i) => file(`f${i}.csv`));
const engines = [
  { id: 'clamav', label: 'BuLL*Sav (ClamAV)', status: 'ok' },
  { id: 'repel', label: 'Repel Shield', status: 'ok' },
];
const answer = async (_rfq: string, fs: File[]) => ({
  rfq_id: 'RFQ-00001', engines,
  results: fs.map((f) => ({ name: f.name, size: 100, sha256: `sha-${f.name}`, clamav: { verdict: 'clean' }, repel: { verdict: 'clean', flags: [] }, decision: 'released', attachment_id: `id-${f.name}` })),
});
const open = (files: File[], onReleased = () => {}) =>
  render(<AttachFilesDialog open rfqId="RFQ-00001" files={files} alreadyAttached={[]} onClose={() => {}} onReleased={onReleased} />);

beforeEach(() => { scanFiles.mockReset(); });

describe('a pick over one scan limit goes in waves', () => {
  it('selects all 23, says 3 waves, runs them in order, shows Wave 2 of 3 and merges one result', async () => {
    const onReleased = vi.fn();
    const release: Array<() => void> = [];
    scanFiles.mockImplementation((_r: string, fs: File[]) => new Promise((res) => { release.push(() => res(answer('', fs))); }));
    open(many(23), onReleased);
    expect(screen.getByText(/23 of 23 selected · sent in 3 waves/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Scan 23 files' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Wave 1 of 3'));
    release[0]();
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Wave 2 of 3'));
    release[1]();
    await waitFor(() => expect(release).toHaveLength(3));
    release[2]();
    expect(await screen.findByText('Scan complete')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('23 of 23 released');
    expect(scanFiles.mock.calls.map((c) => (c[1] as File[]).length)).toEqual([10, 10, 3]);
    expect(onReleased).toHaveBeenCalledTimes(1);
  });

  it('stops at a failed wave, keeps the earlier verdicts and lists the files never sent', async () => {
    scanFiles.mockImplementationOnce(answer).mockRejectedValueOnce(new Error('The scan service answered HTTP 503'));
    const onReleased = vi.fn();
    open(many(23), onReleased);
    fireEvent.click(screen.getByRole('button', { name: 'Scan 23 files' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Wave 2 of 3 failed: The scan service answered HTTP 503');
    expect(alert.textContent).toContain('These 13 files were never scanned or released');
    expect(alert.textContent).toContain('f10.csv');
    expect(screen.getAllByRole('status').map((e) => e.textContent).join(' ')).toContain('10 of 10 released');
    expect(scanFiles).toHaveBeenCalledTimes(2);
    expect(onReleased).toHaveBeenCalledTimes(1);
  });

  it('keeps single-wave behaviour: no wave wording for a small pick', async () => {
    scanFiles.mockImplementation(answer);
    open(many(3));
    expect(screen.queryByText(/waves/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Scan 3 files' }));
    expect(await screen.findByText('Scan complete')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
