import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { SearchableSelect, type SelectItem } from '@/components/ui/searchable-select';
import { logger } from '@/lib/logger';
import { getAccomplish } from '@/lib/accomplish';

interface RfqCreateFormProps {
  onCreated: (rfqId: string) => void;
  onCancel: () => void;
}

/** First step of the RFQ workflow: pick a Customer, then a Project scoped to
 * that customer, confirm/edit the auto-suggested RFQ ID, then hand off into
 * the existing (unmodified) intake/upload flow via onCreated. Rendered
 * inline in the right pane (Column 3), not as a popup dialog. */
export function RfqCreateForm({ onCreated, onCancel }: RfqCreateFormProps) {
  const [customers, setCustomers] = useState<SelectItem[]>([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [projects, setProjects] = useState<SelectItem[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [rfqId, setRfqId] = useState('');
  const [rfqIdMessage, setRfqIdMessage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // On mount: load customers and pre-fill the next suggested RFQ ID.
  useEffect(() => {
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
        logger.error('Failed to initialize Create RFQ form:', err);
      })
      .finally(() => setCustomersLoading(false));
  }, []);

  // Dependent dropdown: reload projects whenever the selected customer changes.
  useEffect(() => {
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

  // Live uniqueness validation as the suggested ID is edited -- reuses the
  // same checkRfqExists RPC the main RFQ-ID textbox already uses, now
  // covering both the legacy and Project Tracking tables (see daemon change).
  useEffect(() => {
    if (!rfqId.trim()) { setRfqIdMessage(null); return; }
    let cancelled = false;
    getAccomplish().checkRfqExists({ rfqId: rfqId.trim() })
      .then(({ exists }) => {
        if (!cancelled) { setRfqIdMessage(exists ? 'This RFQ ID already exists — choose a different one.' : null); }
      })
      .catch(() => { /* non-fatal — server-side createRfq still enforces uniqueness */ });
    return () => { cancelled = true; };
  }, [rfqId]);

  const handleCreate = useCallback(async () => {
    if (!customerId || !projectId || !rfqId.trim() || rfqIdMessage) { return; }
    setCreating(true);
    setCreateError(null);
    try {
      await getAccomplish().createRfq({ rfqId: rfqId.trim(), customerId, projectId });
      onCreated(rfqId.trim());
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }, [customerId, projectId, rfqId, rfqIdMessage, onCreated]);

  const canCreate = !!customerId && !!projectId && !!rfqId.trim() && !rfqIdMessage && !creating;

  return (
    <div className="mx-auto flex h-full max-w-md flex-col justify-center space-y-4 p-6">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Create RFQ</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Associate this RFQ with a Customer and Project before starting the intake workflow.
        </p>
      </div>

      <SearchableSelect
        items={customers}
        value={customerId}
        onChange={setCustomerId}
        label="Customer"
        placeholder="Select a customer"
        searchPlaceholder="Search customers..."
        emptyMessage="No customers yet — add one in Settings"
        loading={customersLoading}
        testId="rfq-create-customer"
      />

      <SearchableSelect
        items={projects}
        value={projectId}
        onChange={setProjectId}
        label="Project"
        placeholder={customerId ? 'Select a project' : 'Select a customer first'}
        searchPlaceholder="Search projects..."
        emptyMessage="No projects for this customer yet — add one in Settings"
        loading={projectsLoading}
        testId="rfq-create-project"
      />

      <div className="space-y-1.5">
        <label className="block text-sm font-medium text-foreground">RFQ ID</label>
        <input
          value={rfqId}
          onChange={(e) => setRfqId(e.target.value)}
          placeholder="e.g. RFQ-000001"
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/60"
        />
        <p className="text-[11px] text-muted-foreground">
          Auto-suggested — you can edit it, but it must stay unique.
        </p>
        {rfqIdMessage && <p className="text-[11px] text-destructive">{rfqIdMessage}</p>}
      </div>

      {createError && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {createError}
        </p>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={onCancel} className="text-xs text-muted-foreground hover:text-foreground">
          Cancel
        </button>
        <Button onClick={() => { void handleCreate(); }} disabled={!canCreate} size="sm">
          {creating ? 'Creating…' : 'Create RFQ'}
        </Button>
      </div>
    </div>
  );
}
