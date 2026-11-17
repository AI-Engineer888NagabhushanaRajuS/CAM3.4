import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { DownloadSimple, X } from '@phosphor-icons/react';
import { ReportsDashboard } from './ReportsDashboard';
import { SupersetDashboardPanel } from './SupersetDashboardPanel';
import { WorkbookEditor } from '@/components/rfq/WorkbookEditor';
import { ChangesPanel } from '@/components/rfq/ChangesPanel';
import { saveFromUrl } from '@/lib/autoDownload';

/**
 * The Output of a finished run, in full screen: the reports and charts, the Superset view, the human review of the workbook
 * (the Excel-like editor), the changes and versions, and every download. Opened from the Output button; Escape or Close returns
 * to the workflow view, which keeps the run's history.
 */

export interface OutputDownload {
  label: string;
  filename: string;
  url: string;
}

type Tab = 'dashboard' | 'superset' | 'review' | 'downloads';
const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'dashboard', label: 'Reports & charts' },
  { id: 'superset', label: 'Superset' },
  { id: 'review', label: 'Review the workbook' },
  { id: 'downloads', label: 'Downloads' },
];

export function OutputPage({
  rfqId,
  workbook,
  downloads,
  onClose,
  onOpenRfq,
}: {
  rfqId: string;
  workbook: string | null;
  downloads: OutputDownload[];
  onClose: () => void;
  onOpenRfq: (rfqId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>('dashboard');
  const [reviewFile, setReviewFile] = useState<File | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !reviewFile) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, reviewFile]);

  // The review opens the CBOM workbook itself, so the person edits the file the run produced.
  const openReview = async () => {
    const cbom = downloads.find((d) => d.label === 'CBOM workbook');
    if (!cbom) {
      setReviewError('There is no CBOM workbook to review yet.');
      return;
    }
    setReviewLoading(true);
    setReviewError(null);
    try {
      const res = await fetch(cbom.url);
      if (!res.ok) throw new Error(`the workbook could not be read (status ${res.status})`);
      const blob = await res.blob();
      setReviewFile(new File([blob], cbom.filename, { type: blob.type }));
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : 'the workbook could not be read');
    } finally {
      setReviewLoading(false);
    }
  };

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`Output for ${rfqId}`} data-testid="output-page" className="fixed inset-0 z-[90] flex flex-col bg-background">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">Output · {rfqId}</h2>
          {workbook && <p className="truncate font-mono text-xs text-muted-foreground">{workbook}</p>}
        </div>
        <div className="flex items-center gap-3">
          <nav aria-label="Output sections" className="inline-flex rounded-md border border-border p-0.5 text-xs">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                aria-current={tab === t.id ? 'page' : undefined}
                onClick={() => setTab(t.id)}
                className={`rounded px-3 py-1.5 font-medium transition ${tab === t.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <button type="button" onClick={onClose} aria-label="Close the output" className="rounded-md border border-border p-1.5 text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === 'dashboard' && <ReportsDashboard rfqId={rfqId} ready onOpenRfq={onOpenRfq} />}

        {tab === 'superset' && (
          <div className="p-6">
            <div className="h-[calc(100vh-9rem)] min-h-[420px] overflow-hidden rounded-xl border border-border bg-card">
              <SupersetDashboardPanel rfqId={rfqId} />
            </div>
          </div>
        )}

        {tab === 'review' && (
          <div className="mx-auto flex max-w-3xl flex-col gap-6 p-6">
            <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
              <h3 className="text-sm font-semibold text-foreground">Human review of the workbook</h3>
              <p className="text-xs text-muted-foreground">
                Open the CBOM workbook in the editor, check the flagged cells, and change what is wrong. A saved change makes a new version;
                the previous one stays downloadable.
              </p>
              <div>
                <button
                  type="button"
                  onClick={() => void openReview()}
                  disabled={reviewLoading}
                  className="rounded-md bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  {reviewLoading ? 'Opening the workbook…' : 'Open the workbook for review'}
                </button>
              </div>
              {reviewError && <p role="alert" className="text-xs text-destructive">{reviewError}</p>}
            </section>
            <section className="rounded-xl border border-border bg-card p-5">
              <h3 className="mb-2 text-sm font-semibold text-foreground">Changes and versions</h3>
              <ChangesPanel rfqId={rfqId} />
            </section>
          </div>
        )}

        {tab === 'downloads' && (
          <div className="mx-auto flex max-w-3xl flex-col gap-3 p-6">
            {downloads.length === 0 && <p className="text-xs text-muted-foreground">Nothing has been exported for this RFQ yet.</p>}
            <ul className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
              {downloads.map((d) => (
                <li key={d.label} className="flex items-center gap-4 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">{d.label}</p>
                    <p className="truncate font-mono text-xs text-muted-foreground">{d.filename}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => saveFromUrl(d.url)}
                    className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs font-semibold text-background hover:opacity-90"
                  >
                    <DownloadSimple className="h-3.5 w-3.5" weight="bold" /> Download
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {reviewFile && (
        <WorkbookEditor
          open
          rfqId={rfqId}
          file={reviewFile}
          name={reviewFile.name}
          onClose={() => setReviewFile(null)}
          onFileChange={(f) => setReviewFile(f)}
        />
      )}
    </div>,
    document.body,
  );
}
