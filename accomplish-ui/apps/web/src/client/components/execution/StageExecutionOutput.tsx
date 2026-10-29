// Location: src/renderer/components/StageExecutionOutput.tsx
import { useMemo, useState, useCallback, useEffect, useRef } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, ModuleRegistry, ColDef, CellValueChangedEvent, IRowNode } from 'ag-grid-community';
import { SpinnerGap, FileXls, ArrowCounterClockwise } from '@phosphor-icons/react';
import { utils, writeFile } from 'xlsx';
// exceljs, not xlsx, for gerberPreview's download -- xlsx (SheetJS
// Community, v0.18.5) cannot write cell fill styles (Pro-only feature),
// confirmed before picking this. Only used for the one export that needs
// the manual-edit yellow highlight; everything else keeps using the
// lighter-weight `xlsx` path above.
import ExcelJS from 'exceljs';
import { BomQualityStrip, findDuplicateMpns, type QualityFilter } from './BomQualityStrip';
import type { WorkflowStageId } from '../../App';
import { myTheme } from '../../lib/agGridTheme';
import { PYTHON_BRIDGE_URL, HITL_BRIDGE_URL, RFQ_UPLOAD_URL } from '../../config/endpoints';
import { authFetch, authDownload } from '../../lib/apiAuth';

ModuleRegistry.registerModules([AllCommunityModule]);

const PYTHON_BRIDGE = PYTHON_BRIDGE_URL;
// hitl_router.py — the final_selection_conflicts review/resolve service (stage 6,
// pricingConsolidation). Separate microservice from PYTHON_BRIDGE.
const HITL_BRIDGE = HITL_BRIDGE_URL;
// upload_server.py — same base URL App.tsx's RFQ_UPLOAD already resumes a
// paused Dify run through (GET /api/dify/start/{rfqId}).
const RFQ_UPLOAD_BRIDGE = RFQ_UPLOAD_URL;

// Shared amber highlight for rows with an unsaved pending edit -- used by both
// the 'preview' and 'cbomPreview' grids' getRowStyle callbacks below.
const PENDING_EDIT_ROW_STYLE = { backgroundColor: 'rgba(234,179,8,0.16)', borderLeft: '2px solid rgba(234,179,8,0.6)' };

// Cell-level "this field has ever been manually edited" highlight for
// rfqBomPreview/gerberPreview specifically -- MUST match
// mcp-tools/shared/highlight_style.py's MANUAL_EDIT_FILL_ARGB (both Python
// exports and this frontend need the identical color). Sticky semantic: once
// a cell is marked edited (locally via touchedFields, or persisted via
// _edited_fields/provenance), it stays yellow even if the value is later
// changed back to its original -- never a live value-diff.
const MANUAL_EDIT_FILL = '#FFF9C4';
const MANUAL_EDIT_CELL_STYLE = { backgroundColor: MANUAL_EDIT_FILL };

// Must match duck_db_api.py's RFQ_EDITABLE_FIELDS exactly -- the columns
// PUT /api/bom/batch-update-rfq/{rfqId} will actually persist. Anything not
// in this list can be marked editable in the grid but the backend will
// silently ignore it, so keep these two lists in sync.
const RFQ_EDITABLE_FIELDS = [
  'fg', 'parent_fg', 'cpn', 'mpn', 'mfr', 'description', 'commodity',
  'bom_qty', 'required_qty', 'uom', 'part_type',
  'selected_supplier', 'selected_unit_price', 'selected_moq', 'selected_currency',
];

interface HitlContext {
  rfqId: string;
  stage: string;
  type: 'preview' | 'alternates' | 'pricingSources' | 'cbomPreview' | 'priceSourceReview' | 'yesNo' | 'rfqBomPreview' | 'gerberPreview';
  message?: string;
}

interface StageExecutionOutputProps {
  rpcClient: { request: (channel: string, args: unknown[]) => Promise<unknown> };
  hitlContextData: HitlContext;
  rowDataPayload: Record<string, unknown>[];
  onNavigateToStage?: (stageId: WorkflowStageId) => void;
}

interface AlternateSupplier {
  supplier: string;
  price: number;
  moq: number;
  lead_time: string;
  stock: number;
}

interface AlternateCandidate {
  mpn: string;
  manufacturer: string;
  bom_item_id: string;
  is_preferred: boolean;
  description: string;
  suppliers: AlternateSupplier[];
}

interface AlternateGroup {
  cpn: string;
  required_qty: number;
  alternates: AlternateCandidate[];
}

interface AlternateRow {
  cpn: string;
  required_qty: number;
  mpn: string;
  manufacturer: string;
  bom_item_id: string;
  description: string;
  suppliers: AlternateSupplier[];
}

// One entry per source ('costing' | 'erp' | 'qw') final_selection_conflicts's
// available_sources JSONB carries for a disputed cbom row.
interface ConflictSourceValues {
  price_conv: number | null;
  price_original: number | null;
  currency_original: string | null;
  mfg_name: string | null;
  supp_name: string | null;
  pkg_qty: number | null;
  moq: number | null;
  lead_time: string | null;
  unit_of_measure: string | null;
}

interface PendingConflict {
  conflict_id: string;
  cbom_item_id: string;
  bom_item_id: string;
  volume_no: number;
  cpn: string;
  available_sources: Record<string, ConflictSourceValues>;
}

interface ConflictSourceRow extends ConflictSourceValues {
  conflict_id: string;
  cpn: string;
  source: string;
}

