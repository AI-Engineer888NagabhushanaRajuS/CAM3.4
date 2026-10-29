import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { Currency } from '@/lib/accomplish';
import type { CreateCurrencyParams, UpdateCurrencyParams } from './useCurrenciesPanel';

interface CurrencyFormDialogProps {
  // Non-null in edit mode (currency code is immutable once created, so the
  // form omits that field and only allows editing name/rate).
  editing: Currency | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (params: CreateCurrencyParams) => Promise<void>;
  onUpdate: (currencyCode: string, patch: UpdateCurrencyParams) => Promise<void>;
}

const emptyForm = { currencyCode: '', currencyName: '', conversionRate: '' };

export function CurrencyFormDialog({ editing, open, onOpenChange, onCreate, onUpdate }: CurrencyFormDialogProps) {
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(
        editing
          ? { currencyCode: editing.currencyCode, currencyName: editing.currencyName, conversionRate: String(editing.conversionRate) }
          : emptyForm,
      );
      setError(null);
    }
  }, [open, editing]);

  const handleSubmit = async () => {
    const currencyCode = form.currencyCode.trim().toUpperCase();
    const currencyName = form.currencyName.trim();
    const conversionRate = Number(form.conversionRate);

    if (!editing && !/^[A-Z]{3}$/.test(currencyCode)) {
      setError('Currency code must be exactly 3 letters (ISO 4217, e.g. USD).');
      return;
    }
    if (!currencyName) {
      setError('Currency name is required.');
      return;
    }
    if (!(conversionRate > 0)) {
      setError('Conversion rate must be a positive number.');
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      if (editing) {
        await onUpdate(editing.currencyCode, { currencyName, conversionRate });
      } else {
        await onCreate({ currencyCode, currencyName, conversionRate });
      }
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save currency');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit ${editing.currencyCode}` : 'Add currency'}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          {!editing && (
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-muted-foreground">Currency code</label>
              <Input
                value={form.currencyCode}
                onChange={(e) => setForm((f) => ({ ...f, currencyCode: e.target.value.toUpperCase() }))}
                placeholder="GBP"
                maxLength={3}
              />
            </div>
          )}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">Currency name</label>
            <Input
              value={form.currencyName}
              onChange={(e) => setForm((f) => ({ ...f, currencyName: e.target.value }))}
              placeholder="British Pound"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">
              Conversion rate (units per 1 USD)
            </label>
            <Input
              type="number"
              step="any"
              value={form.conversionRate}
              onChange={(e) => setForm((f) => ({ ...f, conversionRate: e.target.value }))}
              placeholder="0.79"
            />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={() => { void handleSubmit(); }} disabled={submitting}>
            {submitting ? 'Saving…' : editing ? 'Save changes' : 'Add currency'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
