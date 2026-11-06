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

interface RfqIntakeUploadModalProps {
  open: boolean;
  rfqId: string;
  onClose: () => void;
  onSuccess: (fileName: string) => void;
  onUploadStart?: (fileName: string) => void;
  onUploadError?: (message: string) => void;
}

export function RfqIntakeUploadModal({
  open,
  rfqId,
  onClose,
  onSuccess,
  onUploadStart,
  onUploadError,
}: RfqIntakeUploadModalProps) {
  const [bomFile, setBomFile] = useState<File | null>(null);
  const [bomDragOver, setBomDragOver] = useState(false);
  const [volumeFile, setVolumeFile] = useState<File | null>(null);
  const [volumeDragOver, setVolumeDragOver] = useState(false);
  // Optional -- RFQ_Flow's gerber_integration__extract_features skips itself
  // gracefully (hitl=0, no preview) when no GERBER_ZIP file_role row exists
  // for the rfq_id, same as this platform's other optional inputs.
  const [gerberFile, setGerberFile] = useState<File | null>(null);
  const [gerberDragOver, setGerberDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bomInputRef = useRef<HTMLInputElement>(null);
  const volumeInputRef = useRef<HTMLInputElement>(null);
  const gerberInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const makeDrop = (setter: (f: File | null) => void, setDrag: (v: boolean) => void) =>
    (e: React.DragEvent) => {
      e.preventDefault();
      setDrag(false);
      const file = e.dataTransfer.files?.[0];
      if (file) { setter(file); }
    };

  const handleUpload = () => {
    if (!bomFile || !volumeFile) { return; }
    if (!rfqId.trim()) {
      setError('Please enter a Target RFQ Reference ID before uploading.');
      return;
    }

    const fileName = bomFile.name;
    onUploadStart?.(fileName);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const formData = new FormData();
    formData.append('bom_file', bomFile);
    formData.append('volume_file', volumeFile);
    formData.append('rfq_id', rfqId.trim());
    if (gerberFile) { formData.append('gerber_file', gerberFile); }

    const RFQ_UPLOAD = RFQ_UPLOAD_URL;
    authFetch(`${RFQ_UPLOAD}/api/rfq/upload`, rfqId.trim(), {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          logger.error('BOM upload rejected by server', { status: response.status });
          // SPEC-023: the pre-flight names the cells that would be NaN / error in the output; say which, and where to fix them.
          const body = (await response.json().catch(() => null)) as { detail?: { code?: string; message?: string; issues?: Array<{ sheet: string | null; col: string | null; row: number | null; message: string }> } } | null;
          const d = body?.detail;
          onUploadError?.(d?.code === 'input_invalid'
            ? `${d.message} First: ${(d.issues ?? []).slice(0, 3).map((i) => `${i.sheet ?? ''} ${i.col ?? ''}${i.row ?? ''}: ${i.message}`).join(' ')} Attach the file with the paperclip in the assistant to fix these cells there.`
            : `Server rejected the BOM upload (status ${response.status}).`);
        }
      })
      .catch((err) => {
        if (err instanceof Error && err.name === 'AbortError') { return; }
        const message = err instanceof Error ? err.message : String(err);
        logger.error('BOM upload request failed', { error: message });
        onUploadError?.(message);
      });

    // The upload hand-off (not the full backend workflow) is what this modal
    // gates on — the live SSE progress panel takes over from here, so the
    // modal closes as soon as the request is dispatched.
    setBomFile(null);
    setVolumeFile(null);
    setGerberFile(null);
    setError(null);
    onSuccess(fileName);
  };

  const handleClose = () => {
    abortControllerRef.current?.abort();
    setBomFile(null);
    setVolumeFile(null);
    setGerberFile(null);
    setError(null);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { handleClose(); } }}>
      <DialogContent className="max-w-md border-border bg-card">
        <DialogHeader>
          <DialogTitle className="text-foreground">Upload RFQ Files</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            BOM & volume files for RFQ{' '}
            <span className="font-mono text-primary">{rfqId || '—'}</span>
          </p>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* BOM File Zone */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">BOM File</p>
            <div
              onDragOver={(e) => { e.preventDefault(); setBomDragOver(true); }}
              onDragLeave={() => setBomDragOver(false)}
              onDrop={makeDrop(setBomFile, setBomDragOver)}
              onClick={() => { if (!bomFile) { bomInputRef.current?.click(); } }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-5 text-center transition-colors ${
                bomDragOver
                  ? 'border-primary bg-primary/5'
                  : bomFile
                    ? 'border-primary/50 bg-primary/5'
                    : 'border-border hover:border-muted-foreground'
              }`}
            >
              {bomFile ? (
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 flex-shrink-0 text-primary" />
                  <span className="max-w-[200px] truncate text-sm text-foreground">{bomFile.name}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setBomFile(null); }}
                    className="ml-1 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <p className="mb-1.5 text-xs text-muted-foreground">Drop file here or</p>
                  <span className="text-sm font-medium text-primary">Browse files</span>
                  <p className="mt-1 text-[10px] text-muted-foreground/70">.xlsx · .xls · .csv</p>
                </>
              )}
            </div>
            <input
              ref={bomInputRef}
              type="file"
              className="hidden"
              accept=".xlsx,.xls,.csv"
              onChange={(e) => { if (e.target.files?.[0]) { setBomFile(e.target.files[0]); } }}
            />
          </div>

          {/* Volume File Zone -- mandatory; RFQ_Flow's intake__import_bom
              requires a file_role='VOLUME' row in rfq_file_telemetry
              alongside the BOM row, with no graceful-skip. */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Volume File</p>
            <div
              onDragOver={(e) => { e.preventDefault(); setVolumeDragOver(true); }}
              onDragLeave={() => setVolumeDragOver(false)}
              onDrop={makeDrop(setVolumeFile, setVolumeDragOver)}
              onClick={() => { if (!volumeFile) { volumeInputRef.current?.click(); } }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-5 text-center transition-colors ${
                volumeDragOver
                  ? 'border-primary bg-primary/5'
                  : volumeFile
                    ? 'border-primary/50 bg-primary/5'
                    : 'border-border hover:border-muted-foreground'
              }`}
            >
              {volumeFile ? (
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 flex-shrink-0 text-primary" />
                  <span className="max-w-[200px] truncate text-sm text-foreground">{volumeFile.name}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setVolumeFile(null); }}
                    className="ml-1 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <p className="mb-1.5 text-xs text-muted-foreground">Drop file here or</p>
                  <span className="text-sm font-medium text-primary">Browse files</span>
                  <p className="mt-1 text-[10px] text-muted-foreground/70">.xlsx · .xls · .csv</p>
                </>
              )}
            </div>
            <input
              ref={volumeInputRef}
              type="file"
              className="hidden"
              accept=".xlsx,.xls,.csv"
              onChange={(e) => { if (e.target.files?.[0]) { setVolumeFile(e.target.files[0]); } }}
            />
          </div>

          {/* Gerber ZIP Zone -- optional. Skipped gracefully downstream if
              omitted; see gerber_integration__extract_features. */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Gerber ZIP <span className="text-muted-foreground/60">(optional)</span>
            </p>
            <div
              onDragOver={(e) => { e.preventDefault(); setGerberDragOver(true); }}
              onDragLeave={() => setGerberDragOver(false)}
              onDrop={makeDrop(setGerberFile, setGerberDragOver)}
              onClick={() => { if (!gerberFile) { gerberInputRef.current?.click(); } }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-5 text-center transition-colors ${
                gerberDragOver
                  ? 'border-primary bg-primary/5'
                  : gerberFile
                    ? 'border-primary/50 bg-primary/5'
                    : 'border-border hover:border-muted-foreground'
              }`}
            >
              {gerberFile ? (
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 flex-shrink-0 text-primary" />
                  <span className="max-w-[200px] truncate text-sm text-foreground">{gerberFile.name}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setGerberFile(null); }}
                    className="ml-1 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <>
                  <p className="mb-1.5 text-xs text-muted-foreground">Drop file here or</p>
                  <span className="text-sm font-medium text-primary">Browse files</span>
                  <p className="mt-1 text-[10px] text-muted-foreground/70">.zip</p>
                </>
              )}
            </div>
            <input
              ref={gerberInputRef}
              type="file"
              className="hidden"
              accept=".zip"
              onChange={(e) => { if (e.target.files?.[0]) { setGerberFile(e.target.files[0]); } }}
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
            onClick={handleUpload}
            disabled={!bomFile || !volumeFile}
            size="sm"
          >
            Upload & Proceed
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
