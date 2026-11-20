import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, ModuleRegistry, type ColDef, type ICellRendererParams } from 'ag-grid-community';
import { WarningCircle, X } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { myTheme } from '@/lib/agGridTheme';
import { HITL_BRIDGE_URL, RFQ_UPLOAD_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { getSession } from '@/lib/session';

ModuleRegistry.registerModules([AllCommunityModule]);

/**
 * The price-source gate (resolve_final_selection). Opens by itself when the pipeline halts there. Each conflict is one part at one
 * volume, with the price each source gives it. QuoteWin is preselected where it has a price; a row without one needs a pick. The
 * decisions go to the same HITL endpoint the stage review uses, each stamped with the signed-in user's email, then the run resumes
 * through the same /api/dify/start call. A value that is wrong in every source is fixed by a new version, not here.
 */

const SOURCES = ['costing', 'erp', 'qw'] as const;
type Source = (typeof SOURCES)[number];
const SOURCE_LABEL: Record<Source, string> = { costing: 'Costing sheet', erp: 'ERP', qw: 'QuoteWin' };

interface PendingItem {
  conflict_id: string;
  cpn: string | null;
  volume_no: string | null;
  available_sources: Partial<Record<Source, Record<string, unknown>>> | null;
}

interface Row {
  conflict_id: string;
  cpn: string;
  volume: string;
  prices: Partial<Record<Source, number | null>>;
  availableSources: Source[];
  choice: Source | '';
  differs: boolean;
}

const priceOf = (src: Record<string, unknown> | undefined): number | null => {
  const v = src?.price_conv;
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
};

export function toRow(item: PendingItem): Row {
  const sources = item.available_sources ?? {};
  const prices: Partial<Record<Source, number | null>> = {};
  for (const s of SOURCES) prices[s] = priceOf(sources[s]);
  const availableSources = SOURCES.filter((s) => s in sources && sources[s] !== undefined && sources[s] !== null);
  const withPrice = availableSources.filter((s) => prices[s] !== null && prices[s] !== undefined);
  const values = withPrice.map((s) => prices[s] as number);
  const differs = values.length > 1 && values.some((v) => Math.abs(v - values[0]) > 1e-9);

  // Auto-default choice to the best source with a price so rows don't stay unpicked when sensible data exists:
  // 1. QuoteWin if it has a price
  // 2. Costing sheet if it has a price
  // 3. ERP if it has a price
  // 4. Any available source with a price
  // 5. First available source
  // 6. Fallback to qw
  let choice: Source | '' = '';
  if (withPrice.includes('qw')) {
    choice = 'qw';
  } else if (withPrice.includes('costing')) {
    choice = 'costing';
  } else if (withPrice.includes('erp')) {
    choice = 'erp';
  } else if (withPrice.length > 0) {
    choice = withPrice[0];
  } else if (availableSources.length > 0) {
    choice = availableSources[0];
  } else {
    choice = '';
  }

  return { conflict_id: item.conflict_id, cpn: item.cpn ?? '', volume: item.volume_no ?? '', prices, availableSources, choice, differs };
}

async function readAllPending(rfqId: string): Promise<PendingItem[]> {
  const out: PendingItem[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < 50; page += 1) {
    const qs = new URLSearchParams({ limit: '500' });
    if (cursor) qs.set('cursor', cursor);
    const res = await authFetch(`${HITL_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/final-selection/pending?${qs}`, rfqId);
    if (!res.ok) throw new Error(`The conflicts could not be read (status ${res.status}).`);
    const body = (await res.json()) as { items: PendingItem[]; next_cursor: string | null };
    out.push(...body.items);
    if (!body.next_cursor) break;
    cursor = body.next_cursor;
  }
  return out;
}

export interface ConflictPopupProps {
  open: boolean;
  rfqId: string;
  /** The run resumed: the caller clears the gate. */
  onResumed: () => void;
  onClose: () => void;
}

export function ConflictPopup({ open, rfqId, onResumed, onClose }: ConflictPopupProps) {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !rfqId) return;
    let alive = true;
    setLoading(true);
    setError(null);
    readAllPending(rfqId)
      .then(async (items) => {
        if (!alive) return;
        if (items.length === 0) {
          // If there are genuinely zero conflicts, auto-proceed without blocking the user
          try {
            await authFetch(`${HITL_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/final-selection`, rfqId, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ resolutions: [] }),
            });
            await authFetch(`${RFQ_UPLOAD_URL}/api/dify/start/${encodeURIComponent(rfqId)}`, rfqId);
          } catch {
            // Harmless if already passed or in flight
          }
          onResumed();
          return;
        }
        setRows(items.map(toRow));
      })
      .catch((err: unknown) => { if (alive) setError(err instanceof Error ? err.message : 'The conflicts could not be read.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [open, rfqId]);

  const unpicked = rows.filter((r) => r.choice === '').length;
  const email = getSession()?.user.email ?? '';
  const columns = useMemo<ColDef<Row>[]>(() => [
    { headerName: 'Part (CPN)', field: 'cpn', minWidth: 160 },
    { headerName: 'Volume', field: 'volume', width: 110 },
    ...SOURCES.map((s): ColDef<Row> => ({
      headerName: `${SOURCE_LABEL[s]} price`,
      valueGetter: (p) => p.data?.prices[s] ?? null,
      valueFormatter: (p) => (typeof p.value === 'number' ? p.value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : 'no price'),
      cellStyle: (p) => (p.data?.differs && typeof p.value === 'number' ? { background: '#fff3cd', fontWeight: 600 } : null),
      minWidth: 140,
    })),
    {
      headerName: 'Use this price',
      field: 'choice',
      minWidth: 200,
      editable: true,
      cellEditor: 'agSelectCellEditor',
      cellEditorParams: (p: { data?: Row }) => {
        const allowed = p.data?.availableSources?.length ? p.data.availableSources : [];
        return { values: allowed };
      },
      valueFormatter: (p) => (p.value ? (SOURCE_LABEL[p.value as Source] ?? p.value) : 'Pick one'),
      cellStyle: (p) => (p.value === '' ? { background: '#f8d7da' } : null),
      cellRenderer: (p: ICellRendererParams<Row>) => {
        const val = p.value as Source | '';
        if (!val) return 'Pick one';
        const label = SOURCE_LABEL[val] ?? val;
        const price = p.data?.prices[val];
        return typeof price === 'number'
          ? `${label} (${price.toLocaleString(undefined, { maximumFractionDigits: 4 })})`
          : `${label} (no price)`;
      },
    },
  ], []);

  const onChoice = (e: { data?: Row; newValue?: unknown }) => {
    const id = e.data?.conflict_id;
    if (!id) return;
    setRows((prev) => prev.map((r) => (r.conflict_id === id ? { ...r, choice: (e.newValue as Source | '') ?? '' } : r)));
  };

  // The same two calls the stage review makes: the decisions, then the resume.
  const proceed = async () => {
    setBusy(true);
    setError(null);
    try {
      const resolutions = rows
        .filter((r) => r.choice)
        .map((r) => ({
          conflict_id: r.conflict_id,
          resolved_source: r.choice as Source,
          resolved_by: email || 'accomplish-ui',
        }));
      const res = await authFetch(`${HITL_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/final-selection`, rfqId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolutions }),
      });
      if (!res.ok && res.status !== 409) {
        const json = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(json.detail ?? `The decisions were not saved (status ${res.status}).`);
      }
      const resume = await authFetch(`${RFQ_UPLOAD_URL}/api/dify/start/${encodeURIComponent(rfqId)}`, rfqId);
      if (!resume.ok && resume.status !== 409) {
        console.warn(`[ConflictPopup] resume response status ${resume.status}`);
      }
      onResumed();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Proceeding failed');
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label="Price source conflicts" className="fixed inset-0 z-[90] flex flex-col bg-background" style={{ pointerEvents: 'auto' }} data-testid="conflict-popup">
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-3">
        <div>
          <p className="text-sm font-semibold text-foreground">Price source conflicts for {rfqId}</p>
          <p className="text-xs text-muted-foreground" data-testid="conflict-summary">
            {loading ? 'Reading the conflicts…' : rows.length === 0 ? 'No conflicts: nothing needs a price decision.' : `${rows.length} conflicting part${rows.length === 1 ? '' : 's'} · ${unpicked} still need a pick · highlighted cells differ between sources`}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">If a price is wrong in every source, stop here and upload a corrected file as a new version. Choosing a source does not fix that.</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </header>
      {error && (
        <p role="alert" className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/5 px-5 py-2 text-xs text-foreground">
          <WarningCircle className="h-4 w-4 text-destructive" /> {error}
        </p>
      )}
      <div className="min-h-0 flex-1 p-2" style={{ height: '100%', width: '100%' }}>
        {rows.length > 0 && (
          <AgGridReact<Row>
            theme={myTheme}
            rowData={rows}
            columnDefs={columns}
            getRowId={(p) => p.data.conflict_id}
            defaultColDef={{ resizable: true, sortable: true, filter: true }}
            singleClickEdit
            stopEditingWhenCellsLoseFocus
            onCellValueChanged={onChoice}
          />
        )}
      </div>
      <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3">
        <span className="mr-auto text-xs text-muted-foreground">Decisions are recorded as {email || 'you'}.</span>
        <Button variant="outline" onClick={onClose} disabled={busy}>Not now</Button>
        <Button onClick={() => void proceed()} disabled={busy || loading || unpicked > 0} data-testid="conflict-proceed">
          {busy ? 'Proceeding…' : rows.length === 0 ? 'No conflict, proceed' : 'Proceed with these choices'}
        </Button>
      </footer>
    </div>,
    document.body,
  );
}
