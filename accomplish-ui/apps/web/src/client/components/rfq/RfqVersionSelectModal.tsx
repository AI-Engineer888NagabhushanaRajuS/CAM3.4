import { useState } from 'react';
import { SpinnerGap, FileText, UploadSimple } from '@phosphor-icons/react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

export interface RfqFileVersion {
  version: number;
  isActive: boolean;
  processStage: number;
  hitlRequired: boolean;
  updatedAt: string;
  bom: { id: string; fileName: string } | null;
  quoteWin: { id: string; fileName: string } | null;
  costingSheet: { id: string; fileName: string } | null;
}

interface RfqVersionSelectModalProps {
  open: boolean;
  rfqId: string;
  versions: RfqFileVersion[];
  onClose: () => void;
  onSelectVersion: (v: RfqFileVersion) => Promise<void>;
  onUploadNew: () => void;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function RfqVersionSelectModal({
  open,
  rfqId,
  versions,
  onClose,
  onSelectVersion,
  onUploadNew,
}: RfqVersionSelectModalProps) {
  const [activating, setActivating] = useState<number | null>(null);

  const handleSelect = async (v: RfqFileVersion) => {
    setActivating(v.version);
    try {
      await onSelectVersion(v);
    } finally {
      setActivating(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(val) => { if (!val && activating === null) { onClose(); } }}>
      <DialogContent className="max-w-md border-border bg-card">
        <DialogHeader>
          <DialogTitle className="text-foreground">Select Existing Version</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Existing file versions for RFQ{' '}
            <span className="font-mono text-primary">{rfqId || '—'}</span>
          </p>
        </DialogHeader>

        <div className="max-h-72 overflow-y-auto space-y-2 py-2 pr-1">
          {versions.map((v) => (
            <div
              key={v.version}
              className="rounded-lg border border-border bg-muted/40 p-3.5 space-y-2"
            >
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-primary">
                  Version {v.version}
                  {v.isActive && (
                    <span className="rounded-full bg-primary/15 px-1.5 py-0.5 text-[9px] font-semibold text-primary normal-case tracking-normal">
                      Active
                    </span>
                  )}
                  {v.hitlRequired && (
                    <span className="rounded-full bg-yellow-500/15 px-1.5 py-0.5 text-[9px] font-semibold text-yellow-600 normal-case tracking-normal">
                      Awaiting review
                    </span>
                  )}
                </span>
                <span className="text-[10px] text-muted-foreground">{formatDate(v.updatedAt)}</span>
              </div>

              <div className="space-y-1">
                {v.bom && (
                  <div className="flex items-center gap-1.5">
                    <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="text-[11px] text-muted-foreground truncate max-w-[260px]">
                      BOM: <span className="text-foreground/80">{v.bom.fileName}</span>
                    </span>
                  </div>
                )}
                {v.quoteWin && (
                  <div className="flex items-center gap-1.5">
                    <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="text-[11px] text-muted-foreground truncate max-w-[260px]">
                      QuoteWin: <span className="text-foreground/80">{v.quoteWin.fileName}</span>
                    </span>
                  </div>
                )}
                {v.costingSheet && (
                  <div className="flex items-center gap-1.5">
                    <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="text-[11px] text-muted-foreground truncate max-w-[260px]">
                      Costing Sheet: <span className="text-foreground/80">{v.costingSheet.fileName}</span>
                    </span>
                  </div>
                )}
              </div>

              <Button
                size="sm"
                onClick={() => { void handleSelect(v); }}
                disabled={activating !== null}
                className="w-full mt-1"
              >
                {activating === v.version ? (
                  <>
                    <SpinnerGap className="h-3.5 w-3.5 animate-spin mr-1.5" />
                    Activating...
                  </>
                ) : v.isActive ? (
                  'Currently Active'
                ) : (
                  'Use This Version'
                )}
              </Button>
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            size="sm"
            onClick={onUploadNew}
            disabled={activating !== null}
            className="gap-1.5 text-muted-foreground hover:text-foreground"
          >
            <UploadSimple className="h-3.5 w-3.5" />
            Upload New Version
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
