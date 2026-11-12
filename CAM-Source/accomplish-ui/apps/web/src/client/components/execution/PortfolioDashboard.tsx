import { useEffect, useState } from 'react';
import { PYTHON_BRIDGE_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';

/**
 * All RFQs at a glance (what 3.3's Superset "Executive Sourcing Overview" showed, rebuilt with every figure defined and read from each RFQ's
 * newest exported workbook: GET /api/analytics/portfolio). The definition of each figure is its tooltip. Totals add only RFQs in the most
 * common currency; the others are counted apart.
 */
interface Row {
  rfq_id: string; customer?: string | null; project?: string | null; generated?: string; volume?: string | null; currency?: string | null;
  cost_per_set?: number | null; ext_vol_cost?: number | null; buy?: number | null; final_buy?: number | null; buy_variance?: number | null;
  excess_cost?: number | null; rows?: number | null; priced?: number | null; critical?: number | null; go_no_go?: string | null;
  lead_time?: Record<string, number>; error?: string;
}
interface Portfolio {
  rfqs: Row[];
  totals: { total_rfqs: number; currency: string | null; counted_rfqs: number; cash_rfqs?: number; other_currency_rfqs: number; costing_pct: number | null; final_buy: number; buy: number; buy_variance: number | null; excess_cost: number; critical_exceptions: number; lead_time: Record<string, number>; errors: number; without_stored_values?: number };
  definitions: Record<string, string>;
  repair?: { running: boolean; done: number; total: number; failed: string[] };
}

const fmt = (n: number | null | undefined, d = 0) => (n === null || n === undefined ? 'n/a' : n.toLocaleString(undefined, { maximumFractionDigits: d }));
const pct = (n: number | null | undefined) => (n === null || n === undefined ? 'n/a' : `${(n * 100).toFixed(1)}%`);
const CARD = 'rounded-lg border border-border bg-card p-4';
const BUCKETS = ['up to 8 weeks', '9 to 16 weeks', '17 to 26 weeks', 'over 26 weeks', 'no lead time'];
const BUCKET_CLASS = ['bg-primary/30', 'bg-primary/55', 'bg-primary/80', 'bg-primary', 'bg-amber-500'];

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

  if (error) return <div className="p-6"><p role="alert" className="text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="p-6 text-sm text-muted-foreground" role="status">Reading every RFQ's report…</div>;

  const t = data.totals;
  const d = data.definitions;
  const ok = data.rfqs.filter((r) => !r.error);
  const counted = ok.filter((r) => r.currency === t.currency);
  const top = [...counted].sort((a, b) => (b.final_buy ?? 0) - (a.final_buy ?? 0)).slice(0, 12);
  const maxBuy = Math.max(1, ...top.flatMap((r) => [r.buy ?? 0, r.final_buy ?? 0]));
  const unit = t.currency ? ` ${t.currency}` : '';

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-5">
      <div>
        <h2 className="text-base font-semibold text-foreground">All RFQs</h2>
        <p className="text-xs text-muted-foreground">Each RFQ's newest report, last volume. {t.other_currency_rfqs > 0 ? `${t.other_currency_rfqs} RFQ${t.other_currency_rfqs === 1 ? '' : 's'} in another currency ${t.other_currency_rfqs === 1 ? 'is' : 'are'} listed but not added in. ` : ''}Hover a figure for its definition.</p>
      </div>

      {(t.without_stored_values ?? 0) > 0 && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-foreground">
          <span>
            {data.repair?.running
              ? `Storing the values in older reports: ${data.repair.done} of ${data.repair.total} done. The figures below fill in as each one finishes.`
              : `${t.without_stored_values} older report${t.without_stored_values === 1 ? ' was' : 's were'} exported before formula values were stored, so ${t.without_stored_values === 1 ? 'its' : 'their'} cash-flow and check cells read n/a and are not in the totals.`}
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
        <Tile label="RFQs with a report" value={fmt(t.total_rfqs)} hint={d.total_rfqs} note={t.errors ? `${t.errors} report${t.errors === 1 ? '' : 's'} could not be read` : undefined} />
        <Tile label="Costing" value={pct(t.costing_pct)} hint={d.costing_pct} tone={t.costing_pct !== null && t.costing_pct < 0.5 ? 'warn' : undefined} />
        <Tile label={`Final buy${unit}`} value={fmt(t.final_buy)} hint={d.final_buy} note={`over ${t.cash_rfqs ?? t.counted_rfqs} RFQ${(t.cash_rfqs ?? t.counted_rfqs) === 1 ? '' : 's'} with stored values`} />
        <Tile label="Buy variance" value={pct(t.buy_variance)} hint={d.buy_variance} note="final buy above plain need" />
        <Tile label={`Excess cost${unit}`} value={fmt(t.excess_cost)} hint={d.excess_cost} />
        <Tile label="Critical exceptions" value={fmt(t.critical_exceptions)} hint={d.critical_exceptions} tone={t.critical_exceptions ? 'warn' : 'ok'} note="rows in Missing Notes" />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <section className={CARD} aria-label="Plain need against final buy by RFQ">
          <h3 className="text-sm font-semibold text-foreground">Buy value against final buy, by RFQ</h3>
          {top.length ? (
            <ul className="mt-3 space-y-2.5">
              {top.map((r) => (
                <li key={r.rfq_id}>
                  <p className="truncate text-xs font-medium text-foreground">{r.rfq_id} <span className="font-normal text-muted-foreground">{r.project ?? ''}</span></p>
                  {([['Buy', r.buy, 'bg-brand/60'], ['Final', r.final_buy, 'bg-primary']] as const).map(([label, value, cls]) => (
                    <div key={label} className="mt-0.5 flex items-center gap-2">
                      <span className="w-10 shrink-0 text-[11px] text-muted-foreground">{label}</span>
                      <div className="h-2.5 flex-1 rounded-sm bg-muted"><div className={`h-2.5 rounded-sm ${cls}`} style={{ width: `${((value ?? 0) / maxBuy) * 100}%` }} /></div>
                      <span className="w-20 shrink-0 text-right text-xs tabular-nums text-foreground">{fmt(value)}</span>
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          ) : <p className="py-6 text-center text-xs text-muted-foreground">No RFQ has a readable cash-flow tab yet.</p>}
        </section>

        <section className={CARD} aria-label="Lead-time exposure by RFQ" title={d.lead_time}>
          <h3 className="text-sm font-semibold text-foreground">Lead-time exposure, parts per RFQ</h3>
          <ul className="mt-3 space-y-2">
            {counted.slice(0, 12).map((r) => {
              const total = BUCKETS.reduce((s, b) => s + (r.lead_time?.[b] ?? 0), 0) || 1;
              return (
                <li key={r.rfq_id} className="flex items-center gap-2">
                  <span className="w-24 shrink-0 truncate text-xs text-foreground">{r.rfq_id}</span>
                  <div className="flex h-3 flex-1 overflow-hidden rounded-sm bg-muted" role="img" aria-label={BUCKETS.map((b) => `${b}: ${r.lead_time?.[b] ?? 0}`).join(', ')}>
                    {BUCKETS.map((b, i) => <div key={b} className={BUCKET_CLASS[i]} style={{ width: `${((r.lead_time?.[b] ?? 0) / total) * 100}%` }} />)}
                  </div>
                  <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{total === 1 && !BUCKETS.some((b) => r.lead_time?.[b]) ? 0 : total}</span>
                </li>
              );
            })}
          </ul>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
            {BUCKETS.map((b, i) => (
              <li key={b} className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><span className={`h-2.5 w-2.5 rounded-sm ${BUCKET_CLASS[i]}`} aria-hidden />{b} <span className="tabular-nums text-foreground">{fmt(t.lead_time[b])}</span></li>
            ))}
          </ul>
        </section>
      </div>

      <section className={`${CARD} overflow-x-auto`} aria-label="Every RFQ">
        <h3 className="text-sm font-semibold text-foreground">Every RFQ</h3>
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
            {data.rfqs.map((r) => (
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
          </tbody>
        </table>
      </section>
    </div>
  );
}
