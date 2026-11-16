import { useState, type DragEvent } from 'react';
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

  const missingRequired = BUCKETS.filter((b) => b.required && !files[b.key]);
  const set = (key: BucketKey) => (f: File) => setFiles((prev) => ({ ...prev, [key]: f }));
  const clear = (key: BucketKey) => () => setFiles((prev) => {
    const next = { ...prev };
    delete next[key];
    return next;
  });

  // The BOM upload is synchronous on the server: it creates the RFQ's version and returns it. The QuoteWin and costing sheet are then
  // saved to that same version, so the run has every input it needs before it starts. Nothing is asked for again during the run.
  const handleUpload = async () => {
    if (busy) { return; }
    if (missingRequired.length) {
      setError(`Add the ${missingRequired.map((b) => b.label).join(' and ')} first.`);
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
      if (!res.ok) { throw new Error(await refusalMessage(res)); }

      const extra: { url: string; file: File; label: string }[] = [];
      if (files.quotewin) { extra.push({ url: '/api/rfq/upload/quotewin', file: files.quotewin, label: 'QuoteWin export' }); }
      if (files.costing) { extra.push({ url: '/api/rfq/upload/costing_sheet', file: files.costing, label: 'Costing sheet' }); }
      for (const item of extra) {
        const body = new FormData();
        body.append(item.url.endsWith('quotewin') ? 'quotewin_file' : 'costing_sheet_file', item.file);
        body.append('rfq_id', rfq);
        const r = await authFetch(`${RFQ_UPLOAD_URL}${item.url}`, rfq, { method: 'POST', body });
        if (!r.ok) { throw new Error(`${item.label}: ${await refusalMessage(r)}`); }
      }
      setFiles({});
      onSuccess(bom.name);
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
    setFiles({});
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
          <Button onClick={() => void handleUpload()} disabled={busy || missingRequired.length > 0} size="sm">
            {busy ? 'Uploading…' : 'Upload & Proceed'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
