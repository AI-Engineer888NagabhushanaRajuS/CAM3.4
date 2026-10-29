import { CurrencyDollar, Database, EnvelopeSimple } from '@phosphor-icons/react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { UploadCard } from './UploadCard';
import { useCostingSheetUpload } from './useCostingSheetUpload';

interface AdditionalCostingSheetsModalProps {
  open: boolean;
  onClose: () => void;
}

const CARDS = [
  {
    key: 'customerFixedPrice',
    label: 'Customer Fixed Price',
    accept: '.xlsx,.csv',
    icon: CurrencyDollar,
  },
  {
    key: 'erpFile',
    label: 'ERP File',
    accept: '.xlsx,.csv',
    icon: Database,
  },
  {
    key: 'mail',
    label: 'Mail',
    accept: '.xlsx,.csv',
    icon: EnvelopeSimple,
  },
] as const;

/**
 * Additional Costing Sheets upload panel — Customer Fixed Price / ERP File /
 * Mail. Uses simulated (placeholder) uploads via useCostingSheetUpload since
 * no backend endpoint exists yet for these file types.
 */
export function AdditionalCostingSheetsModal({ open, onClose }: AdditionalCostingSheetsModalProps) {
  const customerFixedPrice = useCostingSheetUpload();
  const erpFile = useCostingSheetUpload();
  const mail = useCostingSheetUpload();

  const uploads = { customerFixedPrice, erpFile, mail } as const;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { onClose(); } }}>
      <DialogContent className="max-w-3xl border-border bg-popover">
        <DialogHeader>
          <DialogTitle className="text-popover-foreground">Additional Costing Sheets</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Optional supporting documents for the active RFQ — upload any that apply.
          </p>
        </DialogHeader>

        <div className="grid grid-cols-1 gap-4 py-2 md:grid-cols-3">
          {CARDS.map((card) => {
            const upload = uploads[card.key];
            return (
              <UploadCard
                key={card.key}
                label={card.label}
                accept={card.accept}
                icon={card.icon}
                file={upload.file}
                status={upload.status}
                progress={upload.progress}
                error={upload.error}
                onSelect={upload.selectFile}
                onRemove={upload.removeFile}
              />
            );
          })}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" size="sm" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
