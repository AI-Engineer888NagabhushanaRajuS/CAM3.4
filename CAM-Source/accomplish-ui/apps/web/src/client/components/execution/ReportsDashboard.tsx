import { useCallback, useEffect, useState } from 'react';
import { ArrowsClockwise, CheckCircle, DownloadSimple, WarningCircle } from '@phosphor-icons/react';
import { PYTHON_BRIDGE_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { downloadReports } from '../rfq/OpenDirectives';
import { SupersetDashboardPanel } from './SupersetDashboardPanel';
import { PortfolioDashboard } from './PortfolioDashboard';

/**
 * Reports & Analytics for one finished RFQ. Every figure is read from the delivered workbook (GET /api/rfq/{id}/analytics), so the screen
 * can never show a number the report does not hold. The Formula Engine check (GET/POST /api/rfq/{id}/verify-workbook) says how many of
 * the workbook's formulas the engine re-computed to the same value. Superset is optional: it needs its own service, so it is offered, not forced.
 */
interface Analytics {
  workbook: string;
  summary: { volumes: string[]; fgs: Array<Record<string, number | string | null>>; totals: Record<string, number | null>; ext_vol_conv_price?: Record<string, number | null>; moq_cost?: Record<string, number | null>; moq_pct?: Record<string, number | null> } | null;
  price_control: Array<{ label: string; ext_price: number | null; ext_vol_cost: number | null; pct: number | null }> | null;
  lead_time: Array<{ weeks: string | null; count: number | null; pct: number | null }> | null;
  cashflow: Array<Array<{ type: string; buy: number | null; final_buy: number | null }>> | null;
  excess_cost: Record<string, number | null> | null;
  uncosted_parts: number | null;
  currency: string | null;
  cbom: { rows: number; priced: number } | null;
  manifest: { error_cells?: number | null; go_no_go?: string | null } | null;
}
interface TabCheck { formulas: number; exact: number; different: number; no_stored_value: number; engine_error: number }
interface EngineResult { label: string; complete: boolean; error: string | null; totals: Partial<TabCheck>; sheets: Record<string, TabCheck>; diagnostics: string[]; corrected?: number; corrected_at_export?: number; elapsed_seconds?: number }
type Verify = { status: 'none' | 'running' } | { status: 'done'; result: EngineResult };

const fmt = (n: number | null | undefined, d = 2) => (n === null || n === undefined ? 'n/a' : n.toLocaleString(undefined, { maximumFractionDigits: d }));
const pct = (n: number | null | undefined) => (n === null || n === undefined ? 'n/a' : `${(n * 100).toFixed(1)}%`);
const BAR = ['bg-primary', 'bg-brand/60', 'bg-amber-500', 'bg-emerald-500'];
const CARD = 'rounded-lg border border-border bg-card p-4';

function Tile({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: 'warn' | 'ok' }) {
  return (
    <div className={CARD}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone === 'warn' ? 'text-amber-600' : tone === 'ok' ? 'text-emerald-600' : 'text-foreground'}`}>{value}</p>
      {note && <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

function Empty({ what }: { what: string }) {
  return <p className="py-6 text-center text-xs text-muted-foreground">{what} is not in this workbook.</p>;
}

export function ReportsDashboard({ rfqId, ready, onOpenRfq }: { rfqId: string; ready: boolean; onOpenRfq: (rfqId: string) => void }) {
  const [view, setView] = useState<'rfq' | 'all'>('rfq');
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [verify, setVerify] = useState<Verify>({ status: 'none' });
  const [showSuperset, setShowSuperset] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const base = `${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}`;

  // This screen opens as soon as the export step starts, before the workbook is finished (the engine check stores its values after the export):
  // it reads only once the export step has completed, and a 404 after that means "not yet", so it asks again until the file is there.
  useEffect(() => {
    let alive = true;
    let timer = 0;
    setData(null);
    setError(null);
    setWaiting(!ready);
    if (!ready) { return undefined; }
    const load = () => {
      authFetch(`${base}/analytics`, rfqId)
        .then(async (r) => {
          if (r.status === 404) { if (alive) { setWaiting(true); timer = window.setTimeout(load, 5000); } return; }
          if (!r.ok) throw new Error(`The numbers could not be read (status ${r.status}).`);
          const d = (await r.json()) as Analytics;
          if (alive) { setWaiting(false); setData(d); }
        })
        .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : 'The numbers could not be read.'); });
    };
    load();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [base, rfqId, ready, reloadKey]);

  const poll = useCallback(async () => {
    const r = await authFetch(`${base}/verify-workbook`, rfqId);
    if (r.ok) setVerify((await r.json()) as Verify);
  }, [base, rfqId]);

  useEffect(() => { if (data) { void poll().catch(() => undefined); } }, [data, poll]);
  // A confirmed edit in the assistant writes a new workbook version: the numbers are read again (see the listener below).
  useEffect(() => {
    const onChanged = (e: Event) => { if ((e as CustomEvent<{ rfqId?: string }>).detail?.rfqId === rfqId) { setReloadKey((k) => k + 1); } };
    window.addEventListener('cam:workbook-changed', onChanged);
    return () => window.removeEventListener('cam:workbook-changed', onChanged);
  }, [rfqId]);
  useEffect(() => {
    if (verify.status !== 'running') return undefined;
    const t = window.setInterval(() => { void poll().catch(() => undefined); }, 4000);
    return () => window.clearInterval(t);
  }, [verify.status, poll]);

  const rerun = async () => {
    setVerify({ status: 'running' });
    await authFetch(`${base}/verify-workbook`, rfqId, { method: 'POST' }).catch(() => undefined);
    void poll().catch(() => undefined);
  };

  const tabs = (
    <div role="tablist" aria-label="Report scope" className="inline-flex w-fit rounded-md border border-border p-0.5 text-xs">
      {([['rfq', 'This RFQ'], ['all', 'All RFQs']] as const).map(([id, label]) => (
        <button key={id} type="button" role="tab" aria-selected={view === id} onClick={() => setView(id)} className={`rounded px-3 py-1 font-semibold ${view === id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{label}</button>
      ))}
    </div>
  );
  if (view === 'all') return <div className="flex h-full min-h-0 flex-col"><div className="p-5 pb-0">{tabs}</div><div className="min-h-0 flex-1"><PortfolioDashboard onOpenRfq={(id) => { setView('rfq'); onOpenRfq(id); }} /></div></div>;
  if (error) return <div className="p-5">{tabs}<p role="alert" className="mt-4 text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="p-5">{tabs}<p className="mt-4 text-sm text-muted-foreground" role="status">{waiting ? 'The report is still being built. This screen fills in by itself when the workbook is exported.' : 'Reading the report…'}</p></div>;

  const s = data.summary;
  const v1 = s?.volumes[0];
  const goodRun = data.manifest?.go_no_go === 'GO';
  const maxFg = Math.max(1, ...(s?.fgs.flatMap((f) => (s?.volumes ?? []).map((v) => Number(f[v]) || 0)) ?? [1]));
  const maxLt = Math.max(1, ...(data.lead_time?.map((l) => l.count ?? 0) ?? [1]));
  const cash = data.cashflow?.[0];
  const maxCash = Math.max(1, ...(cash?.map((c) => c.final_buy ?? 0) ?? [1]));

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-5">
      {tabs}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">Reports &amp; Analytics</h2>
          <p className="truncate text-xs text-muted-foreground">{rfqId} · {data.workbook}</p>
        </div>
        <button type="button" onClick={() => void downloadReports(rfqId)} className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border px-3 py-1 text-xs font-semibold text-foreground hover:bg-muted">
          <DownloadSimple className="h-3.5 w-3.5" aria-hidden /> Download all reports
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        <Tile label={`Cost per set${v1 ? ` (${v1})` : ''}${data.currency ? `, ${data.currency}` : ''}`} value={fmt(s?.totals[v1 ?? ''])} note={s ? `${s.fgs.length} assemblies, ${s.volumes.length} volumes` : 'no summary tab'} />
        <Tile label={`Extended volume cost${v1 ? ` (${v1})` : ''}${data.currency ? `, ${data.currency}` : ''}`} value={fmt(s?.ext_vol_conv_price?.[v1 ?? ''], 0)} note={s?.moq_pct?.[v1 ?? ''] != null ? `${pct(s.moq_pct[v1 ?? ''])} of it is MOQ` : undefined} />
        <Tile label="Priced rows" value={data.cbom ? `${data.cbom.priced} of ${data.cbom.rows}` : 'n/a'} note={data.cbom && data.cbom.rows ? pct(data.cbom.priced / data.cbom.rows) : undefined} tone={data.cbom && data.cbom.priced === 0 ? 'warn' : undefined} />
        <Tile label="Uncosted parts" value={fmt(data.uncosted_parts, 0)} note="listed in Missing Notes" tone={data.uncosted_parts ? 'warn' : 'ok'} />
        <Tile label={`MOQ cost${v1 ? ` (${v1})` : ''}`} value={fmt(s?.moq_cost?.[v1 ?? ''], 0)} note={data.excess_cost?.[v1 ?? ''] != null ? `excess ${fmt(data.excess_cost[v1 ?? ''], 0)}` : undefined} />
        <Tile label="Workbook check" value={data.manifest?.go_no_go ?? 'n/a'} note={data.manifest?.error_cells != null ? `${data.manifest.error_cells} error cells in all tabs` : undefined} tone={goodRun ? 'ok' : data.manifest?.go_no_go ? 'warn' : undefined} />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <section className={CARD} aria-label="Cost per set by assembly">
          <h3 className="text-sm font-semibold text-foreground">Cost per set by assembly</h3>
          {s && s.fgs.length ? (
            <ul className="mt-3 space-y-3">
              {s.fgs.map((f) => (
                <li key={String(f.assembly)}>
                  <p className="truncate text-xs font-medium text-foreground">{String(f.assembly)}</p>
                  {s.volumes.map((vol, i) => (
                    <div key={vol} className="mt-1 flex items-center gap-2">
                      <span className="w-10 shrink-0 text-[11px] text-muted-foreground">{vol}</span>
                      <div className="h-3 flex-1 rounded-sm bg-muted"><div className={`h-3 rounded-sm ${BAR[i % BAR.length]}`} style={{ width: `${((Number(f[vol]) || 0) / maxFg) * 100}%` }} /></div>
                      <span className="w-16 shrink-0 text-right text-xs tabular-nums text-foreground">{fmt(Number(f[vol]))}</span>
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          ) : <Empty what="The summary" />}
        </section>

        <section className={CARD} aria-label="Price control">
          <h3 className="text-sm font-semibold text-foreground">Who set the price</h3>
          {data.price_control ? (
            <>
              <div className="mt-3 flex h-4 overflow-hidden rounded-sm bg-muted" role="img" aria-label={data.price_control.map((p) => `${p.label} ${pct(p.pct)}`).join(', ')}>
                {data.price_control.map((p, i) => <div key={p.label} className={BAR[i % BAR.length]} style={{ width: `${(p.pct ?? 0) * 100}%` }} />)}
              </div>
              <ul className="mt-3 space-y-1.5">
                {data.price_control.map((p, i) => (
                  <li key={p.label} className="flex items-center gap-2 text-xs">
                    <span className={`h-2.5 w-2.5 shrink-0 rounded-sm ${BAR[i % BAR.length]}`} aria-hidden />
                    <span className="flex-1 text-foreground">{p.label}</span>
                    <span className="tabular-nums text-muted-foreground">{fmt(p.ext_vol_cost, 0)}</span>
                    <span className="w-14 text-right tabular-nums text-foreground">{pct(p.pct)}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : <Empty what="Price control" />}
        </section>

        <section className={CARD} aria-label="Lead time">
          <h3 className="text-sm font-semibold text-foreground">Lead time, parts per week count</h3>
          {data.lead_time ? (
            <div className="mt-3 flex h-36 items-end gap-1" role="img" aria-label="Parts by lead time in weeks">
              {data.lead_time.map((l) => (
                <div key={l.weeks ?? 'none'} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1" title={`${l.weeks ?? 'no lead time'} weeks: ${l.count} parts`}>
                  <span className="text-[10px] tabular-nums text-muted-foreground">{l.count}</span>
                  <div className={`w-full rounded-t-sm ${l.weeks === null ? 'bg-amber-500' : 'bg-primary'}`} style={{ height: Math.max(2, ((l.count ?? 0) / maxLt) * 92) }} />
                  <span className="max-w-full truncate text-[10px] text-muted-foreground">{l.weeks ?? 'none'}</span>
                </div>
              ))}
            </div>
          ) : <Empty what="Lead time" />}
        </section>

        <section className={CARD} aria-label="Cash out by payment term">
          <h3 className="text-sm font-semibold text-foreground">Final buy by payment term{s ? ` (${s.volumes[0]})` : ''}</h3>
          {cash ? (
            <ul className="mt-3 space-y-2">
              {cash.map((c) => (
                <li key={c.type} className="flex items-center gap-2">
                  <span className="w-24 shrink-0 truncate text-xs text-foreground">{c.type}</span>
                  <div className="h-3 flex-1 rounded-sm bg-muted"><div className="h-3 rounded-sm bg-primary" style={{ width: `${((c.final_buy ?? 0) / maxCash) * 100}%` }} /></div>
                  <span className="w-20 shrink-0 text-right text-xs tabular-nums text-foreground">{fmt(c.final_buy, 0)}</span>
                </li>
              ))}
            </ul>
          ) : <Empty what="Batchwise cashflow" />}
        </section>
      </div>

      <section className={CARD} aria-label="Formula Engine check">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Formula Engine check</h3>
            <p className="text-xs text-muted-foreground">The engine re-computes every formula of this workbook and compares it with the stored value. An independent check, not client approval.</p>
          </div>
          <button type="button" onClick={() => void rerun()} disabled={verify.status === 'running'} className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border px-3 py-1 text-xs font-semibold text-foreground hover:bg-muted disabled:opacity-50">
            <ArrowsClockwise className={`h-3.5 w-3.5 ${verify.status === 'running' ? 'animate-spin' : ''}`} aria-hidden /> {verify.status === 'running' ? 'Checking…' : verify.status === 'done' ? 'Run again' : 'Run the check'}
          </button>
        </div>
        {verify.status === 'done' && (
          <div className="mt-3">
            {verify.result.error ? (
              <p role="alert" className="flex items-center gap-1.5 text-xs text-destructive"><WarningCircle className="h-4 w-4" aria-hidden /> {verify.result.error}</p>
            ) : (
              <>
                <p className="flex items-center gap-1.5 text-sm text-foreground">
                  {verify.result.totals.different === 0 && verify.result.complete ? <CheckCircle className="h-4 w-4 text-emerald-600" weight="fill" aria-hidden /> : <WarningCircle className="h-4 w-4 text-amber-600" weight="fill" aria-hidden />}
                  <span className="tabular-nums">{fmt(verify.result.totals.exact, 0)} of {fmt(verify.result.totals.formulas, 0)} formulas agree</span>
                  {(verify.result.corrected ?? verify.result.corrected_at_export) ? <span className="text-xs text-muted-foreground">· {fmt(verify.result.corrected ?? verify.result.corrected_at_export, 0)} stored values were replaced with the engine's</span> : null}
                  {!verify.result.complete && <span className="text-xs text-amber-700">· stopped before the end (time budget)</span>}
                </p>
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="text-left text-muted-foreground"><th className="py-1 pr-3 font-medium">Tab</th><th className="py-1 pr-3 text-right font-medium">Formulas</th><th className="py-1 pr-3 text-right font-medium">Agree</th><th className="py-1 pr-3 text-right font-medium">Differ</th><th className="py-1 text-right font-medium">No stored value</th></tr></thead>
                    <tbody>
                      {Object.entries(verify.result.sheets).map(([tab, t]) => (
                        <tr key={tab} className="border-t border-border/60">
                          <td className="py-1 pr-3 text-foreground">{tab}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{fmt(t.formulas, 0)}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{fmt(t.exact, 0)}</td>
                          <td className={`py-1 pr-3 text-right tabular-nums ${t.different ? 'font-semibold text-amber-700' : ''}`}>{fmt(t.different, 0)}</td>
                          <td className="py-1 text-right tabular-nums">{fmt(t.no_stored_value, 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {verify.result.diagnostics.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Engine notes: {verify.result.diagnostics.slice(0, 3).join('; ')}</p>}
                <p className="mt-2 text-[11px] text-muted-foreground">{verify.result.label}</p>
              </>
            )}
          </div>
        )}
        {verify.status === 'none' && <p className="mt-2 text-xs text-muted-foreground">No check has been run on this workbook yet.</p>}
      </section>

      <section className={CARD} aria-label="Superset">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">Superset dashboards need the Superset service (not part of this install by default).</p>
          <button type="button" onClick={() => setShowSuperset((v) => !v)} className="inline-flex min-h-8 items-center rounded-md border border-border px-3 py-1 text-xs font-semibold text-foreground hover:bg-muted">{showSuperset ? 'Hide' : 'Try the Superset view'}</button>
        </div>
        {showSuperset && <div className="mt-3 h-[480px]"><SupersetDashboardPanel rfqId={rfqId} /></div>}
      </section>
    </div>
  );
}
