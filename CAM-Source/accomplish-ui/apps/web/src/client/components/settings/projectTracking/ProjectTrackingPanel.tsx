import { useState, useCallback } from 'react';
import { Plus, SpinnerGap } from '@phosphor-icons/react';
import { useProjectTrackingPanel } from './useProjectTrackingPanel';
import { CustomerProjectCard } from './CustomerProjectCard';

function AddRow({ placeholder, onAdd, disabled }: { placeholder: string; onAdd: (name: string) => Promise<boolean>; disabled?: boolean }) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || busy) { return; }
    setBusy(true);
    const ok = await onAdd(trimmed);
    setBusy(false);
    if (ok) { setValue(''); }
  }, [value, busy, onAdd]);

  return (
    <div className="flex items-center gap-2">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { void submit(); } }}
        placeholder={placeholder}
        disabled={disabled || busy}
        className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-[13px] text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/60 disabled:opacity-50"
      />
      <button
        type="button"
        onClick={() => { void submit(); }}
        disabled={disabled || busy || !value.trim()}
        className="flex shrink-0 items-center gap-1 rounded-lg bg-primary px-3 py-2 text-[13px] font-semibold text-primary-foreground transition disabled:opacity-50"
      >
        {busy ? <SpinnerGap className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" weight="bold" />}
        Add
      </button>
    </div>
  );
}

/** Settings > Project Tracking tab: Customer master data on the left,
 * Projects scoped to whichever customer is selected on the right. Mirrors
 * the Skills tab's CRUD shape (list + add + per-row rename/delete), just
 * with two related lists instead of one. */
export function ProjectTrackingPanel() {
  const p = useProjectTrackingPanel();

  if (p.loading) {
    return (
      <div className="flex items-center justify-center py-10 text-xs text-muted-foreground">
        <SpinnerGap className="mr-2 h-4 w-4 animate-spin" />
        Loading customers & projects...
      </div>
    );
  }

  const selectedCustomer = p.customers.find((c) => c.customer_id === p.selectedCustomerId);

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-muted-foreground">
        Every project belongs to exactly one customer. Adding a customer or project here makes it
        immediately available in the Create RFQ dropdowns.
      </p>

      {p.error && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {p.error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Customers</p>
          <AddRow placeholder="New customer name" onAdd={p.addCustomer} />
          <div className="space-y-1.5">
            {p.customers.length === 0 && (
              <p className="py-4 text-center text-xs text-muted-foreground">No customers yet.</p>
            )}
            {p.customers.map((c) => (
              <CustomerProjectCard
                key={c.customer_id}
                id={c.customer_id}
                name={c.customer_name}
                selected={c.customer_id === p.selectedCustomerId}
                onClick={() => p.setSelectedCustomerId(c.customer_id === p.selectedCustomerId ? null : c.customer_id)}
                onRename={p.editCustomer}
                onDelete={p.deleteCustomer}
              />
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Projects{selectedCustomer ? ` — ${selectedCustomer.customer_name}` : ''}
          </p>
          <AddRow
            placeholder={selectedCustomer ? 'New project name' : 'Select a customer first'}
            onAdd={p.addProject}
            disabled={!selectedCustomer}
          />
          <div className="space-y-1.5">
            {!selectedCustomer && (
              <p className="py-4 text-center text-xs text-muted-foreground">Select a customer to see its projects.</p>
            )}
            {selectedCustomer && p.projects.length === 0 && (
              <p className="py-4 text-center text-xs text-muted-foreground">No projects for this customer yet.</p>
            )}
            {p.projects.map((proj) => (
              <CustomerProjectCard
                key={proj.project_id}
                id={proj.project_id}
                name={proj.project_name}
                onRename={p.editProject}
                onDelete={p.deleteProject}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
