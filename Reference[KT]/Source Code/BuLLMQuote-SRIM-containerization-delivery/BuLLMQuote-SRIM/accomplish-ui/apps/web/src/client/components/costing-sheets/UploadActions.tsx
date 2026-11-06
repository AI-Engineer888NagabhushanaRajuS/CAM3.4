import { ArrowsClockwise, X } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';

interface UploadActionsProps {
  label: string;
  onReplace: () => void;
  onRemove: () => void;
  disabled?: boolean;
}

/** Replace / Remove action row shown once a file has been selected. */
export function UploadActions({ label, onReplace, onRemove, disabled }: UploadActionsProps) {
  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        onClick={(e) => {
          e.stopPropagation();
          onReplace();
        }}
        disabled={disabled}
        aria-label={`Replace ${label} file`}
        className="text-slate-500 hover:text-slate-200"
      >
        <ArrowsClockwise className="h-3.5 w-3.5" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        disabled={disabled}
        aria-label={`Remove ${label} file`}
        className="text-slate-500 hover:text-red-400"
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
