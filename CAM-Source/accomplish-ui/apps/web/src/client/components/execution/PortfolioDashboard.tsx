import { useEffect, useMemo, useState } from 'react';
import { DownloadSimple, X } from '@phosphor-icons/react';
import { PYTHON_BRIDGE_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { PortfolioCharts } from './PortfolioCharts';
import { NO_FILTERS, applyFilters, summarise, toCsv, type PortfolioFilters, type PortfolioRow } from './portfolioSummary';

/**
 * All RFQs at a glance (what 3.3's Superset "Executive Sourcing Overview" showed, rebuilt with every figure defined and read from each RFQ's
 * newest exported workbook: GET /api/analytics/portfolio). The definition of each figure is its tooltip. Filters narrow every tile, chart and
 * table together; with no filter the figures are the server's own. Totals add only RFQs in the most common currency; the others are counted apart.
 */
interface Portfolio {
  rfqs: PortfolioRow[];
  totals: { currency: string | null; other_currency_rfqs: number; without_stored_values?: number; total_rfqs: number; costing_pct: number | null; final_buy: number; buy: number; buy_variance: number | null; excess_cost: number; critical_exceptions: number; lead_time: Record<string, number>; commodity_excess?: Record<string, number>; errors: number; counted_rfqs: number; cash_rfqs?: number };
  definitions: Record<string, string>;
  repair?: { running: boolean; done: number; total: number; failed: string[] };
}

const fmt = (n: number | null | undefined, d = 0) => (n === null || n === undefined ? 'n/a' : n.toLocaleString(undefined, { maximumFractionDigits: d }));
const pct = (n: number | null | undefined) => (n === null || n === undefined ? 'n/a' : `${(n * 100).toFixed(1)}%`);
const CARD = 'rounded-lg border border-border bg-card p-4';
const BUCKETS = ['up to 8 weeks', '9 to 16 weeks', '17 to 26 weeks', 'over 26 weeks', 'no lead time'];
const SELECT = 'rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground';

function Tile({ label, value, note, hint, tone }: { label: string; value: string; note?: string; hint: string; tone?: 'warn' | 'ok' }) {
  return (
    <div className={CARD} title={hint}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone === 'warn' ? 'text-amber-600' : tone === 'ok' ? 'text-emerald-600' : 'text-foreground'}`}>{value}</p>
      {note && <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

export function PortfolioDashboard({ onOpenRfq }: { onOpenRfq: (rfqId: string) => void }) {
  const [data, setData] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<PortfolioFilters>(NO_FILTERS);

  const load = () => authFetch(`${PYTHON_BRIDGE_URL}/api/analytics/portfolio`, 'portfolio')
    .then(async (r) => { if (!r.ok) throw new Error(`The portfolio could not be read (status ${r.status}).`); return r.json() as Promise<Portfolio>; });

  useEffect(() => {
    let alive = true;
    load().then((d) => { if (alive) setData(d); }).catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : 'The portfolio could not be read.'); });
    return () => { alive = false; };
  }, []);

  // While older reports are being brought up to date, read the portfolio again every few seconds so the figures appear as they are stored.
  const repairing = data?.repair?.running === true;
  useEffect(() => {
    if (!repairing) return undefined;
    const t = window.setInterval(() => { load().then(setData).catch(() => undefined); }, 6000);
    return () => window.clearInterval(t);
  }, [repairing]);

  const storeValues = async () => {
    await authFetch(`${PYTHON_BRIDGE_URL}/api/analytics/portfolio/store-values`, 'portfolio', { method: 'POST' }).catch(() => undefined);
    load().then(setData).catch(() => undefined);
  };

  const rfqs = data?.rfqs ?? [];
  const visible = useMemo(() => applyFilters(rfqs, filters), [rfqs, filters]);
  const mainCurrency = data?.totals.currency ?? null;
  const s = useMemo(() => summarise(visible, mainCurrency, BUCKETS), [visible, mainCurrency]);
  const customers = useMemo(() => [...new Set(rfqs.map((r) => r.customer).filter((v): v is string => !!v))].sort(), [rfqs]);
  const projects = useMemo(() => [...new Set(rfqs.map((r) => r.project).filter((v): v is string => !!v))].sort(), [rfqs]);
  const goValues = useMemo(() => [...new Set(rfqs.map((r) => r.go_no_go).filter((v): v is string => !!v))].sort(), [rfqs]);

  if (error) return <div className="p-6"><p role="alert" className="text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="p-6 text-sm text-muted-foreground" role="status">Reading every RFQ's report…</div>;

  const d = data.definitions;
  const unit = mainCurrency ? ` ${mainCurrency}` : '';
  const filtered = filters.customer || filters.project || filters.go || filters.query.trim() !== '';
  const hasStored = (data.totals.without_stored_values ?? 0) > 0;

  const exportCsv = () => {
    const blob = new Blob([toCsv(visible)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cam-rfqs${filtered ? '-filtered' : ''}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-5">
      <div>
        <h2 className="text-base font-semibold text-foreground">All RFQs</h2>
        <p className="text-xs text-muted-foreground">Each RFQ's newest report, last volume. {s.otherCurrency > 0 ? `${s.otherCurrency} RFQ${s.otherCurrency === 1 ? '' : 's'} in another currency ${s.otherCurrency === 1 ? 'is' : 'are'} listed but not added in. ` : ''}Hover a figure for its definition.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3" role="search" aria-label="Filter RFQs">
        <input
          value={filters.query}
          onChange={(e) => setFilters({ ...filters, query: e.target.value })}
          placeholder="RFQ ID"
          aria-label="Filter by RFQ ID"
          className="w-36 rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground"
        />
        <select aria-label="Filter by customer" value={filters.customer} onChange={(e) => setFilters({ ...filters, customer: e.target.value })} className={SELECT}>
          <option value="">All customers</option>
          {customers.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select aria-label="Filter by project" value={filters.project} onChange={(e) => setFilters({ ...filters, project: e.target.value })} className={SELECT}>
          <option value="">All projects</option>
          {projects.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select aria-label="Filter by go or no-go" value={filters.go} onChange={(e) => setFilters({ ...filters, go: e.target.value })} className={SELECT}>
          <option value="">Any go / no-go</option>
          {goValues.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        {filtered && (
          <button type="button" onClick={() => setFilters(NO_FILTERS)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-muted-foreground hover:text-foreground">
            <X size={12} /> Clear
          </button>
        )}
        <span className="ml-auto text-xs tabular-nums text-muted-foreground" role="status">{s.total} of {rfqs.filter((r) => !r.error).length} RFQs</span>
        <button type="button" onClick={exportCsv} disabled={!visible.length} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-semibold text-foreground hover:bg-muted disabled:opacity-50">
          <DownloadSimple size={13} /> Export CSV
        </button>
      </div>

      {hasStored && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-foreground">
          <span>
            {data.repair?.running
              ? `Storing the values in older reports: ${data.repair.done} of ${data.repair.total} done. The figures below fill in as each one finishes.`
              : `${data.totals.without_stored_values} older report${data.totals.without_stored_values === 1 ? ' was' : 's were'} exported before formula values were stored, so ${data.totals.without_stored_values === 1 ? 'its' : 'their'} cash-flow and check cells read n/a and are not in the totals.`}
            {data.repair && !data.repair.running && data.repair.failed.length > 0 ? ` ${data.repair.failed.length} could not be updated.` : ''}
          </span>
          {!data.repair?.running && (
            <button type="button" onClick={() => void storeValues()} className="inline-flex min-h-8 items-center rounded-md border border-border bg-card px-3 py-1 font-semibold hover:bg-muted">
              Store the values now
            </button>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        <Tile label="RFQs with a report" value={fmt(s.total)} hint={d.total_rfqs} note={s.errors ? `${s.errors} report${s.errors === 1 ? '' : 's'} could not be read` : undefined} />
        <Tile label="Costing" value={pct(s.costingPct)} hint={d.costing_pct} tone={s.costingPct !== null && s.costingPct < 0.5 ? 'warn' : undefined} />
        <Tile label={`Final buy${unit}`} value={fmt(s.finalBuy)} hint={d.final_buy} note={`over ${s.cashRfqs} RFQ${s.cashRfqs === 1 ? '' : 's'} with stored values`} />
        <Tile label="Buy variance" value={pct(s.buyVariance)} hint={d.buy_variance} note="final buy above plain need" />
        <Tile label={`Excess cost${unit}`} value={fmt(s.excess)} hint={d.excess_cost} />
        <Tile label="Critical exceptions" value={fmt(s.critical)} hint={d.critical_exceptions} tone={s.critical ? 'warn' : 'ok'} note="rows in Missing Notes" />
      </div>

      <PortfolioCharts
        counted={s.counted}
        all={s.counted}
        currency={mainCurrency}
        commodityExcess={s.commodity}
        leadBuckets={BUCKETS}
        leadTotals={s.lead}
        definitions={d}
      />

      <section className={`${CARD} overflow-x-auto`} aria-label="Every RFQ">
        <h3 className="text-sm font-semibold text-foreground">{filtered ? 'RFQs matching the filter' : 'Every RFQ'}</h3>
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1 pr-3 font-medium">RFQ</th><th className="py-1 pr-3 font-medium">Customer / project</th>
              <th className="py-1 pr-3 text-right font-medium" title={d.volume_rule}>Cost per set</th><th className="py-1 pr-3 text-right font-medium">Final buy</th>
              <th className="py-1 pr-3 text-right font-medium">Variance</th><th className="py-1 pr-3 text-right font-medium">Priced</th>
              <th className="py-1 pr-3 text-right font-medium">Exceptions</th><th className="py-1 font-medium">Check</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.rfq_id} className="border-t border-border/60">
                <td className="py-1.5 pr-3"><button type="button" onClick={() => onOpenRfq(r.rfq_id)} className="font-semibold text-primary hover:underline">{r.rfq_id}</button></td>
                <td className="py-1.5 pr-3 text-muted-foreground">{[r.customer, r.project].filter(Boolean).join(' / ') || '—'}</td>
                {r.error ? <td colSpan={6} className="py-1.5 text-destructive">{r.error}</td> : (
                  <>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(r.cost_per_set, 2)} <span className="text-muted-foreground">{r.currency ?? ''}</span></td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(r.final_buy)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{pct(r.buy_variance)}</td>
                    <td className={`py-1.5 pr-3 text-right tabular-nums ${r.priced === 0 ? 'font-semibold text-amber-700' : ''}`}>{r.rows ? `${r.priced} of ${r.rows}` : 'n/a'}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{fmt(r.critical)}</td>
                    <td className={`py-1.5 ${r.go_no_go === 'GO' ? 'text-emerald-700' : 'font-semibold text-amber-700'}`}>{r.go_no_go ?? 'n/a'}</td>
                  </>
                )}
              </tr>
            ))}
            {!visible.length && (
              <tr><td colSpan={8} className="py-6 text-center text-muted-foreground">No RFQ matches the filter.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
