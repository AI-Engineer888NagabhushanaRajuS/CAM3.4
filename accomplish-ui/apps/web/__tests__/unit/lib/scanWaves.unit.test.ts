import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/config/endpoints', () => ({ PYTHON_BRIDGE_URL: 'http://bridge' }));
vi.mock('@/lib/apiAuth', () => ({ authFetch: vi.fn() }));
const scanFiles = vi.hoisted(() => vi.fn());
vi.mock('@/lib/rfqAttachments', async (orig) => ({ ...(await orig<typeof import('@/lib/rfqAttachments')>()), scanFiles }));

import { scanInWaves } from '@/lib/scanWaves';

const files = (n: number) => Array.from({ length: n }, (_, i) => new File(['x'], `f${i}.csv`));
const reply = (fs: File[]) => ({ rfq_id: 'R', engines: [], results: fs.map((f) => ({ name: f.name, decision: 'released' })) });

beforeEach(() => { scanFiles.mockReset(); });

describe('scanInWaves', () => {
  it('runs the waves one after another and merges every verdict', async () => {
    scanFiles.mockImplementation(async (_r: string, fs: File[]) => reply(fs));
    const seen: Array<[number, number]> = [];
    const out = await scanInWaves('R', files(23), { onWave: (n, of) => seen.push([n, of]) });
    expect(scanFiles.mock.calls.map((c) => (c[1] as File[]).length)).toEqual([10, 10, 3]);
    expect(seen).toEqual([[1, 3], [2, 3], [3, 3]]);
    expect(out.failure).toBeNull();
    expect(out.response?.results).toHaveLength(23);
  });

  it('stops at a failed wave, keeps earlier verdicts and names the files never sent', async () => {
    scanFiles.mockImplementationOnce(async (_r: string, fs: File[]) => reply(fs)).mockRejectedValueOnce(new Error('HTTP 503'));
    const out = await scanInWaves('R', files(23));
    expect(scanFiles).toHaveBeenCalledTimes(2);
    expect(out.response?.results).toHaveLength(10);
    expect(out.failure).toMatchObject({ message: 'HTTP 503', wave: 2, waves: 3 });
    expect(out.failure?.unsent.map((f) => f.name)).toEqual(files(23).slice(10).map((f) => f.name));
  });

  it('has no response when the first wave fails', async () => {
    scanFiles.mockRejectedValue(new Error('down'));
    const out = await scanInWaves('R', files(3));
    expect(out.response).toBeNull();
    expect(out.failure?.unsent).toHaveLength(3);
  });

  it('rethrows an abort instead of reporting a failure', async () => {
    const controller = new AbortController();
    scanFiles.mockImplementation(async () => { controller.abort(); throw new Error('aborted'); });
    await expect(scanInWaves('R', files(3), { signal: controller.signal })).rejects.toThrow('aborted');
  });
});
