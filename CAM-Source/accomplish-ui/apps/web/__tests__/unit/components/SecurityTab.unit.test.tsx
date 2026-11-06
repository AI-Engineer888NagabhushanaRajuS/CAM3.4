import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/config/endpoints', () => ({ PYTHON_BRIDGE_URL: 'http://bridge' }));
const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/apiAuth', () => ({ authFetch }));

import { SecurityTab } from '@/components/settings/SecurityTab';

const telemetry = {
  engines: [
    { id: 'clamav', label: 'BuLL*Sav (ClamAV)', status: 'ok', detail: 'ClamAV 1.4.3, signatures 28173', signatures: 28173 },
    { id: 'repel', label: 'Repel Shield', status: 'ok', detail: 'Rule set 1.0', signatures: null },
  ],
  counts: { released: 7, quarantined: 2, held: 1, error: 0 },
  recent: [{ time: '2026-11-05T10:20:30Z', scope: 'RFQ-1', name: 'eicar.txt', decision: 'quarantined', reason: 'BuLL*Sav (ClamAV): Eicar FOUND', clamav: 'threat', repel: 'clean' }],
  policy: { failClosed: true, maxFiles: 10, maxFileBytes: 25 * 1024 * 1024, maxTotalBytes: 60 * 1024 * 1024 },
};
const memoryOff = { available: true, writesEnabled: false, provider: 'ollama', maxConcurrent: 1, running: 0, queued: 0 };
const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });

function serve(t: () => unknown, m: () => unknown) {
  authFetch.mockImplementation(async (url: string) => (url.endsWith('/api/security/telemetry') ? t() : m()));
}

beforeEach(() => { authFetch.mockReset(); });

describe('SecurityTab', () => {
  it('shows loading first, then engines, counts, decisions and the memory card', async () => {
    serve(() => json(telemetry), () => json(memoryOff));
    render(<SecurityTab />);
    expect(screen.getByRole('status').textContent).toContain('Loading');
    expect(await screen.findByText('28,173 signatures')).toBeTruthy();
    expect(authFetch.mock.calls[0][1]).toBe('SECURITY');
    expect(screen.getByText('Repel Shield')).toBeTruthy();
    expect(screen.getByText('Quarantined', { selector: 'dt' })).toBeTruthy();
    expect(screen.getByLabelText('Decisions in the last 30 days').textContent).toContain('7');
    expect(screen.getByText('eicar.txt')).toBeTruthy();
    expect(screen.getByText('Writes off')).toBeTruthy();
    expect(screen.getByText('Provider: local (Ollama)')).toBeTruthy();
    expect(screen.getByText(/set RFQ_MEMORY_LLM_WRITES=1 and, to avoid loading the local GPU, RFQ_MEMORY_LLM_PROVIDER=openrouter with a key in \.env, then rebuild rfq-memory-server/)).toBeTruthy();
  });

  it('shows cloud provider and queue numbers when writes are on, without the how-to', async () => {
    serve(() => json(telemetry), () => json({ ...memoryOff, writesEnabled: true, provider: 'openrouter', running: 1, queued: 4 }));
    render(<SecurityTab />);
    expect(await screen.findByText('Writes on')).toBeTruthy();
    expect(screen.getByText('Provider: cloud (OpenRouter)')).toBeTruthy();
    expect(screen.getByText(/1 running, 4 queued/)).toBeTruthy();
    expect(screen.queryByText(/To turn writes on/)).toBeNull();
  });

  it('says so when nothing was scanned and when the memory service is unreachable', async () => {
    serve(() => json({ ...telemetry, recent: [] }), () => json({ available: false, reason: 'memory service not reachable (OSError)' }));
    render(<SecurityTab />);
    expect(await screen.findByText('No files scanned in the last 30 days.')).toBeTruthy();
    expect(screen.getByText(/Memory service not reachable: memory service not reachable/)).toBeTruthy();
  });

  it('says an engine is unavailable in words', async () => {
    const down = { ...telemetry, engines: [{ ...telemetry.engines[0], status: 'unavailable', detail: 'cannot run clamscan', signatures: null }, telemetry.engines[1]] };
    serve(() => json(down), () => json(memoryOff));
    render(<SecurityTab />);
    expect(await screen.findByText('Unavailable')).toBeTruthy();
    expect(screen.getByText('cannot run clamscan')).toBeTruthy();
  });

  it('shows an error that stays fail-closed when the bridge fails', async () => {
    serve(() => json({}, 503), () => json(memoryOff));
    render(<SecurityTab />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('HTTP 503');
    expect(alert.textContent).toContain('fail-closed');
  });

  it('refreshes on demand', async () => {
    let n = 0;
    serve(() => json({ ...telemetry, counts: { ...telemetry.counts, released: ++n } }), () => json(memoryOff));
    render(<SecurityTab />);
    await screen.findByText('Recent decisions');
    expect(screen.getByLabelText('Decisions in the last 30 days').textContent).toContain('1');
    fireEvent.click(screen.getByRole('button', { name: /Refresh/ }));
    await waitFor(() => expect(screen.getByLabelText('Decisions in the last 30 days').textContent).toContain('2'));
  });
});
