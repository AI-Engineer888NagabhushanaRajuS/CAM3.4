import { memo, useCallback } from 'react';
import type { Currency } from '@/lib/accomplish';

interface CurrencyCardProps {
  currency: Currency;
  isDefault: boolean;
  onToggleActive: (currencyCode: string, nextActive: boolean) => void;
  onEdit: (currency: Currency) => void;
  onDelete: (currencyCode: string) => void;
  onSetDefault: (currencyCode: string) => void;
  disabled?: boolean; // true while an in-flight mutation is pending for this row
}

// Mirrors UserCard.tsx's card shell/toggle-switch styling for visual
// consistency with the other admin Settings panels.
export const CurrencyCard = memo(function CurrencyCard({
  currency,
  isDefault,
  onToggleActive,
  onEdit,
  onDelete,
  onSetDefault,
  disabled,
}: CurrencyCardProps) {
  const handleToggle = useCallback(() => {
    onToggleActive(currency.currencyCode, !currency.isActive);
  }, [onToggleActive, currency.currencyCode, currency.isActive]);

  const handleEdit = useCallback(() => {
    onEdit(currency);
  }, [onEdit, currency]);

  const handleDelete = useCallback(() => {
    onDelete(currency.currencyCode);
  }, [onDelete, currency.currencyCode]);

  const handleSetDefault = useCallback(() => {
    onSetDefault(currency.currencyCode);
  }, [onSetDefault, currency.currencyCode]);

  return (
    <div className="group rounded-xl border border-border bg-card p-3.5 transition-all duration-200 hover:border-primary hover:shadow-md">
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
            {currency.currencyCode}
            {isDefault && (
              <span className="inline-flex items-center rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary">
                Default quote currency
              </span>
            )}
          </span>
          <p className="truncate text-[11px] text-muted-foreground">
            {currency.currencyName} · rate {currency.conversionRate}
          </p>
        </div>
        <button
          onClick={handleToggle}
          disabled={disabled}
          className={`relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50 ${
            currency.isActive ? 'bg-primary' : 'bg-muted'
          }`}
          aria-label={currency.isActive ? `Deactivate ${currency.currencyCode}` : `Activate ${currency.currencyCode}`}
        >
          <span
            className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
              currency.isActive ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      <div className="mt-2 flex items-center gap-3">
        <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
          {currency.isActive ? 'Active' : 'Inactive'}
        </span>
        <button
          onClick={handleEdit}
          disabled={disabled}
          className="text-[11px] font-medium text-primary hover:underline disabled:opacity-50"
        >
          Edit
        </button>
        {!isDefault && (
          <button
            onClick={handleSetDefault}
            disabled={disabled}
            className="text-[11px] font-medium text-primary hover:underline disabled:opacity-50"
          >
            Set as default
          </button>
        )}
        {!isDefault && (
          <button
            onClick={handleDelete}
            disabled={disabled}
            className="text-[11px] font-medium text-destructive hover:underline disabled:opacity-50"
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
});
