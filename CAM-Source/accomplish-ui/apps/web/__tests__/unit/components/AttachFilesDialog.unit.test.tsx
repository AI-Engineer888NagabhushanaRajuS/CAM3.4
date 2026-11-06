import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/config/endpoints', () => ({ PYTHON_BRIDGE_URL: 'http://bridge' }));
vi.mock('@/lib/apiAuth', () => ({ authFetch: vi.fn() }));
vi.mock('@uppy/react', async () => import('../helpers/fakeUppyReact'));

const scanFiles = vi.hoisted(() => vi.fn());
vi.mock('@/lib/rfqAttachments', async (orig) => ({ ...(await orig<typeof import('@/lib/rfqAttachments')>()), scanFiles }));

import { AttachFilesDialog } from '@/components/rfq/AttachFilesDialog';
import type { ScanResponse } from '@/lib/rfqAttachments';

const file = (name: string, bytes = 100) => new File([new Uint8Array(bytes)], name);
const engines = [
  { id: 'clamav' as const, label: 'BuLL*Sav (ClamAV)', status: 'ok' as const },
  { id: 'repel' as const, label: 'Repel Shield', status: 'ok' as const },
];
const result = (name: string, over: Record<string, unknown> = {}) => ({
  name, size: 100, sha256: `sha-${name}`, clamav: { verdict: 'clean' }, repel: { verdict: 'clean', flags: [] },
  decision: 'released', attachment_id: `id-${name}`, ...over,
});

const open = (files: File[], extra: Partial<React.ComponentProps<typeof AttachFilesDialog>> = {}) =>
  render(<AttachFilesDialog open rfqId="RFQ-00001" files={files} alreadyAttached={[]} onClose={() => {}} onReleased={() => {}} {...extra} />);

beforeEach(() => { scanFiles.mockReset(); }); // not returned: vitest would call a returned function as a cleanup

