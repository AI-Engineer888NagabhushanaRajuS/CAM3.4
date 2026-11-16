import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { ArrowsInSimple, ArrowsOutSimple, DownloadSimple, Table as TableIcon } from '@phosphor-icons/react';
import type { PortfolioRow } from './portfolioSummary';

/**
 * The all-RFQs charts, rebuilt from the figures the portfolio endpoint reads out of each RFQ's newest workbook (GET /api/analytics/portfolio).
 * Every chart is an ECharts chart: hover for the exact figure, click a legend entry to hide a series, and the card's own controls change the
 * orientation, the order, how many rows show, the title and the donut style. Full screen, the data table and the PNG export work on every chart.
 * Nothing here computes a figure the workbook does not hold: each chart plots the values the endpoint returns.
 */

export type { PortfolioRow } from './portfolioSummary';

export interface PortfolioChartsProps {
  /** RFQs in the portfolio's main currency: the ones the totals add up. */
  counted: PortfolioRow[];
  /** Every readable RFQ (any currency): the costing donut counts lines, which do not depend on currency. */
  all: PortfolioRow[];
  currency: string | null;
  commodityExcess: Record<string, number>;
  leadBuckets: string[];
  leadTotals: Record<string, number>;
  definitions: Record<string, string>;
}

interface Config {
  title: string;
  horizontal: boolean;
  byValue: boolean;
  top: number;
  donut: boolean;
  /** The per-RFQ figure a metric chart plots (a key of PortfolioRow). */
  metric?: string;
}

/** The per-RFQ figures a metric chart can plot, with how to show them. */
export const METRICS: { key: keyof PortfolioRow; label: string; percent?: boolean; money?: boolean }[] = [
  { key: 'final_buy', label: 'Final buy value', money: true },
  { key: 'buy', label: 'Baseline buy value', money: true },
  { key: 'buy_variance', label: 'Buy variance', percent: true },
  { key: 'excess_cost', label: 'Excess cost', money: true },
  { key: 'cost_per_set', label: 'Cost per set', money: true },
  { key: 'critical', label: 'Critical exceptions' },
  { key: 'rows', label: 'CBOM lines' },
  { key: 'priced', label: 'Priced lines' },
];

interface Built {
  option: echarts.EChartsOption;
  columns: string[];
  table: (string | number)[][];
}

const COLORS = { baseline: '#22A8C9', final: '#474E7C', costed: '#22A8C9', notCosted: '#474E7C', commodity: '#3300AA' };
const LEAD_COLORS = ['#2A6B6B', '#4FA3A3', '#8FD0D0', '#2C8FB5', '#E8A23A'];
const TOP_OPTIONS = [5, 10, 20, 0];

const money = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
const compact = (n: number) => Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n);

function takeTop<T>(items: T[], top: number): T[] {
  return top > 0 ? items.slice(0, top) : items;
}

function buildBuy(rows: PortfolioRow[], cfg: Config, currency: string | null): Built {
  const items = rows.filter((r) => r.buy !== null && r.buy !== undefined || r.final_buy !== null && r.final_buy !== undefined);
  const ordered = cfg.byValue ? [...items].sort((a, b) => (b.final_buy ?? 0) - (a.final_buy ?? 0)) : items;
  const shown = takeTop(ordered, cfg.top);
  const cats = shown.map((r) => r.rfq_id);
  const unit = currency ? ` ${currency}` : '';
  const valueAxis = { type: 'value' as const, axisLabel: { formatter: (v: number) => compact(v) } };
  const catAxis = { type: 'category' as const, data: cats, axisLabel: { rotate: cfg.horizontal ? 0 : 35, width: 120, overflow: 'truncate' as const } };
  return {
    option: {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `${money(Number(v))}${unit}` },
      legend: { top: 0, icon: 'roundRect' },
      grid: { left: 12, right: 24, top: 40, bottom: 12, containLabel: true },
      xAxis: cfg.horizontal ? valueAxis : catAxis,
      yAxis: cfg.horizontal ? { ...catAxis, inverse: true } : valueAxis,
      series: [
        { name: 'Baseline buy value', type: 'bar', data: shown.map((r) => r.buy ?? 0), itemStyle: { color: COLORS.baseline }, label: { show: true, position: cfg.horizontal ? 'right' : 'top', formatter: (p: { value: unknown }) => compact(Number(p.value)) } },
        { name: 'Final buy value', type: 'bar', data: shown.map((r) => r.final_buy ?? 0), itemStyle: { color: COLORS.final }, label: { show: true, position: cfg.horizontal ? 'right' : 'top', formatter: (p: { value: unknown }) => compact(Number(p.value)) } },
      ],
    },
    columns: ['RFQ', 'Project', `Baseline buy value${unit}`, `Final buy value${unit}`],
    table: shown.map((r) => [r.rfq_id, r.project ?? '', r.buy ?? 0, r.final_buy ?? 0]),
  };
}

