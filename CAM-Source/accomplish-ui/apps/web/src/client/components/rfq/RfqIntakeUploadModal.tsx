import { useEffect, useRef, useState, type DragEvent } from 'react';
import { saveBlob, type FillInIssue } from '@/lib/bomFillIn';
import { WorkbookEditor } from './WorkbookEditor';
import type { CheckIssue } from '@/lib/inputFix';
import { listStaged, stageInput, unstageInput, type StagedRole } from '@/lib/intakeInputs';
import { FileText, WarningCircle, X } from '@phosphor-icons/react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { logger } from '@/lib/logger';
import { RFQ_UPLOAD_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { refusalMessage } from '@/lib/uploadRefusal';

interface RfqIntakeUploadModalProps {
  open: boolean;
  rfqId: string;
  onClose: () => void;
  onSuccess: (fileName: string) => void;
  onUploadStart?: (fileName: string) => void;
  onUploadError?: (message: string) => void;
}

type BucketKey = 'bom' | 'volume' | 'quotewin' | 'costing' | 'gerber';

interface Bucket {
  key: BucketKey;
  label: string;
  hint: string;
  accept: string;
  /** Required buckets are red until filled; the run cannot start without them. Optional buckets stay grey. */
  required: boolean;
  why: string;
}

// The buckets follow the upload service's own rules: BOM and QuoteWin are needed to cost the RFQ; the volume file is optional for the
// default scrub pipeline (its volumes are in the workbook's Settings sheet); the costing sheet and the Gerber ZIP are optional extras.
const BUCKETS: Bucket[] = [
  { key: 'bom', label: 'BOM file', hint: '.xlsx · .xls · .csv', accept: '.xlsx,.xls,.csv', required: true, why: 'The customer BOM. The run cannot start without it.' },
  { key: 'quotewin', label: 'QuoteWin export', hint: '.xlsx · .xls · .csv', accept: '.xlsx,.xls,.csv', required: true, why: 'Prices the parts. Needed before costing; it is not asked for again during the run.' },
  { key: 'volume', label: 'Volume file', hint: '.xlsx · .xls · .csv', accept: '.xlsx,.xls,.csv', required: false, why: 'Volumes. Optional: the default pipeline reads them from the BOM workbook.' },
  { key: 'costing', label: 'Costing sheet', hint: '.xlsx · .xls · .csv', accept: '.xlsx,.xls,.csv', required: false, why: 'Optional extra costing input, sent with the QuoteWin export.' },
  { key: 'gerber', label: 'Gerber ZIP', hint: '.zip', accept: '.zip', required: false, why: 'Optional. Without it the feature extraction is skipped.' },
];

/** The cells a pre-flight refusal names (422 input_invalid), or null for any other refusal. Reads a copy, so the caller can still read the body. */
async function fillInListOf(res: Response): Promise<{ issues: FillInIssue[]; errors: number; message: string } | null> {
  const body = (await res.clone().json().catch(() => null)) as { detail?: { code?: string; message?: string; errors?: number; issues?: FillInIssue[] } } | null;
  const d = body?.detail;
  if (!d || typeof d !== 'object' || d.code !== 'input_invalid') { return null; }
  return { issues: d.issues ?? [], errors: d.errors ?? (d.issues ?? []).length, message: d.message ?? 'The BOM needs fixing.' };
}

function DropBucket({ bucket, file, onFile, onClear }: { bucket: Bucket; file: File | null; onFile: (f: File) => void; onClear: () => void }) {
  const [over, setOver] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const missing = bucket.required && !file;
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };
  const border = over
    ? 'border-primary bg-primary/5'
    : file
      ? 'border-emerald-500/60 bg-emerald-500/5'
      : missing
        ? 'border-destructive/70 bg-destructive/5'
        : 'border-dashed border-border bg-muted/30';
  return (
    <div className="space-y-1.5" data-testid={`bucket-${bucket.key}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-foreground">{bucket.label}</p>
        {bucket.required ? (
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${file ? 'bg-emerald-500/15 text-emerald-700' : 'bg-destructive/15 text-destructive'}`}>
            {file ? 'Ready' : 'Required'}
          </span>
        ) : (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Optional</span>
        )}
      </div>
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={`flex min-h-[92px] flex-col items-center justify-center rounded-lg border-2 px-3 py-3 text-center transition-colors ${border} ${bucket.required || file ? '' : 'opacity-80'}`}
      >
        {file ? (
          <div className="flex max-w-full items-center gap-2">
            <FileText className="h-4 w-4 shrink-0 text-emerald-600" />
            <span className="min-w-0 truncate text-sm text-foreground" title={file.name}>{file.name}</span>
            <button type="button" aria-label={`Remove ${bucket.label}`} onClick={onClear} className="shrink-0 text-muted-foreground hover:text-foreground">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">Drop the file here</p>
            <label className="mt-1 cursor-pointer text-sm font-medium text-primary hover:underline">
              or browse
              <input
                key={inputKey}
                type="file"
                className="sr-only"
                accept={bucket.accept}
                aria-label={`Choose ${bucket.label}`}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) { onFile(f); } setInputKey((k) => k + 1); }}
              />
            </label>
            <p className="mt-1 text-[10px] text-muted-foreground/80">{bucket.hint}</p>
          </>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground">{bucket.why}</p>
    </div>
  );
}