describe('review: select or reject before anything is sent', () => {
  it('lists what can be sent, selected by default, and what is rejected with the reason', () => {
    open([file('quote.xlsx'), file('terms.pdf'), file('setup.exe')]);
    expect(screen.getByLabelText('Remove quote.xlsx')).toBeTruthy(); // a tile per usable file
    expect(screen.getByLabelText('Remove terms.pdf')).toBeTruthy();
    expect(screen.queryByLabelText('Remove setup.exe')).toBeNull();
    expect(screen.getByText(/Rejected \(1\)/)).toBeTruthy();
    expect(screen.getByText(/Unsupported type/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Scan 2 files' })).toBeTruthy();
  });

  it('sends only the files that stay on the dashboard', async () => {
    scanFiles.mockResolvedValue({ rfq_id: 'RFQ-00001', engines, results: [result('terms.pdf')] } satisfies ScanResponse);
    open([file('quote.xlsx'), file('terms.pdf')]);
    fireEvent.click(screen.getByLabelText('Remove quote.xlsx'));
    fireEvent.click(screen.getByRole('button', { name: 'Scan 1 file' }));
    await waitFor(() => expect(scanFiles).toHaveBeenCalledTimes(1));
    expect(scanFiles.mock.calls[0][0]).toBe('RFQ-00001');
    expect((scanFiles.mock.calls[0][1] as File[]).map((f) => f.name)).toEqual(['terms.pdf']);
  });

  it('cannot scan with nothing selected', () => {
    open([file('quote.xlsx')]);
    fireEvent.click(screen.getByRole('button', { name: 'Remove all' }));
    expect((screen.getByRole('button', { name: /^Scan/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('turns a second copy of an attached file away', () => {
    open([file('quote.xlsx')], { alreadyAttached: ['Quote.xlsx'] });
    expect(screen.getByText(/Already in this selection or already attached/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /^Scan/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('the verdicts of both engines are shown as they are', () => {
  it('shows released, quarantined and held files, each with both engines, and refreshes the context list once', async () => {
    const onReleased = vi.fn();
    scanFiles.mockResolvedValue({
      rfq_id: 'RFQ-00001', engines,
      results: [
        result('quote.xlsx'),
        result('eicar.txt', { clamav: { verdict: 'threat', detail: 'Eicar-Signature' }, decision: 'quarantined', attachment_id: null, reason: 'BuLL*Sav (ClamAV) found Eicar-Signature' }),
        result('notes.docx', { repel: { verdict: 'threat', flags: ['prompt_injection', 'hidden_chars'], score: 80 }, decision: 'quarantined', attachment_id: null }),
        result('odd.csv', { clamav: { verdict: 'error', detail: 'scan failed' }, decision: 'error', attachment_id: null, reason: 'BuLL*Sav (ClamAV) could not scan: held, not released' }),
      ],
    } satisfies ScanResponse);
    open([file('quote.xlsx'), file('eicar.txt'), file('notes.docx'), file('odd.csv')], { onReleased });
    fireEvent.click(screen.getByRole('button', { name: 'Scan 4 files' }));
    expect(await screen.findByText('Scan complete')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('1 of 4 released');
    expect(screen.getByText('BuLL*Sav (ClamAV) found Eicar-Signature')).toBeTruthy();
    expect(screen.getByText(/Repel flags: prompt_injection, hidden_chars/)).toBeTruthy();
    expect(screen.getByText('BuLL*Sav (ClamAV) could not scan: held, not released')).toBeTruthy();
    expect(screen.getAllByText('Repel Shield: threat')).toHaveLength(1);
    expect(onReleased).toHaveBeenCalledTimes(1);
  });

  it('keeps showing the verdicts after the release refreshes the attached list (found in the real UI)', async () => {
    scanFiles.mockResolvedValue({ rfq_id: 'RFQ-00001', engines, results: [result('quote.xlsx')] } satisfies ScanResponse);
    const files = [file('quote.xlsx')];
    const view = open(files);
    fireEvent.click(screen.getByRole('button', { name: 'Scan 1 file' }));
    expect(await screen.findByText('Scan complete')).toBeTruthy();
    // the pane refreshes its list: the released file is now "already attached", which must not reset the dialog
    view.rerender(<AttachFilesDialog open rfqId="RFQ-00001" files={files} alreadyAttached={['quote.xlsx']} onClose={() => {}} onReleased={() => {}} />);
    expect(screen.getByText('Scan complete')).toBeTruthy();
    expect(screen.queryByText(/Already in this selection or already attached/)).toBeNull();
  });

  it('says files are held when an engine is unavailable', async () => {
    scanFiles.mockResolvedValue({
      rfq_id: 'RFQ-00001',
      engines: [{ ...engines[0], status: 'unavailable' }, engines[1]],
      results: [result('quote.xlsx', { clamav: { verdict: 'error' }, decision: 'error', attachment_id: null, reason: 'engine unavailable' })],
    } satisfies ScanResponse);
    open([file('quote.xlsx')]);
    fireEvent.click(screen.getByRole('button', { name: 'Scan 1 file' }));
    expect(await screen.findByText(/BuLL\*Sav \(ClamAV\) is unavailable\. Files are held, not released/)).toBeTruthy();
  });

  it('keeps the selection and says nothing was released when the scan service fails', async () => {
    scanFiles.mockImplementation(async () => { throw new Error('The scan service answered HTTP 503'); });
    open([file('quote.xlsx')]);
    fireEvent.click(screen.getByRole('button', { name: 'Scan 1 file' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('HTTP 503. Nothing was released.');
    expect(screen.getByRole('button', { name: 'Scan 1 file' })).toBeTruthy(); // can try again
  });
});

describe('SPEC-022: what the files are, and the next step', () => {
  const role = (name: string, r: string, label: string, over: Record<string, unknown> = {}) => result(name, { role: r, role_label: label, role_reason: `because ${r}`, problems: [], ...over });

  it('shows the detected role of each released file and enables "Create RFQ from these files" for a BOM workbook', async () => {
    const onCreateRfq = vi.fn();
    const onClose = vi.fn();
    scanFiles.mockResolvedValue({ rfq_id: 'RFQ-00001', engines, results: [role('Centum_Scrub_BOM.xlsx', 'scrub_bom', 'BOM workbook (SCRUB BOM)'), role('Volume_File.xlsx', 'volume', 'Volume file')] } satisfies ScanResponse);
    open([file('Centum_Scrub_BOM.xlsx'), file('Volume_File.xlsx')], { onCreateRfq, onClose });
    fireEvent.click(screen.getByRole('button', { name: 'Scan 2 files' }));
    expect(await screen.findByText('Detected: BOM workbook (SCRUB BOM)')).toBeTruthy();
    expect(screen.getByText('Detected: Volume file')).toBeTruthy();
    expect(screen.getByTestId('intake-readiness').textContent).toContain('Centum_Scrub_BOM.xlsx is the BOM workbook and Volume_File.xlsx the volume file');
    fireEvent.click(screen.getByRole('button', { name: 'Create RFQ from these files' }));
    expect(onCreateRfq).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });

  it('a BOM without a SCRUB BOM sheet is flagged with the reason and offers no Create button', async () => {
    const problem = "No sheet named SCRUB BOM (sheets: BOM). The first pipeline step would reject this file as invalid input; use the Scrub BOM workbook.";
    scanFiles.mockResolvedValue({ rfq_id: 'RFQ-00001', engines, results: [role('Centum_BOM.xlsx', 'bom', 'BOM without a SCRUB BOM sheet', { problems: [problem] })] } satisfies ScanResponse);
    open([file('Centum_BOM.xlsx')], { onCreateRfq: () => {} });
    fireEvent.click(screen.getByRole('button', { name: 'Scan 1 file' }));
    expect(await screen.findByText('Detected: BOM without a SCRUB BOM sheet')).toBeTruthy();
    expect(screen.getByText(problem)).toBeTruthy();
    expect(screen.getByTestId('intake-readiness').textContent).toContain('cannot start the pipeline');
    expect(screen.queryByRole('button', { name: 'Create RFQ from these files' })).toBeNull();
  });

  it('shows no role line for a file that was not released', async () => {
    scanFiles.mockResolvedValue({ rfq_id: 'RFQ-00001', engines, results: [result('eicar.txt', { clamav: { verdict: 'threat' }, decision: 'quarantined', attachment_id: null })] } satisfies ScanResponse);
    open([file('eicar.txt')], { onCreateRfq: () => {} });
    fireEvent.click(screen.getByRole('button', { name: 'Scan 1 file' }));
    await screen.findByText('Scan complete');
    expect(screen.queryByText(/Detected:/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create RFQ from these files' })).toBeNull();
  });
});
