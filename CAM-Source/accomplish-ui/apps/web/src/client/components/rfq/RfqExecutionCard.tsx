import { useState, useEffect, useCallback, useRef } from 'react';
import { CloudArrowUp, FileArrowDown, FileText, X } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { SearchableSelect, type SelectItem } from '@/components/ui/searchable-select';
import { logger } from '@/lib/logger';
import { getAccomplish } from '@/lib/accomplish';
import { RFQ_UPLOAD_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { refusalMessage } from '@/lib/uploadRefusal';
import { AttachFilesDialog } from './AttachFilesDialog';

interface RfqExecutionCardProps {
  /** Fired the moment `createRfq` resolves, before the file upload request is
   * dispatched -- lets the caller switch the active RFQ context immediately. */
  onCreated: (rfqId: string) => void;
  onUploadStart: (fileName: string) => void;
  /** Fired right after the upload request is dispatched (not once it
   * completes) -- matches RfqIntakeUploadModal's existing hand-off contract,
   * since the live SSE progress panel takes over from here. */
  onUploadSuccess: (fileName: string) => void;
  onUploadError: (message: string) => void;
  onCancel: () => void;
}

interface FileDropSlotProps {
  label: string;
  file: File | null;
  onSelect: (file: File) => void;
  onClear: () => void;
  accept?: string;
  hint?: string;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) { return `${bytes} B`; }
  if (bytes < 1024 * 1024) { return `${(bytes / 1024).toFixed(1)} KB`; }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** One BOM/Volume upload dropzone -- click or drag-and-drop. Once a file is
 * selected it collapses into a chip row (name, size, remove button) instead
 * of staying a dropzone, matching the requested "selected-file chip" pattern. */
function FileDropSlot({ label, file, onSelect, onClear, accept = '.xlsx,.xls,.csv', hint = '.xlsx · .xls · .csv' }: FileDropSlotProps) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-foreground">{label}</label>
      {file ? (
        <div className="flex items-center gap-2.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileText className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
            <p className="text-[11px] text-muted-foreground">{formatFileSize(file.size)}</p>
          </div>
          <button
            type="button"
            onClick={onClear}
            aria-label={`Remove ${label}`}
            className="shrink-0 rounded-md p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const dropped = e.dataTransfer.files?.[0];
            if (dropped) { onSelect(dropped); }
          }}
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors ${
            dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40 hover:bg-muted/30'
          }`}
        >
          <span className={`flex h-9 w-9 items-center justify-center rounded-full transition-colors ${dragOver ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'}`}>
            <CloudArrowUp className="h-[18px] w-[18px]" />
          </span>
          <p className="text-sm text-foreground">
            Drag and drop, or <span className="font-medium text-primary">browse</span>
          </p>
          <p className="text-[11px] text-muted-foreground/80">{hint}</p>
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept={accept}
        onChange={(e) => { if (e.target.files?.[0]) { onSelect(e.target.files[0]); } }}
      />
    </div>
  );
}

/** One drop area for ALL the input files at once (BOM, volume ...). Nothing here decides which file is which: the scan dialog reads them and says. */
function FilesDrop({ onPick, disabled }: { onPick: (files: File[]) => void; disabled: boolean }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-foreground">Input files</label>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onDragOver={(e) => { e.preventDefault(); if (!disabled) { setDragOver(true); } }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (!disabled && e.dataTransfer.files.length) { onPick(Array.from(e.dataTransfer.files)); } }}
        onClick={() => { if (!disabled) { inputRef.current?.click(); } }}
        onKeyDown={(e) => { if (!disabled && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); inputRef.current?.click(); } }}
        className={`flex flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'} ${dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40 hover:bg-muted/30'}`}
      >
        <span className={`flex h-9 w-9 items-center justify-center rounded-full ${dragOver ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'}`}><CloudArrowUp className="h-[18px] w-[18px]" /></span>
        <p className="text-sm text-foreground">Drop all your files here, or <span className="font-medium text-primary">browse</span></p>
        <p className="max-w-sm text-[11px] text-muted-foreground/80">The BOM workbook and the volume file. Both security engines scan them first, and the files are sorted for you. .xlsx · .xls · .csv</p>
      </div>
      <input ref={inputRef} type="file" multiple className="hidden" accept=".xlsx,.xls,.csv" onChange={(e) => { if (e.target.files?.length) { onPick(Array.from(e.target.files)); } e.target.value = ''; }} />
    </div>
  );
}

