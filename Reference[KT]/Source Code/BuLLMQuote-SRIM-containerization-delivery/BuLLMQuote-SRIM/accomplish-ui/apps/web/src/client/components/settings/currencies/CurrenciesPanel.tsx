import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { Currency } from '@/lib/accomplish';
import { CurrencyCard } from './CurrencyCard';
import { CurrencyFormDialog } from './CurrencyFormDialog';
import { useCurrenciesPanel } from './useCurrenciesPanel';

// Mirrors UsersPanel.tsx's layout conventions -- vertical list, admin-gated
// Settings tab. Controls the currency_conversion_rates table and the single
// default_quote_currency_code setting that reporting_module/currency.py
// (centum intake) reads for CBOM workbook generation.
export function CurrenciesPanel() {
  const {
    loading,
    currencies,
    defaultCurrencyCode,
    pendingCurrencyCode,
    error,
    handleCreate,
    handleUpdate,
    handleDelete,
    handleToggleActive,
    handleSetDefault,
  } = useCurrenciesPanel();
  const [formOpen, setFormOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Currency | null>(null);

  if (loading) {
    return (
      <div className="flex h-[480px] items-center justify-center text-sm text-muted-foreground">
        Loading currencies...
      </div>
    );
  }

  const handleAdd = () => {
    setEditTarget(null);
    setFormOpen(true);
  };

  const handleEdit = (currency: Currency) => {
    setEditTarget(currency);
    setFormOpen(true);
  };

  const handleDeleteWithConfirm = (currencyCode: string) => {
    if (window.confirm(`Delete currency "${currencyCode}"? This cannot be undone.`)) {
      void handleDelete(currencyCode);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          The default quote currency is the standard output currency for CBOM, Price
          Splits, generated reports, and final exports.
        </p>
        <Button size="sm" onClick={handleAdd}>
          + Add currency
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex max-h-[480px] flex-col gap-2 overflow-y-auto pr-1">
        {currencies.map((currency) => (
          <CurrencyCard
            key={currency.currencyCode}
            currency={currency}
            isDefault={currency.currencyCode === defaultCurrencyCode}
            disabled={pendingCurrencyCode === currency.currencyCode}
            onToggleActive={(code, nextActive) => { void handleToggleActive(code, nextActive); }}
            onEdit={handleEdit}
            onDelete={handleDeleteWithConfirm}
            onSetDefault={(code) => { void handleSetDefault(code); }}
          />
        ))}
      </div>
      <CurrencyFormDialog
        editing={editTarget}
        open={formOpen}
        onOpenChange={setFormOpen}
        onCreate={handleCreate}
        onUpdate={handleUpdate}
      />
    </div>
  );
}