export function RfqIntakeUploadModal({
  open,
  rfqId,
  onClose,
  onSuccess,
  onUploadStart,
  onUploadError,
}: RfqIntakeUploadModalProps) {
  const [files, setFiles] = useState<Partial<Record<BucketKey, File>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The BOM the server refused (pre-flight, 422 input_invalid): its flagged cells, until a fixed BOM is dropped in.
  const [fixList, setFixList] = useState<{ issues: FillInIssue[]; errors: number; message: string } | null>(null);
  const fixSent = useRef(false);
  const [editorOpen, setEditorOpen] = useState(false);

  // The QuoteWin and costing sheet are kept on the server as soon as they are dropped, so the buckets show what the RFQ already holds
  // when the dialog opens (after a reload too). The BOM, volume and Gerber files are sent with the BOM upload.
  useEffect(() => {
    if (!open || !rfqId.trim()) { return; }
    let alive = true;
    void listStaged(rfqId).then((staged) => {
      if (!alive) { return; }
      const next: Partial<Record<BucketKey, File>> = {};
      if (staged.quotewin) { next.quotewin = new File([], staged.quotewin.file_name); }
      if (staged.costing) { next.costing = new File([], staged.costing.file_name); }
      setFiles(next);
    });
    return () => { alive = false; };
  }, [open, rfqId]);

  const missingRequired = BUCKETS.filter((b) => b.required && !files[b.key]);
  const bomName = files.bom?.name ?? '';
  const isServerKept = (key: BucketKey): key is StagedRole => key === 'quotewin' || key === 'costing';
  const forget = (key: BucketKey) => setFiles((prev) => {
    const next = { ...prev };
    delete next[key];
    return next;
  });
  const set = (key: BucketKey) => (f: File) => {
    if (key === 'bom') { setFixList(null); }
    if (isServerKept(key)) {
      setError(null);
      stageInput(rfqId, key, f)
        .then(() => setFiles((prev) => ({ ...prev, [key]: f })))
        .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
      return;
    }
    setFiles((prev) => ({ ...prev, [key]: f }));
  };
  const clear = (key: BucketKey) => () => {
    if (key === 'bom') { setFixList(null); }
    if (isServerKept(key)) {
      unstageInput(rfqId, key)
        .then(() => forget(key))
        .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
      return;
    }
    forget(key);
  };


  // The BOM upload is synchronous on the server: it creates the RFQ's version and returns it. QuoteWin and the costing sheet are not
  // sent here: they are remembered in their buckets and the run takes them at its QuoteWin step, so nothing is asked for again.
  const handleUpload = async (proceedWithMissing = false) => {
    if (busy) { return; }
    // "Proceed with missing values" lifts only the non-BOM requirements: the BOM is still the run's input.
    const blocking = proceedWithMissing ? missingRequired.filter((b) => b.key === 'bom') : missingRequired;
    if (blocking.length) {
      setError(`Add the ${blocking.map((b) => b.label).join(' and ')} first.`);
      return;
    }
    const rfq = rfqId.trim();
    if (!rfq) {
      setError('Please enter a Target RFQ Reference ID before uploading.');
      return;
    }
    const bom = files.bom!;
    setBusy(true);
    setError(null);
    onUploadStart?.(bom.name);
    try {
      const form = new FormData();
      form.append('bom_file', bom);
      if (files.volume) { form.append('volume_file', files.volume); }
      if (files.gerber) { form.append('gerber_file', files.gerber); }
      form.append('rfq_id', rfq);
      const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/upload`, rfq, { method: 'POST', body: form });
      if (!res.ok) {
        // The pre-flight named the cells to fill in: show them and keep the dialog open, instead of a one-line refusal.
        const cells = await fillInListOf(res);
        if (cells) {
          fixSent.current = true;
          setFixList(cells);
          return;
        }
        throw new Error(await refusalMessage(res));
      }

      // The server attached any kept QuoteWin / costing sheet to the new BOM version. One it refused is not in the run: say why, in the
      // intake panel, instead of letting the run ask for it again without a reason.
      let refusalNote: string | null = null;
      const uploaded = (await res.clone().json().catch(() => null)) as { staged_inputs?: Record<string, { attached: boolean; file_name?: string; reason?: unknown }> } | null;
      const refused = Object.entries(uploaded?.staged_inputs ?? {}).filter(([, v]) => !v.attached);
      if (refused.length) {
        const why = refused.map(([role, v]) => {
          const reason = typeof v.reason === 'string' ? v.reason : (v.reason as { message?: string } | undefined)?.message ?? 'refused';
          return `${role === 'quotewin' ? 'QuoteWin' : 'Costing sheet'} ${v.file_name ?? ''} was not attached: ${reason}`;
        }).join(' ');
        refusalNote = `${why} Drop a correct file in its bucket; the run will ask for it.`;
      }
      // The BOM upload halts the run at the QuoteWin step while that file is missing. Proceeding with missing values resumes it now,
      // the same resume the QuoteWin prompt uses; the report then says on its Run Inputs tab what was missing.
      if (proceedWithMissing && missingRequired.length) {
        const resumed = await authFetch(`${RFQ_UPLOAD_URL}/api/dify/start/${encodeURIComponent(rfq)}`, rfq);
        if (!resumed.ok) { throw new Error(`The run could not continue without ${missingRequired.map((b) => b.label).join(', ')} (status ${resumed.status}).`); }
      }
      // A BOM that came back fixed from the fill-in is saved to the computer as it goes on to processing, as the user asked.
      if (fixSent.current) {
        fixSent.current = false;
        saveBlob(bom, bom.name);
      }
      // The files stay remembered in their buckets: the run takes the QuoteWin and costing sheet from there when it reaches that step.
      setFixList(null);
      onSuccess(bom.name);
      // Reported after onSuccess, which sets the panel to "processing": the reason must stay on screen.
      if (refusalNote) { onUploadError?.(refusalNote); }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      logger.error('Intake upload failed', { error: message });
      setError(message);
      onUploadError?.(message);
    } finally {
      setBusy(false);
    }
  };

  const handleClose = () => {
    if (busy) { return; }
    setError(null);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { handleClose(); } }}>
      <DialogContent className="max-w-3xl border-border bg-card">
        <DialogHeader>
          <DialogTitle className="text-foreground">Input files for this RFQ</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            RFQ <span className="font-mono text-primary">{rfqId || '—'}</span>. Drop each file in its own bucket. The red ones are required; the grey ones are optional.
          </p>
        </DialogHeader>

        <div className="grid grid-cols-1 gap-4 py-2 sm:grid-cols-2 xl:grid-cols-3">
          {BUCKETS.map((b) => (
            <DropBucket key={b.key} bucket={b} file={files[b.key] ?? null} onFile={set(b.key)} onClear={clear(b.key)} />
          ))}
        </div>

        {fixList && (
          <section role="alert" aria-label="Cells to fill in" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
            <p className="text-sm font-semibold text-foreground">
              The BOM needs {fixList.errors} cell{fixList.errors === 1 ? '' : 's'} filled in before processing. Open the whole workbook to fill them in, or force the run.
            </p>
            <Button size="sm" onClick={() => setEditorOpen(true)} data-testid="open-workbook">Open the workbook</Button>
          </section>
        )}

        {missingRequired.length > 0 && !error && (
          <p className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive" role="status">
            <WarningCircle className="h-4 w-4 shrink-0" weight="fill" />
            Still required: {missingRequired.map((b) => b.label).join(', ')}.
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        )}

        <DialogFooter className="gap-2">
          <button type="button" onClick={handleClose} disabled={busy} className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50">
            Cancel
          </button>
          {missingRequired.length > 0 && (
            <Button
              variant="outline"
              onClick={() => void handleUpload(true)}
              disabled={busy || !files.bom}
              size="sm"
              title="Runs without the missing required input. The report says so on its Run Inputs tab and is not marked release-ready."
            >
              Proceed with missing values
            </Button>
          )}
          <Button onClick={() => void handleUpload()} disabled={busy || missingRequired.length > 0} size="sm">
            {busy ? 'Uploading…' : 'Upload & Proceed'}
          </Button>
        </DialogFooter>
      </DialogContent>
      {editorOpen && files.bom && (
        <WorkbookEditor
          open
          rfqId={rfqId}
          file={files.bom}
          name={files.bom.name}
          report={fixList ? { checked: true, ok: false, errors: fixList.errors, warnings: 0, rows: 0, issues: fixList.issues as CheckIssue[], truncated: false } : undefined}
          onClose={() => setEditorOpen(false)}
          onFileChange={(f) => { setEditorOpen(false); set('bom')(f); }}
          onForced={() => {
            setEditorOpen(false);
            setFixList(null);
            onSuccess(bomName);
          }}
        />
      )}
    </Dialog>
  );
}