function buildLead(rows: PortfolioRow[], cfg: Config, buckets: string[]): Built {
  const withTotal = rows.map((r) => ({ r, total: buckets.reduce((s, b) => s + (r.lead_time?.[b] ?? 0), 0) })).filter((x) => x.total > 0);
  const ordered = cfg.byValue ? [...withTotal].sort((a, b) => b.total - a.total) : withTotal;
  const shown = takeTop(ordered, cfg.top);
  const cats = shown.map((x) => x.r.rfq_id);
  return {
    option: {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `${money(Number(v))} parts` },
      legend: { bottom: 0, icon: 'roundRect' },
      grid: { left: 12, right: 24, top: 16, bottom: 56, containLabel: true },
      xAxis: cfg.horizontal ? { type: 'value' } : { type: 'category', data: cats, axisLabel: { rotate: 35, width: 120, overflow: 'truncate' } },
      yAxis: cfg.horizontal ? { type: 'category', data: cats, inverse: true, axisLabel: { width: 120, overflow: 'truncate' } } : { type: 'value' },
      series: buckets.map((b, i) => ({
        name: b,
        type: 'bar',
        stack: 'lead',
        emphasis: { focus: 'series' },
        itemStyle: { color: LEAD_COLORS[i % LEAD_COLORS.length] },
        data: shown.map((x) => x.r.lead_time?.[b] ?? 0),
      })),
    },
    columns: ['RFQ', ...buckets, 'Total parts'],
    table: shown.map((x) => [x.r.rfq_id, ...buckets.map((b) => x.r.lead_time?.[b] ?? 0), x.total]),
  };
}

function buildCommodity(values: Record<string, number>, cfg: Config, currency: string | null): Built {
  const unit = currency ? ` ${currency}` : '';
  const sorted = Object.entries(values).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const shown = takeTop(sorted, cfg.top);
  const cats = shown.map(([name]) => name);
  const valueAxis = { type: 'value' as const, axisLabel: { formatter: (v: number) => compact(v) } };
  const catAxis = { type: 'category' as const, data: cats, axisLabel: { width: 140, overflow: 'truncate' as const } };
  return {
    option: {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `${money(Number(v))}${unit}` },
      legend: { top: 0, icon: 'roundRect' },
      grid: { left: 12, right: 32, top: 40, bottom: 12, containLabel: true },
      xAxis: cfg.horizontal ? valueAxis : catAxis,
      yAxis: cfg.horizontal ? { ...catAxis, inverse: true } : valueAxis,
      series: [{ name: 'Net excess cost', type: 'bar', data: shown.map(([, v]) => v), itemStyle: { color: COLORS.commodity }, label: { show: true, position: cfg.horizontal ? 'right' : 'top', formatter: (p: { value: unknown }) => compact(Number(p.value)) } }],
    },
    columns: ['Commodity', `Net excess cost${unit}`],
    table: shown.map(([name, v]) => [name, v]),
  };
}

function buildMetric(rows: PortfolioRow[], cfg: Config): Built {
  const metric = METRICS.find((m) => m.key === cfg.metric) ?? METRICS[0];
  const values = rows
    .map((r) => ({ id: r.rfq_id, value: r[metric.key] }))
    .filter((x): x is { id: string; value: number } => typeof x.value === 'number' && Number.isFinite(x.value));
  const ordered = cfg.byValue ? [...values].sort((a, b) => b.value - a.value) : values;
  const shown = takeTop(ordered, cfg.top);
  const cats = shown.map((x) => x.id);
  const show = (v: number) => (metric.percent ? `${(v * 100).toFixed(1)}%` : money(v));
  const axis = (v: number) => (metric.percent ? `${(v * 100).toFixed(0)}%` : compact(v));
  const valueAxis = { type: 'value' as const, axisLabel: { formatter: (v: number) => axis(v) } };
  const catAxis = { type: 'category' as const, data: cats, axisLabel: { rotate: cfg.horizontal ? 0 : 35, width: 120, overflow: 'truncate' as const } };
  return {
    option: {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => show(Number(v)) },
      legend: { top: 0, icon: 'roundRect' },
      grid: { left: 12, right: 32, top: 40, bottom: 12, containLabel: true },
      xAxis: cfg.horizontal ? valueAxis : catAxis,
      yAxis: cfg.horizontal ? { ...catAxis, inverse: true } : valueAxis,
      series: [{ name: metric.label, type: 'bar', data: shown.map((x) => x.value), itemStyle: { color: COLORS.final }, label: { show: true, position: cfg.horizontal ? 'right' : 'top', formatter: (p: { value: unknown }) => show(Number(p.value)) } }],
    },
    columns: ['RFQ', metric.label],
    table: shown.map((x) => [x.id, metric.percent ? `${(x.value * 100).toFixed(2)}%` : x.value]),
  };
}

