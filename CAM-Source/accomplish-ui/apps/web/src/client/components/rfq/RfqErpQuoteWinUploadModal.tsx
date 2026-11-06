import { useRef, useState } from 'react';
import { FileText, X } from '@phosphor-icons/react';
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

interface UploadedFileNames {
  quoteWinFileName?: string;
  costingSheetFileName?: string;
}

interface RfqErpQuoteWinUploadModalProps {
  open: boolean;
  rfqId: string;
  onClose: () => void;
  onSuccess: (files: UploadedFileNames) => void;
  onUploadStart?: (files: UploadedFileNames) => void;
  onUploadError?: (message: string) => void;
}

export function RfqErpQuoteWinUploadModal({
  open,
  rfqId,
  onClose,
  onSuccess,
  onUploadStart,
  onUploadError,
}: RfqErpQuoteWinUploadModalProps) {
  const [costingSheetFile, setCostingSheetFile] = useState<File | null>(null);
  const [quoteWinFile, setQuoteWinFile] = useState<File | null>(null);
  const [costingSheetDragOver, setCostingSheetDragOver] = useState(false);
  const [quoteWinDragOver, setQuoteWinDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  const costingSheetInputRef = useRef<HTMLInputElement>(null);
  const quoteWinInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const makeDrop = (setter: (f: File | null) => void, setDrag: (v: boolean) => void) =>
    (e: React.DragEvent) => {
      e.preventDefault();
      setDrag(false);
      const file = e.dataTransfer.files?.[0];
      if (file) { setter(file); }
    };

  const handleUpload = async () => {
    if (!quoteWinFile) {
      setError('QuoteWin file is required — upload it alone or together with a Costing Sheet.');
      return;
    }
    if (!rfqId.trim()) {
      setError('Please enter a Target RFQ Reference ID before uploading.');
      return;
    }

    const trimmedRfqId = rfqId.trim();
    const fileNames: UploadedFileNames = {
      ...(quoteWinFile ? { quoteWinFileName: quoteWinFile.name } : {}),
      ...(costingSheetFile ? { costingSheetFileName: costingSheetFile.name } : {}),
    };
    onUploadStart?.(fileNames);

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setIsUploading(true);
    setError(null);

    const RFQ_UPLOAD = RFQ_UPLOAD_URL;

    // Two separate backend endpoints — /api/rfq/upload/costing_sheet and
    // /api/rfq/upload/quotewin each take only their own file field. Only
    // build the requests for whichever file(s) were actually selected --
    // both are optional, at least one is required (guard above).
    const uploads: { label: string; request: Promise<Response> }[] = [];
    if (costingSheetFile) {
      const formData = new FormData();
      formData.append('costing_sheet_file', costingSheetFile);
      formData.append('rfq_id', trimmedRfqId);
      uploads.push({
        label: 'costing sheet',
        request: authFetch(`${RFQ_UPLOAD}/api/rfq/upload/costing_sheet`, trimmedRfqId, {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        }),
      });
    }
    if (quoteWinFile) {
      const formData = new FormData();
      formData.append('quotewin_file', quoteWinFile);
      formData.append('rfq_id', trimmedRfqId);
      uploads.push({
        label: 'quotewin',
        request: authFetch(`${RFQ_UPLOAD}/api/rfq/upload/quotewin`, trimmedRfqId, {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        }),
      });
    }

    try {
      const responses = await Promise.all(uploads.map((u) => u.request));
      const failed = responses
        .map((res, i) => ({ res, label: uploads[i].label }))
        .filter(({ res }) => !res.ok);
      if (failed.length > 0) {
        throw new Error(
          `Upload rejected by server (${failed.map(({ res, label }) => `${label}: ${res.status}`).join(', ')})`,
        );
      }

      setCostingSheetFile(null);
      setQuoteWinFile(null);
      setError(null);
      // Close immediately — resuming the paused pipeline can block for a
      // long time (the whole Dify run has to finish), and there's no reason
      // to keep the dialog open for that. RfqIntakeProgressPanel (right
      // panel) already knows how to show "uploaded — resuming…" while this
      // finishes in the background, then "Resumed" once the real
      // rfq:skill-progress SSE event confirms the pipeline actually moved on.
      onSuccess(fileNames);

      authFetch(`${RFQ_UPLOAD}/api/dify/start/${encodeURIComponent(trimmedRfqId)}`, trimmedRfqId)
        .then((resumeResponse) => {
          if (!resumeResponse.ok) {
            throw new Error(`Failed to resume pipeline (status ${resumeResponse.status})`);
          }
        })
        .catch((err) => {
          const message = err instanceof Error ? err.message : String(err);
          logger.error('Pipeline resume failed after Costing Sheet/QuoteWin upload', { error: message });
          onUploadError?.(message);
        });
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') { return; }
      const message = err instanceof Error ? err.message : String(err);
      logger.error('Costing Sheet/QuoteWin upload failed', { error: message });
      setError(message);
      onUploadError?.(message);
    } finally {
      setIsUploading(false);
    }
  };

  const handleClose = () => {
    abortControllerRef.current?.abort();
    setCostingSheetFile(null);
    setQuoteWinFile(null);
    setError(null);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { handleClose(); } }}>
      <DialogContent className="max-w-md border-border bg-card">
        <DialogHeader>
          <DialogTitle className="text-foreground">Upload QuoteWin & Costing Sheet Files</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            QuoteWin and Costing Sheet files for RFQ{' '}
            <span className="font-mono text-primary">{rfqId || '—'}</span>
          </p>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* QuoteWin File Zone */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">QuoteWin File (required)</p>
            <div
              onDragOver={(e) => { e.preventDefault(); setQuoteWinDragOver(true); }}
              onDragLeave={() => setQuoteWinDragOver(false)}
              onDrop={makeDrop(setQuoteWinFile, setQuoteWinDragOver)}
              onClick={() => { if (!quoteWinFile) { quoteWinInputRef.current?.click(); } }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-5 text-center transition-colors ${
                quoteWinDragOver
                  ? 'border-primary bg-primary/5'
                  : quoteWinFile
                    ? 'border-primary/50 bg-primary/5'
                    : 'border-border hover:border-muted-foreground'
              }`}
            >
              {quoteWinFile ? (
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 flex-shrink-0 text-primary" />
                  <span className="max-w-[200px] truncate text-sm text-foreground">{quoteWinFile.name}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setQuoteWinFile(null); }}
                    className="ml-1 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <p className="mb-1.5 text-xs text-muted-foreground">Drop file here or</p>
                  <span className="text-sm font-medium text-primary">Browse files</span>
                  <p className="mt-1 text-[10px] text-muted-foreground/70">.xlsx · .xls</p>
                </>
              )}
            </div>
            <input
              ref={quoteWinInputRef}
              type="file"
              className="hidden"
              accept=".xlsx,.xls"
              onChange={(e) => { if (e.target.files?.[0]) { setQuoteWinFile(e.target.files[0]); } }}
            />
          </div>

          {/* Costing Sheet File Zone */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Costing Sheet File (optional)</p>
            <div
              onDragOver={(e) => { e.preventDefault(); setCostingSheetDragOver(true); }}
              onDragLeave={() => setCostingSheetDragOver(false)}
              onDrop={makeDrop(setCostingSheetFile, setCostingSheetDragOver)}
              onClick={() => { if (!costingSheetFile) { costingSheetInputRef.current?.click(); } }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-5 text-center transition-colors ${
                costingSheetDragOver
                  ? 'border-primary bg-primary/5'
                  : costingSheetFile
                    ? 'border-primary/50 bg-primary/5'
                    : 'border-border hover:border-muted-foreground'
              }`}
            >
              {costingSheetFile ? (
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 flex-shrink-0 text-primary" />
                  <span className="max-w-[200px] truncate text-sm text-foreground">{costingSheetFile.name}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setCostingSheetFile(null); }}
                    className="ml-1 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <p className="mb-1.5 text-xs text-muted-foreground">Drop file here or</p>
                  <span className="text-sm font-medium text-primary">Browse files</span>
                  <p className="mt-1 text-[10px] text-muted-foreground/70">.xlsx · .xls</p>
                </>
              )}
            </div>
            <input
              ref={costingSheetInputRef}
              type="file"
              className="hidden"
              accept=".xlsx,.xls"
              onChange={(e) => { if (e.target.files?.[0]) { setCostingSheetFile(e.target.files[0]); } }}
            />
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
              {error}
            </p>
          )}
        </div>

        <DialogFooter className="gap-2">
          <button
            type="button"
            onClick={handleClose}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
          <Button
            onClick={() => { void handleUpload(); }}
            disabled={!quoteWinFile || isUploading}
            size="sm"
          >
            {isUploading ? 'Uploading…' : 'Upload & Proceed'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
