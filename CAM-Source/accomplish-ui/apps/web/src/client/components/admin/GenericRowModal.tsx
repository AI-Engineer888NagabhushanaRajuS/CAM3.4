import { useState } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from '@phosphor-icons/react';
import type { MasterRow } from '../../lib/masterExcel';

interface GenericRowModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tabLabel: string;
  columns: string[];
  initialValues: MasterRow | null;
  onSave: (values: Record<string, string>) => void;
}

function seedValues(columns: string[], initialValues: MasterRow | null): Record<string, string> {
  const seeded: Record<string, string> = {};
  for (const column of columns) {
    seeded[column] = initialValues ? String(initialValues[column] ?? '') : '';
  }
  return seeded;
}

// Keyed by the record being edited (or 'new') in the parent so switching
// targets remounts this form and re-seeds via useState's lazy initializer.
function GenericRowForm({
  columns,
  initialValues,
  tabLabel,
  onSave,
}: {
  columns: string[];
  initialValues: MasterRow | null;
  tabLabel: string;
  onSave: (values: Record<string, string>) => void;
}) {
  const [values, setValues] = useState(() => seedValues(columns, initialValues));
  const isEdit = initialValues !== null;
  const hasAnyValue = Object.values(values).some((v) => v.trim() !== '');

  return (
    <>
      <div className="flex items-start justify-between border-b border-border px-5 py-4 dark:border-white/10">
        <div>
          <DialogPrimitive.Title className="text-base font-semibold text-foreground">
            {isEdit ? `Edit ${tabLabel} row` : `Add ${tabLabel} row`}
          </DialogPrimitive.Title>
          <p className="mt-0.5 text-xs text-muted-foreground">{tabLabel}</p>
        </div>
        <DialogPrimitive.Close className="rounded-md p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground">
          <X className="h-4 w-4" />
        </DialogPrimitive.Close>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {columns.map((column) => (
          <div key={column}>
            <label htmlFor={`field-${column}`} className="mb-1 block text-xs font-medium text-muted-foreground">
              {column}
            </label>
            <input
              id={`field-${column}`}
              value={values[column] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [column]: e.target.value }))}
              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/30 dark:border-white/10"
            />
          </div>
        ))}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-4 dark:border-white/10">
        <DialogPrimitive.Close asChild>
          <button type="button" className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground/80 transition hover:bg-muted dark:border-white/10">
            Cancel
          </button>
        </DialogPrimitive.Close>
        <button
          type="button"
          disabled={!hasAnyValue}
          onClick={() => onSave(values)}
          title={hasAnyValue ? undefined : 'Fill in at least one field before saving'}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:opacity-40"
        >
          Save
        </button>
      </div>
    </>
  );
}

export function GenericRowModal({ open, onOpenChange, tabLabel, columns, initialValues, onSave }: GenericRowModalProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <DialogPrimitive.Portal forceMount>
            <DialogPrimitive.Overlay asChild forceMount>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="fixed inset-0 z-50 bg-background/60 backdrop-blur-[8px]"
              />
            </DialogPrimitive.Overlay>
            <DialogPrimitive.Content asChild forceMount aria-describedby={undefined}>
              <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 12 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 12 }}
                transition={{ duration: 0.18, ease: 'easeOut' }}
                className="fixed inset-0 z-50 m-auto flex h-fit max-h-[85vh] w-full max-w-[520px] flex-col rounded-2xl border border-border bg-card shadow-2xl dark:border-white/10"
              >
                <GenericRowForm
                  key={initialValues?.id ?? 'new'}
                  columns={columns}
                  initialValues={initialValues}
                  tabLabel={tabLabel}
                  onSave={onSave}
                />
              </motion.div>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        )}
      </AnimatePresence>
    </DialogPrimitive.Root>
  );
}