export function StageExecutionOutput({ rpcClient, hitlContextData, rowDataPayload, onNavigateToStage }: StageExecutionOutputProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingEdits, setPendingEdits] = useState<Record<string, Record<string, unknown>>>({});
  // Pre-edit snapshot of each row currently in pendingEdits, captured once on
  // the FIRST edit to that row (see handleCellValueChanged) -- lets Undo
  // restore true original values no matter how many times a row was re-edited.
  const [originalRowValues, setOriginalRowValues] = useState<Record<string, Record<string, unknown>>>({});
  // Cell-level "has this field ever been touched this editing session" --
  // rfqBomPreview/gerberPreview only (see MANUAL_EDIT_CELL_STYLE). Sticky:
  // only ever grows (a field is added the first time it's edited, never
  // removed just because a later edit happens to match the original value
  // again) -- matches the persisted _edited_fields/provenance semantic
  // exactly, so there's no visible difference between "unsaved" and
  // "persisted" yellow, just a change in which state is backing it.
  const [touchedFields, setTouchedFields] = useState<Record<string, Set<string>>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [qualityFilter, setQualityFilter] = useState<QualityFilter>('all');
  const gridRef = useRef<AgGridReact>(null);

  const [alternates, setAlternates] = useState<AlternateGroup[]>([]);
  const [alternatesLoading, setAlternatesLoading] = useState(false);
  const [alternatesError, setAlternatesError] = useState<string | null>(null);
  const [selectedByCpn, setSelectedByCpn] = useState<Record<string, string>>({});

  const [cbomRows, setCbomRows] = useState<Record<string, unknown>[]>([]);
  const [cbomLoading, setCbomLoading] = useState(false);
  const [cbomError, setCbomError] = useState<string | null>(null);

  const [rfqPreviewRows, setRfqPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [rfqPreviewLoading, setRfqPreviewLoading] = useState(false);
  const [rfqPreviewError, setRfqPreviewError] = useState<string | null>(null);

  const [gerberGeometry, setGerberGeometry] = useState<Record<string, unknown> | null>(null);
  const [gerberChecklist, setGerberChecklist] = useState<Record<string, unknown>[]>([]);
  const [gerberLoading, setGerberLoading] = useState(false);
  const [gerberError, setGerberError] = useState<string | null>(null);

  const [conflicts, setConflicts] = useState<PendingConflict[]>([]);
  const [conflictsLoading, setConflictsLoading] = useState(false);
  const [conflictsLoadingMore, setConflictsLoadingMore] = useState(false);
  const [conflictsError, setConflictsError] = useState<string | null>(null);
  const [conflictsNextCursor, setConflictsNextCursor] = useState<string | null>(null);
  const [selectedSourceByConflict, setSelectedSourceByConflict] = useState<Record<string, string>>({});
  const [resolvingConflictId, setResolvingConflictId] = useState<string | null>(null);
  // Stage 6 -> stage 7 hand-off: once every conflict is resolved, transition
  // straight into the final costed-BOM preview client-side — no backend
  // skill/macro_category exists for priceDecision (verified against
  // system_skills_registry: nothing is registered at macro_category=7), so
  // this is a pure UI transition rather than a new hitl:request event.
  const [showFinalPreview, setShowFinalPreview] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  // Populated once "Clear & Resume Pipeline" finishes on the cbomPreview
  // screen — that resume call blocks until the whole Dify run (including
  // export_reports) completes, so by the time it resolves the export
  // workbook already exists on disk; this just surfaces its filename.
  const [exportInfo, setExportInfo] = useState<{ filename: string; generatedAt: string } | null>(null);

  // Extract rows from { success, data: [...] } format or use flat array directly
  const rowData = useMemo(() => {
    if (Array.isArray(rowDataPayload)) { return rowDataPayload; }
    const nested = (rowDataPayload as unknown as { data?: Record<string, unknown>[] }).data;
    return nested ?? [];
  }, [rowDataPayload]);

  const duplicateMpns = useMemo(() => findDuplicateMpns(rowData), [rowData]);

  // KPI tile clicks filter the grid via AG Grid's external filter hooks.
  const isExternalFilterPresent = useCallback(() => qualityFilter !== 'all', [qualityFilter]);
  const doesExternalFilterPass = useCallback(
    (node: IRowNode) => {
      const row = node.data as Record<string, unknown> | undefined;
      if (!row) { return true; }
      if (qualityFilter === 'missingCpn') {
        return row.cpn === null || row.cpn === undefined || row.cpn === '';
      }
      if (qualityFilter === 'duplicateMpn') {
        return duplicateMpns.has(String(row.mpn ?? ''));
      }
      if (qualityFilter === 'qtyMismatch') {
        return row.bom_qty !== row.required_qty;
      }
      return true;
    },
    [qualityFilter, duplicateMpns],
  );

  useEffect(() => {
    gridRef.current?.api?.onFilterChanged();
  }, [qualityFilter]);

  // 'pricingSources' (Consolidated-stage "Pricing Sources Choosing") reuses this
  // flow as-is — same supplier/alternate-selection shape, just a different stage
  // triggers it. Fires automatically; no user-triggered toggle.
  const isAlternatesLike = hitlContextData.type === 'alternates' || hitlContextData.type === 'pricingSources';

  useEffect(() => {
    if (!isAlternatesLike) { return; }

    setAlternatesLoading(true);
    setAlternatesError(null);

    authFetch(`${PYTHON_BRIDGE}/api/bom/alternatives/${hitlContextData.rfqId}`, hitlContextData.rfqId)
      .then(async (r) => {
        const json = await r.json().catch(() => ({}));
        if (!r.ok) {
          throw new Error((json as { detail?: string }).detail ?? `Server error ${r.status}`);
        }
        return json as { data: AlternateGroup[] };
      })
      .then((json) => {
        const groups = json.data ?? [];
        setAlternates(groups);

        const preferred: Record<string, string> = {};
        for (const group of groups) {
          const pref = group.alternates.find((a) => a.is_preferred);
          if (pref) { preferred[group.cpn] = pref.mpn; }
        }
        setSelectedByCpn(preferred);
      })
      .catch((err) => {
        setAlternatesError(err instanceof Error ? err.message : 'Failed to load alternates');
      })
      .finally(() => setAlternatesLoading(false));
  }, [hitlContextData.rfqId, isAlternatesLike]);

  // Also true after the stage 6 -> 7 client-side hand-off (showFinalPreview),
  // not just when a real hitl:request arrives with type 'cbomPreview' — both
  // paths render/fetch the exact same costed-BOM preview.
  const isCbomPreview = hitlContextData.type === 'cbomPreview' || showFinalPreview;

  // Stage 7 (priceDecision) — cbomPreview no longer arrives via the bulk SSE
  // broadcast (removed on the daemon side: bulk row broadcasting reintroduces
  // the exact "everything in one payload" problem HITL was redesigned to
  // avoid). Instead it's fetched here from the cbom-backed preview endpoint,
  // looping cursor pages to build the full FG-wise set client-side — AG Grid
  // Community's own row grouping/pagination then take over from there, same
  // as every other mode in this file.
  interface CbomCursor { cursor_fg: string; cursor_cpn: string; cursor_id: string }
  interface CbomPreviewPage {
    data?: Record<string, unknown>[];
    next_cursor?: CbomCursor | null;
    detail?: string;
  }

  useEffect(() => {
    if (!isCbomPreview) { return; }

    let cancelled = false;
    setCbomLoading(true);
    setCbomError(null);

    const fetchAllPages = async () => {
      const collected: Record<string, unknown>[] = [];
      let cursor: CbomCursor | null = null;

      for (;;) {
        const params = new URLSearchParams({ limit: '500' });
        if (cursor) {
          params.set('cursor_fg', cursor.cursor_fg);
          params.set('cursor_cpn', cursor.cursor_cpn);
          params.set('cursor_id', cursor.cursor_id);
        }

        const res = await authFetch(`${PYTHON_BRIDGE}/api/bom/preview/${hitlContextData.rfqId}?${params.toString()}`, hitlContextData.rfqId);
        const json = (await res.json().catch(() => ({}))) as CbomPreviewPage;
        if (!res.ok) {
          throw new Error(json.detail ?? `Server error ${res.status}`);
        }

        collected.push(...(json.data ?? []));
        const next = json.next_cursor ?? null;
        if (!next) { break; }
        cursor = next;
      }

      return collected;
    };

    fetchAllPages()
      .then((rows) => { if (!cancelled) { setCbomRows(rows); } })
      .catch((err) => {
        if (!cancelled) { setCbomError(err instanceof Error ? err.message : 'Failed to load costed BOM'); }
      })
      .finally(() => { if (!cancelled) { setCbomLoading(false); } });

    return () => { cancelled = true; };
  }, [hitlContextData.rfqId, isCbomPreview]);

  // Stage 7 (priceDecision) for RFQ_Flow specifically — the finalized,
  // deduplicated BOM from processed_bom_items, post apply_alternatives.
  // Single GET, no cursor paging: RFQ_Flow's row counts (tens/hundreds) never
  // approach the volumes the cbom-preview cursor pagination was built for.
  const isRfqPreview = hitlContextData.type === 'rfqBomPreview';

  useEffect(() => {
    if (!isRfqPreview) { return; }

    let cancelled = false;
    setRfqPreviewLoading(true);
    setRfqPreviewError(null);

    authFetch(`${PYTHON_BRIDGE}/api/bom/rfq-preview/${hitlContextData.rfqId}`, hitlContextData.rfqId)
      .then(async (r) => {
        const json = await r.json().catch(() => ({}));
        if (!r.ok) {
          throw new Error((json as { detail?: string }).detail ?? `Server error ${r.status}`);
        }
        return json as { data?: Record<string, unknown>[] };
      })
      .then((json) => { if (!cancelled) { setRfqPreviewRows(json.data ?? []); } })
      .catch((err) => {
        if (!cancelled) { setRfqPreviewError(err instanceof Error ? err.message : 'Failed to load BOM preview'); }
      })
      .finally(() => { if (!cancelled) { setRfqPreviewLoading(false); } });

    return () => { cancelled = true; };
  }, [hitlContextData.rfqId, isRfqPreview]);

  // RFQ_Flow's optional Gerber ZIP feature-extraction preview -- rows come
  // from gerber_geometry (one object) + gerber_checklist (34 rows) in
  // bom_storage.duckdb, written by gerber_integration__extract_features.
  // Same single-GET, no-pagination reasoning as isRfqPreview above.
  const isGerberPreview = hitlContextData.type === 'gerberPreview';

  useEffect(() => {
    if (!isGerberPreview) { return; }

    let cancelled = false;
    setGerberLoading(true);
    setGerberError(null);

    authFetch(`${PYTHON_BRIDGE}/api/bom/gerber-preview/${hitlContextData.rfqId}`, hitlContextData.rfqId)
      .then(async (r) => {
        const json = await r.json().catch(() => ({}));
        if (!r.ok) {
          throw new Error((json as { detail?: string }).detail ?? `Server error ${r.status}`);
        }
        return json as { geometry?: Record<string, unknown> | null; checklist?: Record<string, unknown>[] };
      })
      .then((json) => {
        if (!cancelled) {
          setGerberGeometry(json.geometry ?? null);
          setGerberChecklist(json.checklist ?? []);
        }
      })
      .catch((err) => {
        if (!cancelled) { setGerberError(err instanceof Error ? err.message : 'Failed to load Gerber preview'); }
      })
      .finally(() => { if (!cancelled) { setGerberLoading(false); } });

    return () => { cancelled = true; };
  }, [hitlContextData.rfqId, isGerberPreview]);

  // CPN groups with no selection yet -- a candidate with zero distributor
  // pricing (every supplier column null) renders with an empty suppliers[]
  // list and no obvious price to compare, which is easy to skip without
  // noticing. Surfacing this count explicitly (and gating the resume button
  // on it) replaces the previous silent behavior: clicking "Clear & Resume
  // Pipeline" with conflicts still open just re-halted at this same screen
  // every time, indistinguishable from the button doing nothing at all.
  const unresolvedAlternateCpns = useMemo(
    () => alternates.filter((group) => !selectedByCpn[group.cpn]).length,
    [alternates, selectedByCpn],
  );

  const alternateRows = useMemo<AlternateRow[]>(
    () =>
      alternates.flatMap((group) =>
        group.alternates.map((alt) => ({
          cpn: group.cpn,
          required_qty: group.required_qty,
          mpn: alt.mpn,
          manufacturer: alt.manufacturer,
          bom_item_id: alt.bom_item_id,
          description: alt.description,
          suppliers: alt.suppliers,
        })),
      ),
    [alternates],
  );

  // The Suppliers column renders one line per supplier — AG Grid's default fixed
  // row height doesn't grow to fit that, so rows with 2+ suppliers overflow and
  // visually bleed into the row below. Size each row to its actual supplier count.
  const getAlternateRowHeight = useCallback((params: { data?: AlternateRow }) => {
    const supplierCount = Math.max(params.data?.suppliers.length ?? 0, 1);
    return 28 + supplierCount * 18;
  }, []);

  const handleSelectAlternate = useCallback(
    async (cpn: string, mpn: string) => {
      const previous = selectedByCpn[cpn];
      setSelectedByCpn((prev) => ({ ...prev, [cpn]: mpn }));

      try {
        const res = await authFetch(
          `${PYTHON_BRIDGE}/api/bom/alternatives/${hitlContextData.rfqId}/select`,
          hitlContextData.rfqId,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cpn, mpn }),
          },
        );

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail ?? `Server error ${res.status}`);
        }
      } catch (err) {
        setSelectedByCpn((prev) => ({ ...prev, [cpn]: previous }));
        setAlternatesError(err instanceof Error ? err.message : 'Selection failed');
      }
    },
    [selectedByCpn, hitlContextData.rfqId],
  );

  const alternateColumnDefs = useMemo<ColDef[]>(
    () => [
      { field: 'bom_item_id', hide: true },
      { field: 'cpn', headerName: 'CPN', width: 110, pinned: 'left', filter: true },
      { field: 'required_qty', headerName: 'Req Qty', type: 'numericColumn', width: 100 },
      { field: 'manufacturer', headerName: 'Manufacturer', width: 140 },
      { field: 'mpn', headerName: 'MPN', width: 130, filter: true },
      { field: 'description', headerName: 'Description', minWidth: 200, flex: 1 },
      {
        headerName: 'Suppliers',
        minWidth: 260,
        flex: 1,
        cellRenderer: (params: { data?: AlternateRow }) => {
          const suppliers = params.data?.suppliers ?? [];
          if (suppliers.length === 0) { return '—'; }
          return (
            <div className="text-[11px] leading-tight py-1 space-y-0.5">
              {suppliers.map((s) => (
                <div key={s.supplier}>
                  {s.supplier} — ${s.price} · MOQ {s.moq} · {s.lead_time} · {s.stock} in stock
                </div>
              ))}
            </div>
          );
        },
      },
      {
        headerName: 'Select',
        width: 90,
        pinned: 'right',
        cellRenderer: (params: { data?: AlternateRow }) => {
          const row = params.data;
          if (!row) { return null; }
          return (
            <input
              type="radio"
              name={`alt-select-${row.cpn}`}
              checked={selectedByCpn[row.cpn] === row.mpn}
              onChange={() => { void handleSelectAlternate(row.cpn, row.mpn); }}
              aria-label={`Select ${row.mpn} for ${row.cpn}`}
            />
          );
        },
      },
    ],
    [selectedByCpn, handleSelectAlternate],
  );

  const isPriceSourceReview = hitlContextData.type === 'priceSourceReview';

  const fetchConflictsPage = useCallback(
    async (cursor: string | null) => {
      const params = new URLSearchParams({ limit: '200' });
      if (cursor) { params.set('cursor', cursor); }

      const res = await authFetch(
        `${HITL_BRIDGE}/api/rfq/${hitlContextData.rfqId}/final-selection/pending?${params.toString()}`,
        hitlContextData.rfqId,
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error((json as { detail?: string }).detail ?? `Server error ${res.status}`);
      }
      return json as { items: PendingConflict[]; next_cursor: string | null };
    },
    [hitlContextData.rfqId],
  );

  // Stage 6 (pricingConsolidation) — reviews final_selection_conflicts rows
  // (2+ candidate sources for the same cbom line) via hitl_router.py, a
  // separate microservice from PYTHON_BRIDGE's cbom-preview endpoint. Fetches
  // the first page on mount; further pages are pulled explicitly via
  // "Load More" rather than all at once, consistent with why this was
  // cursor-paginated server-side in the first place (an RFQ can have
  // thousands of conflicting rows).
  useEffect(() => {
    if (!isPriceSourceReview) { return; }

    let cancelled = false;
    setConflictsLoading(true);
    setConflictsError(null);
    setConflicts([]);
    setShowFinalPreview(false);
    setSelectedSourceByConflict({});

    fetchConflictsPage(null)
      .then(async (page) => {
        if (cancelled) { return; }
        if (page.items.length === 0) {
          // Nothing to reconcile (e.g. only one pricing source was
          // uploaded) -- confirm skill 6 complete (no human decision
          // needed here) and go straight to the CBOM preview, which is
          // where the actual review for this upload combination happens.
          // Without this, the user would be stuck on a dead-end "no
          // conflicts" screen with no way to proceed.
          const res = await authFetch(`${HITL_BRIDGE}/api/rfq/${hitlContextData.rfqId}/final-selection`, hitlContextData.rfqId, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ resolutions: [] }),
          });
          if (!res.ok) {
            const json = await res.json().catch(() => ({}));
            throw new Error((json as { detail?: string }).detail ?? `Server error ${res.status}`);
          }
          if (!cancelled) { setShowFinalPreview(true); }
          return;
        }
        setConflicts(page.items);
        setConflictsNextCursor(page.next_cursor);
      })
      .catch((err) => {
        if (!cancelled) { setConflictsError(err instanceof Error ? err.message : 'Failed to load conflicts'); }
      })
      .finally(() => { if (!cancelled) { setConflictsLoading(false); } });

    return () => { cancelled = true; };
  }, [isPriceSourceReview, fetchConflictsPage, hitlContextData.rfqId]);

  const handleLoadMoreConflicts = useCallback(async () => {
    if (!conflictsNextCursor) { return; }
    setConflictsLoadingMore(true);
    try {
      const page = await fetchConflictsPage(conflictsNextCursor);
      setConflicts((prev) => [...prev, ...page.items]);
      setConflictsNextCursor(page.next_cursor);
    } catch (err) {
      setConflictsError(err instanceof Error ? err.message : 'Failed to load more conflicts');
    } finally {
      setConflictsLoadingMore(false);
    }
  }, [conflictsNextCursor, fetchConflictsPage]);

  // One row per (conflict_id, source) pair — mirrors alternates' flat
  // (cpn, mpn) row shape, just keyed by conflict_id instead of cpn.
  const conflictSourceRows = useMemo<ConflictSourceRow[]>(
    () =>
      conflicts.flatMap((conflict) =>
        Object.entries(conflict.available_sources).map(([source, values]) => ({
          conflict_id: conflict.conflict_id,
          cpn: conflict.cpn,
          source,
          ...values,
        })),
      ),
    [conflicts],
  );

  const handleSelectConflictSource = useCallback(
    async (conflictId: string, source: string) => {
      const previous = selectedSourceByConflict[conflictId];
      setSelectedSourceByConflict((prev) => ({ ...prev, [conflictId]: source }));
      setResolvingConflictId(conflictId);

      try {
        const res = await authFetch(`${HITL_BRIDGE}/api/rfq/${hitlContextData.rfqId}/final-selection`, hitlContextData.rfqId, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            resolutions: [{ conflict_id: conflictId, resolved_source: source, resolved_by: 'accomplish-ui' }],
          }),
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error((json as { detail?: string }).detail ?? `Server error ${res.status}`);
        }

        // Resolved conflicts drop out of hitl_router.py's pending set
        // (WHERE resolved_source IS NULL) — remove it here too so the grid
        // reflects the same "still pending" view the backend would return.
        setConflicts((prev) => prev.filter((c) => c.conflict_id !== conflictId));

        const remaining = (json as { remaining?: number }).remaining;
        if (remaining === 0) {
          // Every conflict is resolved — hand off straight into the final
          // costed-BOM preview (stage 7) rather than clearing/resuming
          // immediately. The pipeline itself stays paused until the reviewer
          // confirms the preview via "Clear & Resume Pipeline" below
          // (handleConfirmAndResume), which is what actually calls
          // /api/dify/start.
          setShowFinalPreview(true);
        }
      } catch (err) {
        setSelectedSourceByConflict((prev) => ({ ...prev, [conflictId]: previous }));
        setConflictsError(err instanceof Error ? err.message : 'Resolution failed');
      } finally {
        setResolvingConflictId(null);
      }
    },
    [selectedSourceByConflict, hitlContextData.rfqId],
  );

  const conflictColumnDefs = useMemo<ColDef[]>(
    () => [
      { field: 'cpn', headerName: 'CPN', width: 120, pinned: 'left', filter: true },
      { field: 'source', headerName: 'Source', width: 90, pinned: 'left' },
      { field: 'mfg_name', headerName: 'Manufacturer', width: 140 },
      { field: 'price_conv', headerName: 'Price (Conv)', type: 'numericColumn', width: 110 },
      { field: 'price_original', headerName: 'Price (Orig)', type: 'numericColumn', width: 110 },
      { field: 'currency_original', headerName: 'Currency', width: 90 },
      { field: 'supp_name', headerName: 'Supplier', width: 140 },
      { field: 'pkg_qty', headerName: 'Pkg Qty', type: 'numericColumn', width: 90 },
      { field: 'moq', headerName: 'MOQ', type: 'numericColumn', width: 90 },
      { field: 'lead_time', headerName: 'Lead Time', width: 100 },
      { field: 'unit_of_measure', headerName: 'UOM', width: 80 },
      {
        headerName: 'Select',
        width: 90,
        pinned: 'right',
        cellRenderer: (params: { data?: ConflictSourceRow }) => {
          const row = params.data;
          if (!row) { return null; }
          const isResolving = resolvingConflictId === row.conflict_id;
          return (
            <input
              type="radio"
              name={`conflict-select-${row.conflict_id}`}
              checked={selectedSourceByConflict[row.conflict_id] === row.source}
              disabled={isResolving}
              onChange={() => { void handleSelectConflictSource(row.conflict_id, row.source); }}
              aria-label={`Select ${row.source} for ${row.cpn}`}
            />
          );
        },
      },
    ],
    [selectedSourceByConflict, resolvingConflictId, handleSelectConflictSource],
  );

  const submitAction = async (isApproved: boolean) => {
    setIsSubmitting(true);
    try {
      await rpcClient.request('hitl:submit-decision', [hitlContextData.rfqId, isApproved]);
    } catch (err) {
      console.error('Failed executing override clearance:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  // RFQ_Flow's alternates review (stage 6) needs the exact same real-resume
  // treatment as cbomPreview/rfqPreview below -- narrowly scoped to 'alternates'
  // itself (not the whole isAlternatesLike group), since 'pricingSources'
  // reuses this same grid for a separate, unrelated feature never verified
  // against this fix.
  const isAlternatesReview = hitlContextData.type === 'alternates';

  // "Clear & Resume Pipeline" for the costed-BOM preview specifically needs to
  // actually resume the paused Dify run first — whether the reviewer arrived
  // here via a real hitl:request (type 'cbomPreview') or via the stage 6 -> 7
  // client-side hand-off (showFinalPreview), the backend was left paused
  // either way and nothing else re-triggers it. The generic submitAction()
  // path below only fires the daemon's hitl:submit-decision RPC, which wakes
  // a legacy /api/orchestrator/resume webhook (http://127.0.0.1:8000) that
  // this platform's Dify-based orchestration doesn't use at all -- it never
  // calls upload_server.py's real /api/dify/start, so without this branch the
  // paused Dify run never actually continues.
  const handleConfirmAndResume = async (isApproved: boolean) => {
    if (isApproved && (isCbomPreview || isRfqPreview || isGerberPreview || isAlternatesReview)) {
      setResumeError(null);
      // Disable the button and show the spinner immediately -- the resume
      // fetch below blocks until the entire resumed Dify run finishes, which
      // can take a while, and without this the click looks like it did
      // nothing.
      setIsSubmitting(true);

      if (isRfqPreview) {
        // apply_alternatives left rfq_process_stage sitting at its own
        // position (hitl=1 never advances it) -- unlike Standard_BOM_Flow's
        // resolve_final_selection, nothing else advances past it once the
        // user is done reviewing, so this must happen before resuming or the
        // Dify run would just re-halt at the same step.
        try {
          const approveResponse = await authFetch(
            `${PYTHON_BRIDGE}/api/bom/rfq-preview/${encodeURIComponent(hitlContextData.rfqId)}/approve`,
            hitlContextData.rfqId,
            { method: 'POST' },
          );
          if (!approveResponse.ok) {
            throw new Error(`Failed to approve BOM preview (status ${approveResponse.status})`);
          }
        } catch (err) {
          setResumeError(err instanceof Error ? err.message : 'Failed to approve BOM preview');
          setIsSubmitting(false);
          return;
        }
      }

      if (isGerberPreview) {
        // Same reasoning as isRfqPreview above -- extract_features's own
        // hitl=1 never advances rfq_process_stage on its own, so this must
        // happen before resuming or the run would just re-halt at the same
        // step.
        try {
          const approveResponse = await authFetch(
            `${PYTHON_BRIDGE}/api/bom/gerber-preview/${encodeURIComponent(hitlContextData.rfqId)}/approve`,
            hitlContextData.rfqId,
            { method: 'POST' },
          );
          if (!approveResponse.ok) {
            throw new Error(`Failed to approve Gerber preview (status ${approveResponse.status})`);
          }
        } catch (err) {
          setResumeError(err instanceof Error ? err.message : 'Failed to approve Gerber preview');
          setIsSubmitting(false);
          return;
        }
      }

      try {
        const resumeResponse = await authFetch(`${RFQ_UPLOAD_BRIDGE}/api/dify/start/${encodeURIComponent(hitlContextData.rfqId)}`, hitlContextData.rfqId);
        if (!resumeResponse.ok) {
          throw new Error(`Failed to resume pipeline (status ${resumeResponse.status})`);
        }
      } catch (err) {
        setResumeError(err instanceof Error ? err.message : 'Failed to resume pipeline');
        setIsSubmitting(false);
        return;
      }

      if (isGerberPreview) {
        // Resuming runs into distributor__enrich_bom next, NOT an export
        // step -- unlike isRfqPreview/isCbomPreview (which sit right before
        // export and so check for a finished export file below), there is
        // nothing export-related to check for here. Whatever halts next
        // (detect_alternates, or nothing) arrives via its own hitl:request
        // SSE event, same mechanism isAlternatesReview below relies on.
        setIsSubmitting(false);
        return;
      }

      if (isAlternatesReview) {
        // Deliberately do NOT call submitAction here. Resuming runs straight
        // into apply_alternatives, which ALWAYS halts again almost
        // immediately (its own unconditional hitl=1, stage 7 rfqBomPreview)
        // -- a fast, local-only DB operation with no external API calls, so
        // its own hitl:request can arrive within a second. That event
        // naturally replaces this modal's content via React state (helped
        // by App.tsx's key={rfqId-type-stage} remount), no explicit clear
        // needed. submitAction() broadcasts hitl:clear -- a blanket "hide
        // whatever's shown" signal with no awareness of which review session
        // it was meant for. It raced against the new hitl:request: landing
        // AFTER the new preview had already replaced hitlContext, it wiped
        // that brand-new stage-7 preview out again a moment after it
        // appeared ("pops up for a second and disappears").
        setIsSubmitting(false);
        return;
      }

      // The resume call above only resolves once the whole Dify run
      // (report generation + export) has finished, so the workbook is
      // already on disk by now -- fetch its name to show a download link.
      // Not fatal if this specific rfq_id's run didn't reach export_reports
      // for some reason (e.g. it stopped at an earlier HITL gate) -- just
      // fall through to the normal close below rather than surfacing an
      // error for something that isn't actually a failure of this action.
      try {
        const exportResponse = await authFetch(`${PYTHON_BRIDGE}/api/bom/export/${encodeURIComponent(hitlContextData.rfqId)}`, hitlContextData.rfqId);
        if (exportResponse.ok) {
          const exportJson = (await exportResponse.json()) as { filename: string; generated_at: string };
          setExportInfo({ filename: exportJson.filename, generatedAt: exportJson.generated_at });
          // Deliberately do NOT call submitAction here -- doing so clears
          // hitlContext (via the daemon's hitl:clear broadcast), which
          // unmounts this whole component, including the download button
          // we just populated, before the user ever gets to see or click
          // it. Stay on this screen; the "Continue to Quote Readiness"
          // button (shown once exportInfo is set) is what actually calls
          // submitAction, as a deliberate action taken after downloading
          // rather than an automatic side effect of resuming.
          setIsSubmitting(false);
          return;
        }
      } catch {
        // Non-fatal -- no download link shown, close normally below.
      }
    }
    await submitAction(isApproved);
  };

  // Once the alternates fetch above confirms zero groups to review, there is
  // nothing a human could do here that "Clear & Resume Pipeline" wouldn't
  // already do on its own (unresolvedAlternateCpns is trivially 0 for an
  // empty alternates array) -- so resolve it automatically instead of
  // leaving the user staring at an empty screen. Scoped to isAlternatesReview
  // only (not the broader isAlternatesLike), matching handleConfirmAndResume's
  // own real-resume branch above -- 'pricingSources' is a separate, unrelated
  // feature this doesn't touch. Ref-guarded so this fires at most once per
  // mount, even though alternateRows.length staying 0 across re-renders would
  // otherwise re-run this effect harmlessly (calling handleConfirmAndResume
  // twice is not itself dangerous, but firing it exactly once is cleaner).
  const autoSkippedEmptyAlternatesRef = useRef(false);
  useEffect(() => {
    if (!isAlternatesReview) { return; }
    if (alternatesLoading) { return; }
    if (alternateRows.length > 0) { return; }
    if (autoSkippedEmptyAlternatesRef.current) { return; }
    autoSkippedEmptyAlternatesRef.current = true;
    void handleConfirmAndResume(true);
    // handleConfirmAndResume is a plain (non-memoized) function recreated
    // every render; including it below would re-fire this effect on every
    // render. Same established pattern as App.tsx's own mount-restore effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAlternatesReview, alternatesLoading, alternateRows.length]);

  const handleDownloadExport = useCallback(() => {
    // Finalize Price only ever downloads the CBOM sheet on its own -- the
    // full 16-report bundle is a separate download, available from the
    // Quote Readiness stage instead (App.tsx). For RFQ_Flow (isRfqPreview),
    // this same endpoint falls back to distributor__export_enriched_bom's
    // Distributor_Verification_Output file (the consolidated, per-part
    // pricing view -- RFQ_Flow's own analog of "the CBOM sheet"), so this
    // one handler now backs both flows' "consolidated BOM" button.
    void authDownload(`${PYTHON_BRIDGE}/api/bom/export-cbom/${encodeURIComponent(hitlContextData.rfqId)}/download`, hitlContextData.rfqId);
  }, [hitlContextData.rfqId]);

  // RFQ_Flow's "final quote" download -- distributor__export_quote_summary's
  // own workbook (the "Quote" + "Final Structured BoM" sheets), via a
  // dedicated endpoint rather than /api/bom/export/{rfqId}/download (which
  // returns "whichever export happens to be newest" -- the right choice for
  // App.tsx's single catch-all download button, but not for a button
  // explicitly labeled "Download Final Quote," which must always mean this
  // specific file, not implicitly whatever ran most recently).
  const handleDownloadRfqQuoteExport = useCallback(() => {
    void authDownload(`${PYTHON_BRIDGE}/api/bom/export-quote/${encodeURIComponent(hitlContextData.rfqId)}/download`, hitlContextData.rfqId);
  }, [hitlContextData.rfqId]);

  // The first real (server-rendered) Gerber export -- distinct from
  // downloadGerberChecklistExcel's client-side quick dump above, though both
  // read the same persisted provenance='operator' signal for highlighting.
  const handleDownloadGerberReport = useCallback(() => {
    void authDownload(`${PYTHON_BRIDGE}/api/bom/gerber-preview/${encodeURIComponent(hitlContextData.rfqId)}/export/download`, hitlContextData.rfqId);
  }, [hitlContextData.rfqId]);

  const handleCellValueChanged = useCallback((event: CellValueChangedEvent) => {
    // Every other grid's rows carry a bom_item_id UUID; the Gerber checklist
    // grid's rows don't (they're not BOM line items) -- `field` (e.g.
    // "mask_colour") is that grid's own natural unique row identifier.
    const rowKey = (isGerberPreview ? event.data.field : event.data.bom_item_id) as string;
    setPendingEdits((prev) => ({ ...prev, [rowKey]: { ...event.data } }));
    setOriginalRowValues((prev) => {
      if (rowKey in prev) { return prev; }
      const field = event.colDef.field as string;
      return { ...prev, [rowKey]: { ...event.data, [field]: event.oldValue } };
    });
    // Sticky, additive-only -- see touchedFields' own comment. Only
    // consumed by rfqBomPreview/gerberPreview's cellStyle, but harmless to
    // populate for every grid since nothing else reads it.
    setTouchedFields((prev) => {
      const next = new Set(prev[rowKey] ?? []);
      next.add(event.colDef.field as string);
      return { ...prev, [rowKey]: next };
    });
  }, [isGerberPreview]);

  const handleUndoAll = useCallback(() => {
    gridRef.current?.api.applyTransaction({ update: Object.values(originalRowValues) });
    setPendingEdits({});
    setOriginalRowValues({});
    // Only clears the UNSAVED portion of highlighting -- already-persisted
    // highlights come from _edited_fields/provenance in the loaded row data
    // (a separate check), untouched by this.
    setTouchedFields({});
  }, [originalRowValues]);

  const handleSaveChanges = async () => {
    const rows = Object.values(pendingEdits);
    if (rows.length === 0) { return; }

    setIsSaving(true);
    setSaveError(null);

    // RFQ_Flow's finalized BOM preview persists to processed_bom_items via
    // its own endpoint; the Gerber checklist (field-keyed, not
    // bom_item_id-keyed) has its own endpoint too -- everything else
    // (cbomPreview's final_* columns) keeps using the original cbom.duckdb
    // batch-update endpoint.
    const batchUpdateUrl = isGerberPreview
      ? `${PYTHON_BRIDGE}/api/bom/batch-update-gerber-checklist/${hitlContextData.rfqId}`
      : isRfqPreview
      ? `${PYTHON_BRIDGE}/api/bom/batch-update-rfq/${hitlContextData.rfqId}`
      : `${PYTHON_BRIDGE}/api/bom/batch-update/${hitlContextData.rfqId}`;

    try {
      const response = await authFetch(
        batchUpdateUrl,
        hitlContextData.rfqId,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(rows),
        }
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error((errData as { detail?: string }).detail ?? `Server error ${response.status}`);
      }

      // Locally fold the just-saved touched fields into the loaded row data's
      // OWN persisted-highlight markers, in the SAME tick pendingEdits/
      // touchedFields get cleared -- without this there'd be one render
      // where neither the unsaved check (just cleared) nor the persisted
      // check (still the stale pre-save _edited_fields/provenance from the
      // last GET) is true, i.e. a visible flash where the cell briefly
      // un-highlights before a save is even confirmed on screen.
      if (isRfqPreview) {
        setRfqPreviewRows((prev) =>
          prev.map((row) => {
            const rowKey = row.bom_item_id as string;
            const newlyTouched = touchedFields[rowKey];
            if (!newlyTouched || newlyTouched.size === 0) { return row; }
            const existing = Array.isArray(row._edited_fields) ? (row._edited_fields as string[]) : [];
            const merged = Array.from(new Set([...existing, ...newlyTouched]));
            return { ...row, _edited_fields: merged };
          }),
        );
      } else if (isGerberPreview) {
        setGerberChecklist((prev) =>
          prev.map((row) => {
            const rowKey = row.field as string;
            if (!touchedFields[rowKey]?.size) { return row; }
            return { ...row, provenance: 'operator' };
          }),
        );
      }

      setPendingEdits({});
      setOriginalRowValues({});
      setTouchedFields({});
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setIsSaving(false);
    }
  };

  // gerberPreview's own quick-download, via exceljs so the manually-edited
  // Value cells (provenance === 'operator', the same persisted signal the
  // grid itself and the real Gerber Report export both read) come out
  // highlighted -- xlsx (used by the plain branch below) cannot write cell
  // fills at all. Uses the SAME column set/order as gerberChecklistColumnDefs
  // (category/label/value/present/provenance/confidence/note -- `field` stays
  // hidden there too).
  const downloadGerberChecklistExcel = useCallback(async () => {
    if (gerberChecklist.length === 0) { return; }
    const columns: { key: string; header: string }[] = [
      { key: 'category', header: 'Category' },
      { key: 'label', header: 'Field' },
      { key: 'value', header: 'Value' },
      { key: 'present', header: 'Stated in Pack?' },
      { key: 'provenance', header: 'Source' },
      { key: 'confidence', header: 'Confidence' },
      { key: 'note', header: 'Note' },
    ];

    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet('Gerber Checklist');
    sheet.columns = columns.map((c) => ({ header: c.header, key: c.key, width: 22 }));

    gerberChecklist.forEach((row) => {
      const excelRow = sheet.addRow(columns.reduce((acc, c) => ({ ...acc, [c.key]: row[c.key] as unknown }), {}));
      if (row.provenance === 'operator') {
        excelRow.getCell('value').fill = {
          type: 'pattern',
          pattern: 'solid',
          // MUST match mcp-tools/shared/highlight_style.py's
          // MANUAL_EDIT_FILL_ARGB and this file's own MANUAL_EDIT_FILL.
          fgColor: { argb: 'FFFFF9C4' },
        };
      }
    });

    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `gerber-checklist-${hitlContextData.rfqId}.xlsx`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [gerberChecklist, hitlContextData.rfqId]);

  const handleDownloadExcel = useCallback(() => {
    if (isGerberPreview) {
      void downloadGerberChecklistExcel();
      return;
    }

    const exportRows = isAlternatesLike
      ? alternateRows.map(({ suppliers, ...rest }) => ({
          ...rest,
          suppliers: suppliers
            .map((s) => `${s.supplier} $${s.price} MOQ${s.moq} ${s.lead_time} qty${s.stock}`)
            .join('; '),
        }))
      : isCbomPreview
      ? cbomRows.map(({ bom_item_id: _bomItemId, cbom_item_id: _cbomItemId, ...rest }) => rest)
      : isRfqPreview
      ? rfqPreviewRows.map(({ bom_item_id: _bomItemId, ...rest }) => rest)
      : isPriceSourceReview
      ? conflictSourceRows
      : rowData.map(({ bom_item_id: _bomItemId, ...rest }) => rest);

    if (exportRows.length === 0) { return; }

    const worksheet = utils.json_to_sheet(exportRows);
    const workbook = utils.book_new();
    utils.book_append_sheet(workbook, worksheet, 'BOM');
    writeFile(workbook, `bom-${hitlContextData.rfqId}-${hitlContextData.type}.xlsx`);
  }, [hitlContextData, rowData, alternateRows, isAlternatesLike, isCbomPreview, cbomRows, isRfqPreview, rfqPreviewRows, isGerberPreview, downloadGerberChecklistExcel, isPriceSourceReview, conflictSourceRows]);

  const exportRowCount = isAlternatesLike
    ? alternateRows.length
    : isCbomPreview
    ? cbomRows.length
    : isRfqPreview
    ? rfqPreviewRows.length
    : isGerberPreview
    ? gerberChecklist.length
    : isPriceSourceReview
    ? conflictSourceRows.length
    : rowData.length;

  const pendingCount = Object.keys(pendingEdits).length;

  const columnDefs = useMemo<ColDef[]>(() => [
    { field: 'bom_item_id', hide: true, editable: false },
    { field: 'item_num', headerName: '#', width: 70, pinned: 'left', sort: 'asc', editable: false },
    {
      field: 'cpn',
      headerName: 'CPN',
      width: 110,
      pinned: 'left',
      filter: true,
      // Missing CPN is the most common intake defect — flag the cell amber
      cellStyle: (params) =>
        params.value === null || params.value === undefined || params.value === ''
          ? { backgroundColor: 'rgba(245,158,11,0.12)', borderLeft: '2px solid rgba(245,158,11,0.5)' }
          : null,
    },
    {
      field: 'mpn',
      headerName: 'MPN',
      width: 130,
      pinned: 'left',
      filter: true,
      cellStyle: (params) =>
        duplicateMpns.has(String(params.value ?? ''))
          ? { backgroundColor: 'rgba(239,68,68,0.12)', borderLeft: '2px solid rgba(239,68,68,0.5)' }
          : null,
    },
    { field: 'mfr', headerName: 'Manufacturer', width: 120 },
    { field: 'description', headerName: 'Description', minWidth: 200, flex: 1 },
    { field: 'bom_qty', headerName: 'BOM Qty', type: 'numericColumn', width: 100 },
    {
      field: 'required_qty',
      headerName: 'Req Qty',
      type: 'numericColumn',
      width: 100,
      cellStyle: (params) =>
        params.data && params.data.bom_qty !== params.data.required_qty
          ? { backgroundColor: 'rgba(245,158,11,0.12)' }
          : null,
    },
    { field: 'uom', headerName: 'UOM', width: 80 },
  ], [duplicateMpns]);

  // CBOM (stage 7 "priceDecision" — costed BOM preview) columns are generated
  // dynamically from the preview endpoint's row shape rather than hardcoded,
  // same reasoning as before. Only final_* fields are reviewer-editable —
  // everything else (fg, cpn, description, etc.) is context and stays
  // read-only. fg is grouped (rowGroup + hidden) so the grid displays the
  // costed BOM FG-wise, same as the Excel reports.
  const cbomColumnDefs = useMemo<ColDef[]>(() => {
    if (!isCbomPreview || cbomRows.length === 0) { return []; }
    return Object.keys(cbomRows[0])
      .filter((key) => key !== 'cbom_item_id')
      .map((key) => {
        const base: ColDef = {
          field: key,
          headerName: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
          minWidth: 120,
          flex: 1,
          sortable: true,
          filter: true,
          editable: key.startsWith('final_'),
          hide: key === 'bom_item_id',
          // Same display-only rounding as rfqPreviewColumnDefs -- final_price_conv
          // etc. carry full float precision from cbom_db.cbom.
          valueFormatter: (params) =>
            typeof params.value === 'number' && !Number.isInteger(params.value)
              ? params.value.toFixed(2)
              : String(params.value ?? ''),
        };
        return key === 'fg' ? { ...base, rowGroup: true, hide: true } : base;
      });
  }, [isCbomPreview, cbomRows]);

  // RFQ_Flow's stage-7 preview counterpart to cbomColumnDefs' final_*
  // allowlist above -- mirrors the backend's RFQ_EDITABLE_FIELDS in
  // duck_db_api.py exactly (both the raw intake fields, for a data-entry
  // fix caught this late, and the enrichment-stage distributor-selection
  // fields). best_* columns stay read-only -- they're a live recomputed
  // display value, not a real column that PUT /api/bom/batch-update-rfq
  // can persist.
  const rfqPreviewColumnDefs = useMemo<ColDef[]>(() => {
    if (rfqPreviewRows.length === 0) { return []; }
    return Object.keys(rfqPreviewRows[0])
      .filter((key) => key !== 'bom_item_id' && key !== '_edited_fields')
      .map((key) => {
        const base: ColDef = {
          field: key,
          headerName: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
          minWidth: 120,
          flex: 1,
          sortable: true,
          filter: true,
          editable: RFQ_EDITABLE_FIELDS.includes(key),
          // bom_qty/required_qty/selected_unit_price etc. carry full float
          // precision from processed_bom_items (e.g. 1950.720000000) --
          // display-only rounding, doesn't touch the underlying/edited value.
          valueFormatter: (params) =>
            typeof params.value === 'number' && !Number.isInteger(params.value)
              ? params.value.toFixed(2)
              : String(params.value ?? ''),
          // Cell-level "ever manually edited" highlight -- unsaved
          // (touchedFields) OR persisted (_edited_fields from the last GET,
          // folded back in by handleSaveChanges right after a save so
          // there's no flash between the two).
          cellStyle: (params) => {
            const rowKey = params.data?.bom_item_id as string | undefined;
            const persisted = Array.isArray(params.data?._edited_fields)
              ? (params.data._edited_fields as string[]).includes(key)
              : false;
            const unsaved = rowKey ? touchedFields[rowKey]?.has(key) : false;
            return persisted || unsaved ? MANUAL_EDIT_CELL_STYLE : null;
          },
        };
        return base;
      });
  }, [rfqPreviewRows, touchedFields]);

  // Fixed column set (not dynamic from row keys, unlike rfqPreviewColumnDefs
  // above) -- gerber_checklist's shape is known upfront and a controlled
  // column order/label reads far better than category/label/value/etc in
  // whatever order the SQL SELECT happened to return them. `value` is the
  // one editable column -- see duck_db_api.py's _coerce_checklist_value():
  // whatever string a reviewer types gets re-split into value_text/
  // value_num/value_bool server-side, so a single plain-text cell editor is
  // enough here, no per-row conditional editor needed.
  const gerberChecklistColumnDefs = useMemo<ColDef[]>(() => [
    { field: 'field', hide: true, editable: false },
    { field: 'category', headerName: 'Category', width: 130, editable: false },
    { field: 'label', headerName: 'Field', minWidth: 180, flex: 1, editable: false },
    {
      field: 'value',
      headerName: 'Value',
      minWidth: 150,
      flex: 1,
      editable: true,
      // Highlight only the Value cell (never the whole row) -- unsaved
      // (touchedFields) OR persisted (provenance === 'operator', set by
      // batch_update_gerber_checklist / folded in locally right after a
      // save to avoid a flash -- see handleSaveChanges).
      cellStyle: (params) => {
        const rowKey = params.data?.field as string | undefined;
        const persisted = params.data?.provenance === 'operator';
        const unsaved = rowKey ? touchedFields[rowKey]?.has('value') : false;
        return persisted || unsaved ? MANUAL_EDIT_CELL_STYLE : null;
      },
    },
    {
      field: 'present',
      headerName: 'Stated in Pack?',
      width: 130,
      editable: false,
      cellStyle: (params) =>
        params.value ? null : { backgroundColor: 'rgba(245,158,11,0.12)' },
    },
    { field: 'provenance', headerName: 'Source', width: 110, editable: false },
    {
      field: 'confidence',
      headerName: 'Confidence',
      width: 110,
      editable: false,
      valueFormatter: (params) => (typeof params.value === 'number' ? `${Math.round(params.value * 100)}%` : ''),
    },
    { field: 'note', headerName: 'Note', minWidth: 200, flex: 1, editable: false },
  ], [touchedFields]);

  return (
    <div className="srim-theme-shell flex flex-col h-full w-full p-4 font-sans">

      {hitlContextData.type === 'preview' && (
        <BomQualityStrip rows={rowData} active={qualityFilter} onSelect={setQualityFilter} />
      )}

      <div className="flex-1 min-h-0 w-full mb-4 bg-background/75 rounded-md border border-border/70 overflow-hidden">
        {hitlContextData.type === 'preview' && (
          <div className="w-full h-full">
            <AgGridReact
              theme={myTheme}
              ref={gridRef}
              rowData={rowData}
              getRowId={(params) => params.data.bom_item_id as string}
              columnDefs={columnDefs}
              isExternalFilterPresent={isExternalFilterPresent}
              doesExternalFilterPass={doesExternalFilterPass}
              defaultColDef={{
                sortable: true,
                filter: true,
                resizable: true,
                floatingFilter: true,
                editable: true,
              }}
              getRowStyle={(params) =>
                (params.data?.bom_item_id as string) in pendingEdits ? PENDING_EDIT_ROW_STYLE : undefined
              }
              onCellValueChanged={handleCellValueChanged}
              pagination={true}
              paginationPageSize={25}
              enableCellTextSelection={true}
            />
          </div>
        )}

        {isAlternatesLike && (
          alternatesLoading ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground">
              <SpinnerGap className="h-4 w-4 animate-spin mr-2" />
              Loading alternate manufacturers...
            </div>
          ) : alternateRows.length === 0 ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground p-6 text-center">
              {isAlternatesReview ? (
                <>
                  <SpinnerGap className="h-4 w-4 animate-spin mr-2" />
                  No alternates found for this RFQ — continuing automatically...
                </>
              ) : (
                'No alternates found for this RFQ.'
              )}
            </div>
          ) : (
            <div className="w-full h-full">
              <AgGridReact
                theme={myTheme}
                rowData={alternateRows}
                columnDefs={alternateColumnDefs}
                getRowHeight={getAlternateRowHeight}
                defaultColDef={{
                  sortable: true,
                  filter: true,
                  resizable: true,
                }}
                pagination={true}
                paginationPageSize={25}
                enableCellTextSelection={true}
              />
            </div>
          )
        )}

        {isCbomPreview && (
          cbomLoading ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground">
              <SpinnerGap className="h-4 w-4 animate-spin mr-2" />
              Loading costed BOM...
            </div>
          ) : cbomRows.length === 0 ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground p-6 text-center">
              No costed BOM data available for this RFQ yet.
            </div>
          ) : (
            <div className="w-full h-full">
              <AgGridReact
                theme={myTheme}
                ref={gridRef}
                rowData={cbomRows}
                getRowId={(params) => params.data.bom_item_id as string}
                columnDefs={cbomColumnDefs}
                autoGroupColumnDef={{ headerName: 'FG', minWidth: 200, pinned: 'left' }}
                groupDefaultExpanded={1}
                defaultColDef={{
                  sortable: true,
                  filter: true,
                  resizable: true,
                }}
                getRowStyle={(params) =>
                  (params.data?.bom_item_id as string) in pendingEdits ? PENDING_EDIT_ROW_STYLE : undefined
                }
                onCellValueChanged={handleCellValueChanged}
                pagination={true}
                paginationPageSize={25}
                enableCellTextSelection={true}
              />
            </div>
          )
        )}

        {isRfqPreview && (
          rfqPreviewLoading ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground">
              <SpinnerGap className="h-4 w-4 animate-spin mr-2" />
              Loading finalized BOM...
            </div>
          ) : rfqPreviewRows.length === 0 ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground p-6 text-center">
              No finalized BOM data available for this RFQ yet.
            </div>
          ) : (
            <div className="w-full h-full">
              <AgGridReact
                theme={myTheme}
                ref={gridRef}
                rowData={rfqPreviewRows}
                getRowId={(params) => params.data.bom_item_id as string}
                columnDefs={rfqPreviewColumnDefs}
                defaultColDef={{
                  sortable: true,
                  filter: true,
                  resizable: true,
                }}
                onCellValueChanged={handleCellValueChanged}
                pagination={true}
                paginationPageSize={25}
                enableCellTextSelection={true}
              />
            </div>
          )
        )}

        {isGerberPreview && (
          gerberLoading ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground">
              <SpinnerGap className="h-4 w-4 animate-spin mr-2" />
              Loading Gerber feature extraction...
            </div>
          ) : gerberError ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-red-400 p-6 text-center">
              {gerberError}
            </div>
          ) : gerberChecklist.length === 0 ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground p-6 text-center">
              No Gerber feature data available for this RFQ yet.
            </div>
          ) : (
            <div className="w-full h-full flex flex-col">
              {gerberGeometry && (
                <div className="mb-3 grid grid-cols-3 sm:grid-cols-6 gap-2 shrink-0">
                  {[
                    ['Board Size', `${gerberGeometry.width_mm ?? '?'} x ${gerberGeometry.height_mm ?? '?'} mm`],
                    ['Layers', String(gerberGeometry.layer_count ?? '?')],
                    ['Drill Holes', String(gerberGeometry.total_holes ?? '?')],
                    ['Confidence', `${Math.round((Number(gerberGeometry.confidence) || 0) * 100)}%`],
                    ['Board Name', String(gerberGeometry.board_name ?? '—')],
                    ['Outline', gerberGeometry.is_outline_estimated ? 'Estimated' : 'Exact'],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-md border border-border/70 bg-background/60 px-2.5 py-1.5">
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
                      <p className="text-xs font-semibold text-foreground truncate">{value}</p>
                    </div>
                  ))}
                </div>
              )}
              {Array.isArray(gerberGeometry?.warnings) && gerberGeometry.warnings.length > 0 && (
                <p className="mb-3 text-xs text-black bg-amber-950/30 border border-amber-900/40 rounded px-3 py-2 shrink-0">
                  {(gerberGeometry.warnings as string[]).join(' · ')}
                </p>
              )}
              <div className="flex-1 min-h-0">
                <AgGridReact
                  theme={myTheme}
                  ref={gridRef}
                  rowData={gerberChecklist}
                  getRowId={(params) => params.data.field as string}
                  columnDefs={gerberChecklistColumnDefs}
                  defaultColDef={{
                    sortable: true,
                    filter: true,
                    resizable: true,
                  }}
                  onCellValueChanged={handleCellValueChanged}
                  pagination={true}
                  paginationPageSize={34}
                  enableCellTextSelection={true}
                />
              </div>
            </div>
          )
        )}

        {isPriceSourceReview && !showFinalPreview && (
          conflictsLoading ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground">
              <SpinnerGap className="h-4 w-4 animate-spin mr-2" />
              Loading pricing source conflicts...
            </div>
          ) : conflictSourceRows.length === 0 ? (
            <div className="flex items-center justify-center h-full text-xs font-mono text-muted-foreground p-6 text-center">
              No pricing source conflicts pending for this RFQ.
            </div>
          ) : (
            <div className="w-full h-full flex flex-col">
              <div className="flex-1 min-h-0">
                <AgGridReact
                  theme={myTheme}
                  rowData={conflictSourceRows}
                  columnDefs={conflictColumnDefs}
                  defaultColDef={{
                    sortable: true,
                    filter: true,
                    resizable: true,
                  }}
                  pagination={true}
                  paginationPageSize={25}
                  enableCellTextSelection={true}
                />
              </div>
              {conflictsNextCursor && (
                <div className="pt-2 flex justify-center shrink-0">
                  <button
                    type="button"
                    onClick={() => { void handleLoadMoreConflicts(); }}
                    disabled={conflictsLoadingMore}
                    className="px-3 py-1.5 text-[11px] font-mono rounded-md border border-border/70 hover:border-primary/40 text-muted-foreground hover:text-foreground transition disabled:opacity-50"
                  >
                    {conflictsLoadingMore ? 'Loading…' : 'Load More Conflicts'}
                  </button>
                </div>
              )}
            </div>
          )
        )}

        {hitlContextData.type === 'yesNo' && (
          <div className="flex flex-col items-center justify-center h-full gap-3 p-6 text-center">
            <p className="max-w-md text-sm text-foreground/90">
              {hitlContextData.message ?? 'Please confirm to proceed with the pipeline.'}
            </p>
          </div>
        )}
      </div>

      {saveError && (
        <p className="mb-3 text-xs text-red-400 bg-red-950/40 border border-red-900/50 rounded px-3 py-2">
          {saveError}
        </p>
      )}

      {alternatesError && (
        <p className="mb-3 text-xs text-red-400 bg-red-950/40 border border-red-900/50 rounded px-3 py-2">
          {alternatesError}
        </p>
      )}

      {cbomError && (
        <p className="mb-3 text-xs text-red-400 bg-red-950/40 border border-red-900/50 rounded px-3 py-2">
          {cbomError}
        </p>
      )}

      {rfqPreviewError && (
        <p className="mb-3 text-xs text-red-400 bg-red-950/40 border border-red-900/50 rounded px-3 py-2">
          {rfqPreviewError}
        </p>
      )}

      {conflictsError && (
        <p className="mb-3 text-xs text-red-400 bg-red-950/40 border border-red-900/50 rounded px-3 py-2">
          {conflictsError}
        </p>
      )}

      {resumeError && (
        <p className="mb-3 text-xs text-red-400 bg-red-950/40 border border-red-900/50 rounded px-3 py-2">
          {resumeError}
        </p>
      )}

      {isAlternatesReview && unresolvedAlternateCpns > 0 && (
        <p className="mb-3 text-xs text-amber-400 bg-amber-950/30 border border-amber-900/40 rounded px-3 py-2">
          {unresolvedAlternateCpns} CPN{unresolvedAlternateCpns === 1 ? '' : 's'} still need{unresolvedAlternateCpns === 1 ? 's' : ''} a selection before you can resume. A candidate with no price shown from any distributor is still a valid, selectable option.
        </p>
      )}

      <div className="flex justify-between items-center gap-3 pt-2 border-t border-border/10">
        <div className="flex gap-3">
          {hitlContextData.type !== 'yesNo' && !isCbomPreview && !isRfqPreview && (
            <button
              type="button"
              onClick={handleDownloadExcel}
              disabled={exportRowCount === 0}
              className="px-4 py-2 bg-emerald-600/90 hover:bg-emerald-500 text-xs font-semibold rounded-md transition disabled:opacity-50 flex items-center gap-1.5"
            >
              <FileXls className="h-3.5 w-3.5" />
              Download Excel
            </button>
          )}
          {isGerberPreview && gerberChecklist.length > 0 && (
            <button
              type="button"
              onClick={handleDownloadGerberReport}
              className="px-4 py-2 bg-blue-600/90 hover:bg-blue-500 text-xs font-semibold rounded-md transition flex items-center gap-1.5"
              title="Board geometry summary + full checklist, manually-edited fields highlighted"
            >
              <FileXls className="h-3.5 w-3.5" />
              Download Gerber Report
            </button>
          )}
          {exportInfo && !isRfqPreview && (
            <button
              type="button"
              onClick={handleDownloadExport}
              className="px-4 py-2 bg-blue-600/90 hover:bg-blue-500 text-xs font-semibold rounded-md transition flex items-center gap-1.5"
              title={`Generated ${new Date(exportInfo.generatedAt).toLocaleString()}`}
            >
              <FileXls className="h-3.5 w-3.5" />
              CBOM Export
            </button>
          )}
          {exportInfo && isRfqPreview && (
            <>
              <button
                type="button"
                onClick={handleDownloadExport}
                className="px-4 py-2 bg-blue-600/90 hover:bg-blue-500 text-xs font-semibold rounded-md transition flex items-center gap-1.5"
                title="Consolidated, per-part BOM with every distributor's price plus the single selected best price"
              >
                <FileXls className="h-3.5 w-3.5" />
                Download Consolidated BOM
              </button>
              <button
                type="button"
                onClick={handleDownloadRfqQuoteExport}
                className="px-4 py-2 bg-blue-600/90 hover:bg-blue-500 text-xs font-semibold rounded-md transition flex items-center gap-1.5"
                title={`Generated ${new Date(exportInfo.generatedAt).toLocaleString()}`}
              >
                <FileXls className="h-3.5 w-3.5" />
                Download Final Quote
              </button>
            </>
          )}
          {pendingCount > 0 && (
            <>
              <button
                type="button"
                onClick={handleUndoAll}
                disabled={isSaving}
                className="px-4 py-2 border border-border/70 hover:border-primary/40 text-muted-foreground hover:text-foreground text-xs font-semibold rounded-md transition disabled:opacity-50 flex items-center gap-1.5"
              >
                <ArrowCounterClockwise className="h-3.5 w-3.5" />
                Undo
              </button>
              <button
                type="button"
                onClick={() => { void handleSaveChanges(); }}
                disabled={isSaving}
                className="px-4 py-2 bg-yellow-500 hover:bg-yellow-400 text-xs font-semibold rounded-md text-black transition disabled:opacity-50 flex items-center gap-1.5"
              >
                {isSaving ? (
                  <>
                    <SpinnerGap className="h-3.5 w-3.5 animate-spin" />
                    Saving...
                  </>
                ) : (
                  `Save Changes (${pendingCount})`
                )}
              </button>
            </>
          )}
        </div>
        <div className="flex gap-3">
          {exportInfo ? (
            // The run already finished (that's how we got the export) --
            // "Halt"/"Resume" no longer apply. Closing now is a deliberate
            // action the user takes after seeing/downloading the report,
            // not an automatic side effect of clicking resume.
            <button
              type="button"
              onClick={() => { onNavigateToStage?.('quoteReadiness'); void submitAction(true); }}
              disabled={isSubmitting}
              className="px-4 py-2 bg-green-500 hover:bg-green-600 text-xs font-semibold rounded-md text-black transition disabled:opacity-50"
            >
              Continue to Quote Readiness
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={() => { void submitAction(false); }}
                disabled={isSubmitting}
                className="px-4 py-2 bg-red-600/90 hover:bg-red-700 text-xs font-semibold rounded-md transition disabled:opacity-50"
              >
                {hitlContextData.type === 'yesNo' ? 'No' : 'Halt & Reject Run'}
              </button>
              <button
                onClick={() => { void handleConfirmAndResume(true); }}
                disabled={isSubmitting || (isAlternatesReview && unresolvedAlternateCpns > 0)}
                title={isAlternatesReview && unresolvedAlternateCpns > 0 ? `${unresolvedAlternateCpns} CPN(s) still need a selection` : undefined}
                className="px-4 py-2 bg-green-500 hover:bg-green-600 text-xs font-semibold rounded-md text-black transition disabled:opacity-50 flex items-center gap-1.5"
              >
                {hitlContextData.type === 'yesNo' ? (
                  'Yes'
                ) : isCbomPreview ? (
                  isSubmitting ? (
                    <>
                      <SpinnerGap className="h-3.5 w-3.5 animate-spin" />
                      Preparing CBOM Export…
                    </>
                  ) : (
                    'Approve CBOM'
                  )
                ) : isRfqPreview ? (
                  isSubmitting ? (
                    <>
                      <SpinnerGap className="h-3.5 w-3.5 animate-spin" />
                      Preparing Export…
                    </>
                  ) : (
                    'Approve & Continue to Export'
                  )
                ) : isGerberPreview ? (
                  isSubmitting ? (
                    <>
                      <SpinnerGap className="h-3.5 w-3.5 animate-spin" />
                      Advancing…
                    </>
                  ) : (
                    'Approve Gerber Data & Continue'
                  )
                ) : isAlternatesReview && unresolvedAlternateCpns > 0 ? (
                  `Select ${unresolvedAlternateCpns} More`
                ) : (
                  'Clear & Resume Pipeline'
                )}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
