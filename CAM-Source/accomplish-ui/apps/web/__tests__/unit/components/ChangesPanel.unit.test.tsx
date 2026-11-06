import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

const authFetch = vi.fn();
const authDownload = vi.fn(async () => undefined);
vi.mock('@/lib/apiAuth', () => ({ authFetch: (...a: unknown[]) => authFetch(...a), authDownload: (...a: unknown[]) => authDownload(...a) }));
vi.mock('@/config/endpoints', () => ({ PYTHON_BRIDGE_URL: 'http://bridge', backendUrl: (p: string) => `http://daemon${p}` }));
vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));

import { ChangesPanel, describeDiff } from '@/components/rfq/ChangesPanel';
import { OpenManifestDirective } from '@/components/rfq/OpenDirectives';
import { ConfirmActionCard } from '@/components/rfq/ConfirmActionCard';
import { Directive } from '@/components/rfq/AssistantDirectives';
import { parseUi, type UiDirective } from '@/lib/chatContract';
import { isRfqChangeEvent, pushRfqChangeEvent, resetRfqChanges } from '@/lib/rfqChanges';

const RFQ = 'RFQ-00007';
const json = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => body }) as Response;

beforeEach(() => {
  resetRfqChanges();
  authFetch.mockReset();
  authDownload.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

describe('ChangesPanel timeline', () => {
  it('starts empty with words, and the timeline is a polite live region', () => {
    authFetch.mockResolvedValue(json([]));
    render(<ChangesPanel rfqId={RFQ} />);
    expect(screen.getByText(/No value changes yet for RFQ-00007/)).toBeTruthy();
    expect(document.querySelector('[aria-live="polite"]')).not.toBeNull();
  });

  it('shows changed, regenerating and ready (new file, cells, sheets, Download) in order', async () => {
    render(<ChangesPanel rfqId={RFQ} />);
    act(() => {
      pushRfqChangeEvent({ event: 'rfq:value-changed', rfqId: RFQ, fields: ['final_moq'], items: 1 });
      pushRfqChangeEvent({ event: 'rfq:reports-regenerating', rfqId: RFQ });
    });
    expect(screen.getByText('Value changed:')).toBeTruthy();
    expect(screen.getByText(/final_moq \(1 item\)/)).toBeTruthy();
    expect(screen.getByText('Regenerating:')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Download' })).toBeNull();
    act(() => pushRfqChangeEvent({ event: 'rfq:reports-ready', rfqId: RFQ, filename: 'CBOM_v2.xlsx', totalChangedCells: 14, sheets: [{ sheet: 'A' }, { sheet: 'B' }] }));
    expect(screen.getByText('Reports ready:')).toBeTruthy();
    expect(screen.getByText(/new version CBOM_v2.xlsx, 14 changed cells across 2 sheets/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await waitFor(() => expect(authDownload).toHaveBeenCalledTimes(1));
    expect(String(authDownload.mock.calls[0][0])).toContain('/api/bom/export/RFQ-00007/download');
  });

  it('shows a failure in words with the message', () => {
    render(<ChangesPanel rfqId={RFQ} />);
    act(() => pushRfqChangeEvent({ event: 'rfq:reports-failed', rfqId: RFQ, message: 'builder crashed' }));
    expect(screen.getByText('Failed:')).toBeTruthy();
    expect(screen.getByText(/builder crashed/)).toBeTruthy();
  });

  it('ignores other RFQs, other events and malformed frames', () => {
    render(<ChangesPanel rfqId={RFQ} />);
    act(() => {
      pushRfqChangeEvent({ event: 'rfq:reports-ready', rfqId: 'RFQ-99999', filename: 'x.xlsx' });
      pushRfqChangeEvent({ event: 'rfq:skill-progress', rfqId: RFQ });
      pushRfqChangeEvent({ event: 'rfq:value-changed' });
      pushRfqChangeEvent(null);
    });
    expect(screen.getByText(/No value changes yet/)).toBeTruthy();
    expect(isRfqChangeEvent('rfq:reports-ready')).toBe(true);
    expect(isRfqChangeEvent('rfq:skill-progress')).toBe(false);
  });

  it('keeps events that arrived before the panel mounted', () => {
    pushRfqChangeEvent({ event: 'rfq:reports-regenerating', rfqId: RFQ });
    render(<ChangesPanel rfqId={RFQ} />);
    expect(screen.getByText('Regenerating:')).toBeTruthy();
  });
});

describe('Versions list', () => {
  const versions = [
    { filename: 'CBOM_v2.xlsx', generated_at: '2026-11-05T10:00:00Z', diff_summary: { total_changed_cells: 14, sheets: [{}, {}] } },
    { filename: 'CBOM_v1.xlsx', generated_at: '2026-11-05T09:00:00Z', diff_summary: null },
  ];

  it('is collapsed until opened, then lists versions newest first with summaries and a download each', async () => {
    authFetch.mockResolvedValue(json(versions));
    render(<ChangesPanel rfqId={RFQ} />);
    const toggle = screen.getByRole('button', { name: /Versions/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(authFetch).not.toHaveBeenCalled();
    fireEvent.click(toggle);
    await screen.findByText('CBOM_v2.xlsx');
    expect(String(authFetch.mock.calls[0][0])).toBe('http://bridge/api/rfq/RFQ-00007/exports');
    expect(screen.getByText('Latest')).toBeTruthy();
    expect(screen.getByText(/14 changed cells across 2 sheets/)).toBeTruthy();
    expect(screen.getByText(/First version, nothing to compare with/)).toBeTruthy();
    const buttons = screen.getAllByRole('button', { name: 'Download' });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(authDownload).toHaveBeenCalledTimes(1));
    expect(String(authDownload.mock.calls[0][0])).toContain('/exports/CBOM_v1.xlsx/download');
  });

  it('says so in words when the list cannot be loaded, and when it is empty', async () => {
    authFetch.mockResolvedValueOnce(json({}, false));
    render(<ChangesPanel rfqId={RFQ} />);
    fireEvent.click(screen.getByRole('button', { name: /Versions/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('Could not load the versions');
  });

  it('reloads the list when a new version is announced', async () => {
    authFetch.mockResolvedValue(json(versions));
    render(<ChangesPanel rfqId={RFQ} />);
    fireEvent.click(screen.getByRole('button', { name: /Versions/ }));
    await screen.findByText('CBOM_v2.xlsx');
    act(() => pushRfqChangeEvent({ event: 'rfq:reports-ready', rfqId: RFQ, filename: 'CBOM_v3.xlsx', totalChangedCells: 1, sheets: 1 }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
  });

  it('describeDiff reads strings, counts and null', () => {
    expect(describeDiff('3 cells')).toBe('3 cells');
    expect(describeDiff({ total_changed_cells: 1, sheets: 1 })).toBe('1 changed cell across 1 sheet');
    expect(describeDiff(undefined)).toContain('First version');
  });
});

describe('open_manifest directive', () => {
  it('is kept by parseUi only with a path and label', () => {
    expect(parseUi({ type: 'open_manifest', path: 'skills/a.json', label: 'A' })).toBeTruthy();
    expect(parseUi({ type: 'open_manifest', path: '', label: 'A' })).toBeUndefined();
    expect(parseUi({ type: 'open_manifest', path: 'x' })).toBeUndefined();
  });
  it('renders a button-link to #/manifests?path=...', () => {
    render(<OpenManifestDirective path="skills/skill 1.json" label="Input Standardization (skill 1)" />);
    const link = screen.getByRole('link', { name: /Input Standardization \(skill 1\)/ });
    expect(link.getAttribute('href')).toBe('#/manifests?path=skills%2Fskill%201.json');
  });
  it('is drawn by the assistant directive switch', () => {
    const msg = { id: 'm', role: 'assistant', content: '', ui: { type: 'open_manifest', path: 'agent/a.json', label: 'Agent' } as UiDirective } as never;
    render(<Directive msg={msg} busy={false} actions={{ onChoose: vi.fn(), onOpenPicker: vi.fn(), onUpload: vi.fn(), onSettle: vi.fn() }} />);
    expect(screen.getByRole('link', { name: /Agent/ }).getAttribute('href')).toBe('#/manifests?path=agent%2Fa.json');
  });
});

describe('edit_value card', () => {
  const ui: Extract<UiDirective, { type: 'confirm_action' }> = {
    type: 'confirm_action', action: 'edit_value', summary: 'Change MOQ of PN-100', confirmToken: 't', expiresAt: new Date(Date.now() + 300_000).toISOString(),
    params: { rfqId: RFQ, bomItemId: 'b1', label: 'PN-100', field: 'final_moq', fieldLabel: 'MOQ', before: 100, after: 500 },
  };
  it('lists RFQ, item, field, current value and new value', () => {
    render(<ConfirmActionCard ui={ui} onSettle={vi.fn()} />);
    for (const t of ['RFQ', RFQ, 'Item', 'PN-100 (bom item b1)', 'Field', 'MOQ', 'Current value', '100', 'New value', '500']) {
      expect(screen.getAllByText(t).length).toBeGreaterThan(0);
    }
    expect(screen.getByText('Change MOQ and regenerate the reports')).toBeTruthy();
  });
  it('shows an empty current value in words', () => {
    render(<ConfirmActionCard ui={{ ...ui, params: { ...ui.params, before: null } }} onSettle={vi.fn()} />);
    expect(screen.getByText('Empty')).toBeTruthy();
  });
  it('after Confirm the reply with open_export shows the download button', () => {
    const outcome = { state: 'confirmed' as const, response: { ok: true, message: 'Changed.', rfqId: RFQ, steps: [], ui: { type: 'open_export' as const, rfqId: RFQ } } };
    render(<ConfirmActionCard ui={ui} outcome={outcome} onSettle={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Download reports for RFQ-00007/ })).toBeTruthy();
  });
});