/** Inline execution card for the "Create RFQ" sub-skill, rendered in place of
 * the chat outlet (Column 2) rather than as a popup dialog. Combines what used
 * to be two separate steps -- RfqCreateForm's metadata form, then
 * RfqIntakeUploadModal's file upload -- into a single card: pick Customer,
 * Project, confirm the RFQ ID, attach BOM + Volume files, submit once. */
export function RfqExecutionCard({
  onCreated,
  onUploadStart,
  onUploadSuccess,
  onUploadError,
  onCancel,
}: RfqExecutionCardProps) {
  const [customers, setCustomers] = useState<SelectItem[]>([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [projects, setProjects] = useState<SelectItem[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [rfqId, setRfqId] = useState('');
  const [rfqIdMessage, setRfqIdMessage] = useState<string | null>(null);
  const [bomFile, setBomFile] = useState<File | null>(null);
  const [volumeFile, setVolumeFile] = useState<File | null>(null);
  // What was just dropped: it goes through the Uppy dashboard and both security engines, which sort the files into BOM and volume.
  const [picked, setPicked] = useState<File[]>([]);
  // Optional -- RFQ_Flow's gerber_integration__extract_features skips itself
  // gracefully (hitl=0, no preview) when no GERBER_ZIP file_role row exists
  // for the rfq_id, same as RfqIntakeUploadModal's own Gerber dropzone.
  const [gerberFile, setGerberFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: fetch on mount
    setCustomersLoading(true);
    Promise.all([
      getAccomplish().listCustomers(),
      getAccomplish().getNextRfqId(),
    ])
      .then(([{ customers: list }, { rfqId: suggested }]) => {
        setCustomers(list.map((c) => ({ id: c.customer_id, name: c.customer_name })));
        setRfqId(suggested);
      })
      .catch((err: unknown) => {
        logger.error('Failed to initialize Create RFQ card:', err);
      })
      .finally(() => setCustomersLoading(false));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: reset on customer change
    if (!customerId) { setProjects([]); setProjectId(null); return; }
    setProjectsLoading(true);
    setProjectId(null);
    getAccomplish().listProjects({ customerId })
      .then(({ projects: list }) => {
        setProjects(list.map((p) => ({ id: p.project_id, name: p.project_name })));
      })
      .catch((err: unknown) => logger.error('Failed to load projects:', err))
      .finally(() => setProjectsLoading(false));
  }, [customerId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: reset on id change
    if (!rfqId.trim()) { setRfqIdMessage(null); return; }
    let cancelled = false;
    getAccomplish().checkRfqExists({ rfqId: rfqId.trim() })
      .then(({ exists }) => {
        if (!cancelled) { setRfqIdMessage(exists ? 'This RFQ ID already exists — choose a different one.' : null); }
      })
      .catch(() => { /* non-fatal — server-side createRfq still enforces uniqueness */ });
    return () => { cancelled = true; };
  }, [rfqId]);

  // The volume file is optional: a SCRUB BOM workbook carries its volumes in its own Settings sheet (the service allows no volume file for it).
  const canSubmit = !!customerId && !!projectId && !!rfqId.trim() && !rfqIdMessage
    && !!bomFile && !submitting;

  const handleStartRfq = useCallback(async () => {
    if (!customerId || !projectId || !bomFile) { return; }
    const trimmedId = rfqId.trim();
    if (!trimmedId || rfqIdMessage) { return; }

    setSubmitting(true);
    setSubmitError(null);
    try {
      await getAccomplish().createRfq({ rfqId: trimmedId, customerId, projectId });
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
      return;
    }

    onCreated(trimmedId);
    onUploadStart(bomFile.name);

    const formData = new FormData();
    formData.append('bom_file', bomFile);
    if (volumeFile) { formData.append('volume_file', volumeFile); }
    formData.append('rfq_id', trimmedId);
    if (gerberFile) { formData.append('gerber_file', gerberFile); }

    authFetch(`${RFQ_UPLOAD_URL}/api/rfq/upload`, trimmedId, { method: 'POST', body: formData })
      .then(async (response) => {
        if (!response.ok) {
          logger.error('BOM upload rejected by server', { status: response.status });
          onUploadError(await refusalMessage(response));
        }
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : String(err);
        logger.error('BOM upload request failed', { error: message });
        onUploadError(message);
      });

    // Same hand-off contract as RfqIntakeUploadModal: the request being
    // dispatched (not completed) is what this card gates on -- the live SSE
    // progress panel takes over immediately after.
    onUploadSuccess(bomFile.name);
    setSubmitting(false);
  }, [customerId, projectId, bomFile, volumeFile, gerberFile, rfqId, rfqIdMessage, onCreated, onUploadStart, onUploadSuccess, onUploadError]);

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-6">
      <div className="relative w-full max-w-2xl rounded-2xl border border-border bg-background p-7 shadow-xl">
        <div className="mb-6 flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileArrowDown className="h-4 w-4" />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-foreground">Create RFQ &amp; Upload BOM</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Fill metadata and attach BOM / Volume file to begin macro-skill execution.
            </p>
          </div>
        </div>

        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <SearchableSelect
              items={customers}
              value={customerId}
              onChange={setCustomerId}
              label="Customer *"
              placeholder="Select Customer..."
              searchPlaceholder="Search customers..."
              emptyMessage="No customers yet — add one in Settings"
              loading={customersLoading}
              testId="rfq-execution-customer"
            />
            <SearchableSelect
              items={projects}
              value={projectId}
              onChange={setProjectId}
              label="Project *"
              placeholder={customerId ? 'Select Project...' : 'Select a customer first'}
              searchPlaceholder="Search projects..."
              emptyMessage="No projects for this customer yet — add one in Settings"
              loading={projectsLoading}
              testId="rfq-execution-project"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-foreground">RFQ ID (Auto-Suggested)</label>
            <input
              value={rfqId}
              onChange={(e) => setRfqId(e.target.value)}
              placeholder="e.g. RFQ-000001"
              className="h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm font-medium text-foreground placeholder:text-muted-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
            {rfqIdMessage && <p className="text-[13px] text-destructive">{rfqIdMessage}</p>}
          </div>

          {bomFile ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <FileDropSlot label="BOM workbook" file={bomFile} onSelect={setBomFile} onClear={() => { setBomFile(null); setVolumeFile(null); }} />
              <FileDropSlot label="Volume file (optional)" file={volumeFile} onSelect={setVolumeFile} onClear={() => setVolumeFile(null)} />
            </div>
          ) : (
            <FilesDrop disabled={!rfqId.trim()} onPick={setPicked} />
          )}
          <AttachFilesDialog
            open={picked.length > 0}
            rfqId={rfqId.trim() || 'NEW'}
            files={picked}
            alreadyAttached={[]}
            onClose={() => setPicked([])}
            onReleased={() => undefined}
            onUseFiles={({ bom, volume }) => { setBomFile(bom); setVolumeFile(volume); }}
          />

          <FileDropSlot
            label="Gerber ZIP (optional)"
            file={gerberFile}
            onSelect={setGerberFile}
            onClear={() => setGerberFile(null)}
            accept=".zip"
            hint=".zip"
          />

          {submitError && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
              {submitError}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onCancel}>
              Cancel
            </Button>
            <Button onClick={() => { void handleStartRfq(); }} disabled={!canSubmit} size="sm">
              {submitting ? 'Creating…' : 'Create RFQ'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