function buildCosting(rows: PortfolioRow[], cfg: Config): Built {
  const priced = rows.reduce((s, r) => s + (r.priced ?? 0), 0);
  const all = rows.reduce((s, r) => s + (r.rows ?? 0), 0);
  const notCosted = Math.max(all - priced, 0);
  const pieData = [
    { name: 'Costed', value: priced, itemStyle: { color: COLORS.costed } },
    { name: 'Not costed', value: notCosted, itemStyle: { color: COLORS.notCosted } },
  ];
  return {
    option: {
      tooltip: { trigger: 'item', formatter: (p: { name: string; value: number; percent: number }) => `${p.name}: ${money(p.value)} lines (${p.percent}%)` },
      legend: { bottom: 0, icon: 'roundRect' },
      series: [{
        type: 'pie',
        radius: cfg.donut ? ['52%', '76%'] : ['0%', '76%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        label: { formatter: '{b}\n{d}%' },
        data: pieData,
      }],
      graphic: all ? [{ type: 'text', left: 'center', top: '43%', style: { text: `${money(all)}\nCBOM lines`, textAlign: 'center', fill: '#475569', fontSize: 14, fontWeight: 600 } }] : [],
    },
    columns: ['Status', 'CBOM lines'],
    table: [['Costed', priced], ['Not costed', notCosted], ['Total', all]],
  };
}

interface CardProps {
  id: string;
  defaults: Config;
  canOrient: boolean;
  canSort: boolean;
  canDonut: boolean;
  canMetric?: boolean;
  build: (cfg: Config) => Built;
  note: string;
}

function ChartCard({ id, defaults, canOrient, canSort, canDonut, canMetric = false, build, note }: CardProps) {
  const [cfg, setCfg] = useState<Config>(defaults);
  const [full, setFull] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const built = useMemo(() => build(cfg), [build, cfg]);

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const chart = echarts.init(hostRef.current, undefined, { renderer: 'canvas' });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(hostRef.current);
    return () => { ro.disconnect(); chart.dispose(); chartRef.current = null; };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(built.option, { notMerge: true });
  }, [built]);

  useEffect(() => {
    if (!full) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setFull(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [full]);

  // The chart resizes with its box; full screen changes the box, so ask ECharts to measure again on the next frame.
  useEffect(() => {
    const t = window.setTimeout(() => chartRef.current?.resize(), 60);
    return () => window.clearTimeout(t);
  }, [full]);

  const exportPng = () => {
    const url = chartRef.current?.getDataURL({ pixelRatio: 2, backgroundColor: '#ffffff' });
    if (!url) return;
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(cfg.title || id).replace(/[^\w\- ]+/g, '').trim() || id}.png`;
    a.click();
  };

  const select = (label: string, value: string | number, options: [string | number, string][], onChange: (v: string) => void) => (
    <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] text-foreground">
        {options.map(([v, l]) => <option key={String(v)} value={v}>{l}</option>)}
      </select>
    </label>
  );

  return (
    <section
      aria-label={cfg.title}
      className={full
        ? 'fixed inset-0 z-[80] flex flex-col gap-2 bg-background p-5'
        : 'flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-card p-4'}
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={cfg.title}
          onChange={(e) => setCfg({ ...cfg, title: e.target.value })}
          aria-label="Chart title"
          className="basis-full bg-transparent text-sm font-semibold text-foreground outline-none focus:underline"
        />
        {canOrient && select('Layout', cfg.horizontal ? 'h' : 'v', [['v', 'Vertical'], ['h', 'Horizontal']], (v) => setCfg({ ...cfg, horizontal: v === 'h' }))}
        {canSort && select('Order', cfg.byValue ? 'value' : 'rfq', [['value', 'Largest first'], ['rfq', 'RFQ order']], (v) => setCfg({ ...cfg, byValue: v === 'value' }))}
        {canDonut && select('Style', cfg.donut ? 'donut' : 'pie', [['donut', 'Donut'], ['pie', 'Pie']], (v) => setCfg({ ...cfg, donut: v === 'donut' }))}
        {canMetric && select('Measure', cfg.metric ?? METRICS[0].key, METRICS.map((m) => [m.key, m.label]), (v) => setCfg({ ...cfg, metric: v }))}
        {(canSort || canOrient) && select('Show', cfg.top, TOP_OPTIONS.map((n) => [n, n === 0 ? 'All' : `Top ${n}`]), (v) => setCfg({ ...cfg, top: Number(v) }))}
        <button type="button" onClick={() => setShowTable((s) => !s)} aria-pressed={showTable} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground hover:bg-muted">
          <TableIcon size={13} /> Data
        </button>
        <button type="button" onClick={exportPng} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground hover:bg-muted">
          <DownloadSimple size={13} /> PNG
        </button>
        <button type="button" onClick={() => setFull((f) => !f)} aria-label={full ? 'Exit full screen' : 'Full screen'} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground hover:bg-muted">
          {full ? <ArrowsInSimple size={13} /> : <ArrowsOutSimple size={13} />} {full ? 'Close' : 'Full screen'}
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground">{note}</p>
      <div ref={hostRef} className={full ? 'min-h-0 flex-1' : 'h-[340px] w-full'} role="img" aria-label={cfg.title} />
      {showTable && (
        <div className="max-h-[260px] overflow-auto rounded-md border border-border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted">
              <tr>{built.columns.map((c) => <th key={c} className="px-2 py-1.5 text-left font-semibold">{c}</th>)}</tr>
            </thead>
            <tbody>
              {built.table.map((row, i) => (
                <tr key={i} className="border-t border-border/60">
                  {row.map((cell, j) => <td key={j} className="px-2 py-1 tabular-nums">{typeof cell === 'number' ? money(cell) : cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function PortfolioCharts({ counted, all, currency, commodityExcess, leadBuckets, leadTotals, definitions }: PortfolioChartsProps) {
  const buyBuild = useMemo(() => (cfg: Config) => buildBuy(counted, cfg, currency), [counted, currency]);
  const leadBuild = useMemo(() => (cfg: Config) => buildLead(counted, cfg, leadBuckets), [counted, leadBuckets]);
  const commodityBuild = useMemo(() => (cfg: Config) => buildCommodity(commodityExcess, cfg, currency), [commodityExcess, currency]);
  const costingBuild = useMemo(() => (cfg: Config) => buildCosting(all, cfg), [all]);
  const metricBuild = useMemo(() => (cfg: Config) => buildMetric(counted, cfg), [counted]);

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <ChartCard
        id="costing-status"
        defaults={{ title: 'Production component costing status', horizontal: false, byValue: false, top: 0, donut: true }}
        canOrient={false} canSort={false} canDonut
        build={costingBuild}
        note={`Costed = CBOM lines with a final price. ${definitions.costing_pct ?? ''}`}
      />
      <ChartCard
        id="buy-value"
        defaults={{ title: 'Baseline vs final buy value by RFQ', horizontal: false, byValue: true, top: 10, donut: false }}
        canOrient canSort={false} canDonut={false}
        build={buyBuild}
        note={`${definitions.final_buy ?? ''} ${currency ? `All figures in ${currency}.` : ''}`}
      />
      <ChartCard
        id="lead-time"
        defaults={{ title: 'Lead-time exposure by RFQ (parts per lead-time bucket)', horizontal: true, byValue: true, top: 10, donut: false }}
        canOrient canSort canDonut={false}
        build={leadBuild}
        note={`${definitions.lead_time ?? ''} Totals over all RFQs in ${currency ?? 'the main currency'}: ${leadBuckets.map((b) => `${b} ${money(leadTotals[b] ?? 0)}`).join(', ')}.`}
      />
      <ChartCard
        id="rfq-measure"
        defaults={{ title: 'One measure for each RFQ', horizontal: true, byValue: true, top: 10, donut: false, metric: 'final_buy' }}
        canOrient canSort canDonut={false} canMetric
        build={metricBuild}
        note="Pick the measure in the card. Each bar is one RFQ's figure from its newest report, in the main currency, as the tile of that name defines it."
      />
      <ChartCard
        id="commodity-excess"
        defaults={{ title: 'Top commodities by net excess cost', horizontal: true, byValue: true, top: 10, donut: false }}
        canOrient canSort={false} canDonut={false}
        build={commodityBuild}
        note={definitions.commodity_excess ?? ''}
      />
    </div>
  );
}
