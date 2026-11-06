import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { InputFixDialog } from '@/components/rfq/InputFixDialog';
import { collectEdits, type CheckIssue, type CheckReport } from '@/lib/inputFix';
import { intakeReadiness, roleChip, type ScanResult } from '@/lib/rfqAttachments';

const api = vi.hoisted(() => ({
  fetchCheck: vi.fn(),
  submitFix: vi.fn(),
  downloadAttachment: vi.fn(async () => undefined),
}));
vi.mock('@/lib/inputFix', async (orig) => ({ ...(await orig<typeof import('@/lib/inputFix')>()), ...api }));

const issue = (over: Partial<CheckIssue>): CheckIssue => ({
  severity: 'error', code: 'quantity_text', sheet: 'SCRUB BOM', row: 3, col: 'I', column: 'Quantity', value: 'ten',
  message: 'Quantity "ten" is not a number.', fixable: true, ...over,
});
const report = (issues: CheckIssue[], over: Partial<CheckReport> = {}): CheckReport => ({
  checked: true, ok: issues.every((i) => i.severity !== 'error'), errors: issues.filter((i) => i.severity === 'error').length,
  warnings: issues.filter((i) => i.severity === 'warning').length, rows: 2, issues, truncated: false, ...over,
});

const open = (props: Partial<React.ComponentProps<typeof InputFixDialog>> = {}) =>
  render(<InputFixDialog open scope="CHAT-1" attachmentId="aaaaaaaaaaaa" name="Centum.xlsx" onClose={() => {}} {...props} />);

beforeEach(() => {
  vi.clearAllMocks();
  api.downloadAttachment.mockResolvedValue(undefined);
});

