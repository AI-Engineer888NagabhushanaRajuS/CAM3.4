import { useRef, useState, type ComponentType } from 'react';
import { FileText, UploadSimple } from '@phosphor-icons/react';
import { StatusChip, type ChipState } from '@/components/ui/StatusChip';
import { UploadProgress } from '@/components/ui/UploadProgress';
import { UploadActions } from './UploadActions';
import { formatFileSize } from '@/lib/fileUtils';
import type { UploadStatus } from './useCostingSheetUpload';

interface UploadCardProps {
  label: string;
  accept: string;
  icon: ComponentType<{ className?: string }>;
  file: File | null;
  status: UploadStatus;
  progress: number;
  error: string | null;
  onSelect: (file: File) => void;
  onRemove: () => void;
}

const STATUS_CHIP: Record<UploadStatus, { state: ChipState; label: string }> = {
  idle: { state: 'pending', label: 'Awaiting file' },
  uploading: { state: 'running', label: 'Uploading' },
  success: { state: 'done', label: 'Uploaded' },
  error: { state: 'error', label: 'Failed' },
};

/**
 * Reusable single-file drag-and-drop upload card. Visual pattern matches
 * RfqIntakeUploadModal's dropzone (border-border idle, border-primary
 * drag-active, border-primary/50 filled) for design-system consistency.
 */
export function UploadCard({
  label,
  accept,
  icon: Icon,
  file,
  status,
  progress,
  error,
  onSelect,
  onRemove,
}: UploadCardProps) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const openPicker = () => inputRef.current?.click();

  const zoneClasses = dragOver
    ? 'border-primary bg-primary/5'
    : file
      ? 'border-primary/50 bg-primary/5'
      : 'border-border hover:border-muted-foreground';

  const chip = STATUS_CHIP[status];

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card/60 p-4">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-primary/40 bg-primary/20 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{label}</p>
        </div>
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-label={`${label} upload zone. Accepted file types: ${accept.replaceAll(',', ', ')}`}
        onClick={() => { if (!file) { openPicker(); } }}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !file) {
            e.preventDefault();
            openPicker();
          }
        }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const dropped = e.dataTransfer.files?.[0];
          if (dropped) { onSelect(dropped); }
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-3 py-5 text-center outline-none transition-colors focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/40 ${zoneClasses}`}
      >
        {file ? (
          <div className="flex w-full flex-col items-center gap-2">
            <div className="flex w-full items-center justify-center gap-2">
              <FileText className="h-4 w-4 shrink-0 text-primary" />
              <span className="max-w-[160px] truncate text-sm text-foreground">{file.name}</span>
              <UploadActions
                label={label}
                onReplace={openPicker}
                onRemove={onRemove}
                disabled={status === 'uploading'}
              />
            </div>
            <p className="text-[10px] text-muted-foreground">{formatFileSize(file.size)}</p>
            {status === 'uploading' && <UploadProgress value={progress} className="max-w-[180px]" />}
          </div>
        ) : (
          <>
            <UploadSimple className="mb-1.5 h-5 w-5 text-muted-foreground" />
            <p className="mb-1 text-xs text-muted-foreground">Drop file here or</p>
            <span className="text-sm font-medium text-primary">Browse files</span>
            <p className="mt-1 text-[10px] text-muted-foreground">{accept.replaceAll(',', ' · ')}</p>
          </>
        )}
      </div>

      <div aria-live="polite" className="flex items-center justify-between">
        <StatusChip state={chip.state} label={chip.label} />
        {error && <span className="text-[10px] text-destructive">{error}</span>}
      </div>

      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept={accept}
        onChange={(e) => {
          const picked = e.target.files?.[0];
          if (picked) { onSelect(picked); }
          e.target.value = '';
        }}
      />
    </div>
  );
}
