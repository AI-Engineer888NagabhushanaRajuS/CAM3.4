/**
 * The all-RFQs figures for whatever rows are visible (after the filters). Same definitions as the server's portfolio totals
 * (mcp-tools/shared/rfq_analytics.py: portfolio()), so with no filter applied the tiles match the server exactly, and with a filter they
 * show the same definitions over the RFQs that remain. Totals add only RFQs in the portfolio's main currency; the rest are counted apart.
 */

export interface PortfolioRow {
  rfq_id: string;
  customer?: string | null;
  project?: string | null;
  currency?: string | null;
  cost_per_set?: number | null;
  buy?: number | null;
  final_buy?: number | null;
  buy_variance?: number | null;
  excess_cost?: number | null;
  rows?: number | null;
  priced?: number | null;
  critical?: number | null;
  go_no_go?: string | null;
  lead_time?: Record<string, number>;
  commodity_excess?: Record<string, number> | null;
  error?: string;
}

export interface PortfolioFilters {
  customer: string;
  project: string;
  go: string;
  query: string;
}

export const NO_FILTERS: PortfolioFilters = { customer: '', project: '', go: '', query: '' };

export function applyFilters(rows: PortfolioRow[], f: PortfolioFilters): PortfolioRow[] {
  const q = f.query.trim().toLowerCase();
  return rows.filter((r) =>
    (!f.customer || r.customer === f.customer)
    && (!f.project || r.project === f.project)
    && (!f.go || r.go_no_go === f.go)
    && (!q || r.rfq_id.toLowerCase().includes(q)));
}

export interface PortfolioSummary {
  /** Readable RFQs among the visible rows, in any currency. */
  total: number;
  /** Visible RFQs in the main currency: the ones every total below adds up. */
  counted: PortfolioRow[];
  otherCurrency: number;
  cashRfqs: number;
  costingPct: number | null;
  buy: number;
  finalBuy: number;
  buyVariance: number | null;
  excess: number;
  critical: number;
  lead: Record<string, number>;
  commodity: Record<string, number>;
  errors: number;
}

export function summarise(rows: PortfolioRow[], currency: string | null, leadBuckets: string[]): PortfolioSummary {
  const readable = rows.filter((r) => !r.error);
  const counted = readable.filter((r) => r.currency === currency);
  const sum = (pick: (r: PortfolioRow) => number | null | undefined) => counted.reduce((s, r) => s + (pick(r) ?? 0), 0);
  const buy = sum((r) => r.buy);
  const finalBuy = sum((r) => r.final_buy);
  const rowsAll = sum((r) => r.rows);
  const priced = sum((r) => r.priced);
  const lead: Record<string, number> = {};
  for (const b of leadBuckets) lead[b] = counted.reduce((s, r) => s + (r.lead_time?.[b] ?? 0), 0);
  const commodity: Record<string, number> = {};
  for (const r of counted) {
    for (const [name, value] of Object.entries(r.commodity_excess ?? {})) commodity[name] = (commodity[name] ?? 0) + value;
  }
  return {
    total: readable.length,
    counted,
    otherCurrency: readable.length - counted.length,
    cashRfqs: counted.filter((r) => r.final_buy !== null && r.final_buy !== undefined).length,
    costingPct: rowsAll ? priced / rowsAll : null,
    buy,
    finalBuy,
    buyVariance: buy ? (finalBuy - buy) / buy : null,
    excess: sum((r) => r.excess_cost),
    critical: sum((r) => r.critical),
    lead,
    commodity,
    errors: rows.length - readable.length,
  };
}

const CSV_COLUMNS: [string, (r: PortfolioRow) => string | number | null | undefined][] = [
  ['RFQ', (r) => r.rfq_id],
  ['Customer', (r) => r.customer],
  ['Project', (r) => r.project],
  ['Currency', (r) => r.currency],
  ['Cost per set', (r) => r.cost_per_set],
  ['Baseline buy value', (r) => r.buy],
  ['Final buy value', (r) => r.final_buy],
  ['Buy variance', (r) => r.buy_variance],
  ['Excess cost', (r) => r.excess_cost],
  ['CBOM lines', (r) => r.rows],
  ['Priced lines', (r) => r.priced],
  ['Critical exceptions', (r) => r.critical],
  ['Go / no-go', (r) => r.go_no_go],
];

/** The visible rows as CSV, one line per RFQ, the figures as the workbook holds them (no rounding). */
export function toCsv(rows: PortfolioRow[]): string {
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = CSV_COLUMNS.map(([name]) => name).join(',');
  const body = rows.filter((r) => !r.error).map((r) => CSV_COLUMNS.map(([, get]) => esc(get(r))).join(','));
  return [head, ...body].join('\n');
}