describe('InputFixDialog (SPEC-023)', () => {
  it('shows only the flagged cells, each with the address and what is wrong; Save stays off until something is typed', async () => {
    api.fetchCheck.mockResolvedValue({ ...report([issue({}), issue({ code: 'volume_blank', sheet: 'Settings', row: 2, col: 'B', column: 'V1 Qty', value: '', message: 'V1 Qty for FG-1 is empty.' })]), name: 'Centum.xlsx' });
    open();
    expect(await screen.findAllByTestId('fix-row')).toHaveLength(2);
    expect(screen.getByText('SCRUB BOM · I3')).toBeTruthy();
    expect(screen.getByText('Settings · B2')).toBeTruthy();
    expect(screen.getByTestId('fix-summary').textContent).toContain('2 to fix');
    expect((screen.getByRole('button', { name: /Save/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('sends only the cells that were changed, then downloads the corrected file when the re-check is clean, and offers to continue', async () => {
    api.fetchCheck.mockResolvedValue({ ...report([issue({}), issue({ row: 4, value: 'x', message: 'other' })]), name: 'Centum.xlsx' });
    api.submitFix.mockResolvedValue({ attachment_id: 'bbbbbbbbbbbb', name: 'Centum_corrected.xlsx', size: 1, sha256: 's', cells_changed: 1, report: report([]), check: { checked: true, ok: true, errors: 0, warnings: 0 } });
    const onFixed = vi.fn();
    const onContinue = vi.fn();
    const onClose = vi.fn();
    open({ onFixed, onContinue, onClose });
    await screen.findAllByTestId('fix-row');
    fireEvent.change(screen.getByLabelText('Type the number for SCRUB BOM I3'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Save 1 correction/ }));
    await waitFor(() => expect(api.submitFix).toHaveBeenCalledWith('CHAT-1', 'aaaaaaaaaaaa', [{ sheet: 'SCRUB BOM', row: 3, col: 'I', value: '10' }]));
    await waitFor(() => expect(api.downloadAttachment).toHaveBeenCalledWith('CHAT-1', 'bbbbbbbbbbbb', 'Centum_corrected.xlsx'));
    expect((await screen.findByTestId('fix-saved')).textContent).toContain('was downloaded to your computer');
    expect(onFixed).toHaveBeenCalledWith(expect.objectContaining({ attachment_id: 'bbbbbbbbbbbb' }), 'aaaaaaaaaaaa');
    fireEvent.click(screen.getByRole('button', { name: 'Continue with this file' }));
    expect(onContinue).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('when the re-check still finds problems it does not download, and shows what is left', async () => {
    api.fetchCheck.mockResolvedValue({ ...report([issue({})]), name: 'Centum.xlsx' });
    api.submitFix.mockResolvedValue({ attachment_id: 'bbbbbbbbbbbb', name: 'Centum_corrected.xlsx', size: 1, sha256: 's', cells_changed: 1, report: report([issue({ row: 7, col: 'D', code: 'cpn_blank', value: '', message: 'CPN is empty.' })]) });
    open();
    await screen.findAllByTestId('fix-row');
    fireEvent.change(screen.getByLabelText('Type the number for SCRUB BOM I3'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: /Save 1 correction/ }));
    expect(await screen.findByText('CPN is empty.')).toBeTruthy();
    expect(api.downloadAttachment).not.toHaveBeenCalled();
    expect(screen.queryByTestId('fix-saved')).toBeNull();
  });

  it('a suggestion button fills the number the text reads as; problems that need Excel are listed apart, with no box', async () => {
    api.fetchCheck.mockResolvedValue({ ...report([issue({ value: '12', suggestion: '12' }), issue({ code: 'fg_not_in_settings', fixable: false, sheet: 'Settings', row: null, col: null, message: 'FG FG-9 has no row in Settings.' })]), name: 'Centum.xlsx' });
    open();
    await screen.findAllByTestId('fix-row');
    expect(screen.getAllByTestId('fix-row')).toHaveLength(1);
    expect(screen.getByTestId('fix-needs-excel').textContent).toContain('FG FG-9 has no row in Settings.');
    fireEvent.click(screen.getByRole('button', { name: 'Use 12' }));
    expect((screen.getByLabelText('Type the number for SCRUB BOM I3') as HTMLInputElement).value).toBe('12');
  });

  it('says so plainly when saving fails', async () => {
    api.fetchCheck.mockResolvedValue({ ...report([issue({})]), name: 'Centum.xlsx' });
    api.submitFix.mockRejectedValue(new Error('The corrections were not applied: "=1+1" starts like a formula.'));
    open();
    await screen.findAllByTestId('fix-row');
    fireEvent.change(screen.getByLabelText('Type the number for SCRUB BOM I3'), { target: { value: '=1+1' } });
    fireEvent.click(screen.getByRole('button', { name: /Save 1 correction/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('starts like a formula');
  });
});

describe('collectEdits', () => {
  it('skips untouched boxes, boxes set back to what the file holds, and cells no single edit can fix', () => {
    const a = issue({});
    const b = issue({ row: 4, value: 'x' });
    const c = issue({ row: 5, fixable: false });
    expect(collectEdits([a, b, c], { 'SCRUB BOM!I3': '10', 'SCRUB BOM!I4': 'x', 'SCRUB BOM!I5': '7' })).toEqual([{ sheet: 'SCRUB BOM', row: 3, col: 'I', value: '10' }]);
  });
});

describe('readiness and chips follow the pre-flight', () => {
  const r = (over: Partial<ScanResult>): ScanResult => ({ name: 'a.xlsx', size: 1, sha256: 'x', clamav: { verdict: 'clean' }, repel: { verdict: 'clean' }, decision: 'released', attachment_id: 'aaaaaaaaaaaa', role: 'scrub_bom', ...over });

  it('a BOM with errors is not ready and carries what the fix button needs; warnings alone do not stop it', () => {
    const bad = intakeReadiness([r({ check: { checked: true, ok: false, errors: 2, warnings: 1 } })]);
    expect(bad.ready).toBe(false);
    expect(bad.fix).toEqual({ attachmentId: 'aaaaaaaaaaaa', name: 'a.xlsx', errors: 2, warnings: 1 });
    expect(bad.message).toContain('2 cells would give NaN or errors');
    expect(intakeReadiness([r({ check: { checked: true, ok: true, errors: 0, warnings: 9 } })]).ready).toBe(true);
  });

  it('the chip says how many cells to fix', () => {
    expect(roleChip({ role: 'scrub_bom', check: { checked: true, ok: false, errors: 3, warnings: 0 } })).toEqual({ text: 'BOM: 3 to fix', warn: true });
    expect(roleChip({ role: 'scrub_bom' })).toEqual({ text: 'BOM', warn: false });
  });
});
