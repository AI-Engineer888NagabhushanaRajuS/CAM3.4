import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import { applyPrefs, useDashboardPrefs, type DashboardPrefs } from '@/lib/dashboardPrefs';

/**
 * The BOM matrix (quantity of each part in each assembly). Four views of the same numbers: a line per part across the assemblies
 * (the default, so a part's usage reads as a trend), a heat map of parts × assemblies, clustered bubbles (dot size is the quantity;
 * parts used in the same assemblies sit together, coloured by commodity), or a triangle matrix (how often two parts share an
 * assembly). Parts are ordered by their grand total; the selector shows the top N, so a 1,000-row BOM stays readable.
 */
export interface MatrixPart {
  part: string;
  quantities: Record<string, number>;
  grand_total: number | null;
  commodity: string | null;
}

const TOP = [10, 25, 50, 100, 0];
const VIEWS = [
  { id: 'line', label: 'Line chart' },
  { id: 'heat', label: 'Heat map' },
  { id: 'bubble', label: 'Clustered bubbles' },
  { id: 'triangle', label: 'Triangle matrix' },
] as const;
type View = (typeof VIEWS)[number]['id'];

// One colour per commodity, cycled; the same commodity keeps its colour within a chart.
const PALETTE = ['#2f5496', '#22a8c9', '#e07b39', '#6aa84f', '#8e5ea2', '#c0392b', '#d4a017', '#5b8c85'];

/**
 * Leaf order of an average-linkage clustering on cosine distance, so parts with similar usage sit next to each other.
 * ponytail: O(n^3) over the parts; above 150 parts the input order (grand total) is kept.
 */
export function clusterOrder(vectors: number[][]): number[] {
  const n = vectors.length;
  if (n < 3 || n > 150) return vectors.map((_, i) => i);
  const norm = vectors.map((v) => Math.hypot(...v) || 1);
  const dist = vectors.map((a, i) => vectors.map((b, j) => {
    if (i === j) return 0;
    let dot = 0;
    for (let k = 0; k < a.length; k++) dot += a[k] * b[k];
    return 1 - dot / (norm[i] * norm[j]);
  }));
  const members = vectors.map((_, i) => [i]);
  const alive = vectors.map((_, i) => i);
  while (alive.length > 1) {
    let pair: [number, number] = [alive[0], alive[1]];
    let best = Infinity;
    for (const a of alive) {
      for (const b of alive) {
        if (a < b && dist[a][b] < best) {
          best = dist[a][b];
          pair = [a, b];
        }
      }
    }
    const [a, b] = pair;
    const sa = members[a].length;
    const sb = members[b].length;
    for (const k of alive) {
      if (k !== a && k !== b) dist[a][k] = dist[k][a] = (sa * dist[a][k] + sb * dist[b][k]) / (sa + sb);
    }
    members[a] = [...members[a], ...members[b]];
    alive.splice(alive.indexOf(b), 1);
  }
  return members[alive[0]];
}

/** Share of the assemblies that either part is in that both are in (Jaccard), 0 to 1. */
function sharedShare(a: MatrixPart, b: MatrixPart, assemblies: string[]): number {
  let both = 0;
  let either = 0;
  for (const asm of assemblies) {
    const x = (a.quantities[asm] ?? 0) > 0;
    const y = (b.quantities[asm] ?? 0) > 0;
    if (x && y) both++;
    if (x || y) either++;
  }
  return either === 0 ? 0 : both / either;
}

function bubbleOption(assemblies: string[], shown: MatrixPart[]): echarts.EChartsOption {
  const order = clusterOrder(shown.map((p) => assemblies.map((a) => p.quantities[a] ?? 0)));
  const rows = order.map((i) => shown[i]);
  const commodities = [...new Set(rows.map((p) => p.commodity ?? 'Unclassified'))];
  const peak = Math.max(1, ...rows.flatMap((p) => assemblies.map((a) => p.quantities[a] ?? 0)));
  return {
    tooltip: {
      formatter: (p: any) => `${rows[p.value[1]].part}<br/>${assemblies[p.value[0]]}: ${p.value[2].toLocaleString()}`,
    },
    legend: { type: 'scroll', top: 0, left: 0, right: 0, textStyle: { fontSize: 11 } },
    grid: { left: 12, right: 24, top: 40, bottom: 40, containLabel: true },
    xAxis: { type: 'category', data: assemblies, splitLine: { show: true, lineStyle: { opacity: 0.4 } }, axisLabel: { rotate: assemblies.length > 8 ? 30 : 0, fontSize: 11 } },
    yAxis: { type: 'category', data: rows.map((p) => p.part), inverse: true, splitLine: { show: true, lineStyle: { opacity: 0.4 } }, axisLabel: { fontSize: 10 } },
    series: commodities.map((c) => ({
      name: c,
      type: 'scatter' as const,
      itemStyle: { color: PALETTE[commodities.indexOf(c) % PALETTE.length] },
      symbolSize: (v: number[]) => 4 + 26 * Math.sqrt(v[2] / peak),
      data: rows.flatMap((p, y) => (p.commodity ?? 'Unclassified') !== c
        ? []
        : assemblies.flatMap((a, x): [number, number, number][] => ((p.quantities[a] ?? 0) > 0 ? [[x, y, p.quantities[a]]] : []))),
    })),
  };
}

function triangleOption(assemblies: string[], shown: MatrixPart[]): echarts.EChartsOption {
  const names = shown.map((p) => p.part);
  // Upper triangle only (column >= row): each pair once, the diagonal is each part with itself.
  const cells: [number, number, number][] = [];
  shown.forEach((pa, i) => {
    shown.forEach((pb, j) => {
      if (j >= i) cells.push([j, i, Number(sharedShare(pa, pb, assemblies).toFixed(2))]);
    });
  });
  return {
    tooltip: {
      formatter: (p: any) => `${names[p.value[1]]} and ${names[p.value[0]]}<br/>Shared assemblies: ${Math.round(p.value[2] * 100)}%`,
    },
    grid: { left: 12, right: 60, top: 12, bottom: 40, containLabel: true },
    xAxis: { type: 'category', data: names, axisLabel: { fontSize: 10, rotate: 60 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: names, inverse: true, axisLabel: { fontSize: 10 }, splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: 1,
      calculable: true,
      orient: 'vertical',
      right: 0,
      top: 'center',
      inRange: { color: ['#f7fbff', '#22a8c9', '#3300aa'] },
    },
    series: [{
      type: 'heatmap',
      data: cells,
      label: { show: shown.length <= 30, fontSize: 10 },
      emphasis: { itemStyle: { shadowBlur: 6 } },
    }],
  };
}

export function BomHeatmap({ assemblies, parts }: { assemblies: string[]; parts: MatrixPart[] }) {
  // The view and the size live in the shared dashboard prefs, so the chat's "switch to heat map" and these selectors agree.
  const prefs = useDashboardPrefs();
  const top = prefs.matrixTop ?? 10;
  // A line runs across assemblies, so with a single assembly it is one dot: the heat map reads better there unless a view was chosen.
  const view: View = prefs.matrixView ?? (assemblies.length < 2 ? 'heat' : 'line');
  const setTop = (n: number) => applyPrefs({ matrixTop: n as DashboardPrefs['matrixTop'] });
  const setView = (v: View) => applyPrefs({ matrixView: v });
  const host = useRef<HTMLDivElement>(null);

  const shown = useMemo(() => {
    const ordered = [...parts].sort((a, b) => (b.grand_total ?? 0) - (a.grand_total ?? 0));
    return top > 0 ? ordered.slice(0, top) : ordered;
  }, [parts, top]);

  useEffect(() => {
    if (!host.current || shown.length === 0) return undefined;
    const chart = echarts.init(host.current, undefined, { renderer: 'canvas' });
    let option: echarts.EChartsOption;
    if (view === 'bubble') option = bubbleOption(assemblies, shown);
    else if (view === 'triangle') option = triangleOption(assemblies, shown);
    else if (view === 'heat') {
      option = {
          tooltip: {
            formatter: (p: any) => `${shown[p.value[1]].part}<br/>${assemblies[p.value[0]]}: ${p.value[2].toLocaleString()}`,
          },
          grid: { left: 12, right: 60, top: 12, bottom: 40, containLabel: true },
          xAxis: { type: 'category', data: assemblies, splitArea: { show: true } },
          yAxis: { type: 'category', data: shown.map((p) => p.part), splitArea: { show: true }, axisLabel: { fontSize: 10 } },
          visualMap: {
            min: 0,
            max: Math.max(1, ...shown.flatMap((p) => assemblies.map((a) => p.quantities[a] ?? 0))),
            calculable: true,
            orient: 'vertical',
            right: 0,
            top: 'center',
            inRange: { color: ['#f7fbff', '#22a8c9', '#3300aa'] },
          },
          series: [{
            type: 'heatmap',
            data: shown.flatMap((p, y) => assemblies.map((a, x): [number, number, number] => [x, y, p.quantities[a] ?? 0])),
            label: { show: shown.length <= 30, fontSize: 10 },
            emphasis: { itemStyle: { shadowBlur: 6 } },
          }],
        };
    } else {
      option = {
          tooltip: { trigger: 'axis', valueFormatter: (v) => (typeof v === 'number' ? v.toLocaleString() : String(v ?? '')) },
          legend: { type: 'scroll', top: 0, left: 0, right: 0, textStyle: { fontSize: 11 } },
          grid: { left: 12, right: 24, top: 56, bottom: 56, containLabel: true },
          xAxis: { type: 'category', data: assemblies, boundaryGap: false, name: 'Assembly', nameLocation: 'middle', nameGap: 36, axisLabel: { rotate: assemblies.length > 8 ? 30 : 0, fontSize: 11 } },
          yAxis: { type: 'value', name: 'Quantity', nameTextStyle: { fontSize: 11 }, splitLine: { lineStyle: { opacity: 0.4 } } },
          dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 4, height: 16 }],
          series: shown.map((p) => ({
            name: p.part,
            type: 'line' as const,
            smooth: false,
            symbolSize: 6,
            data: assemblies.map((a) => p.quantities[a] ?? 0),
          })),
        };
    }
    chart.setOption(option, true);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(host.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [shown, assemblies, view]);

  if (parts.length === 0 || assemblies.length === 0) return <p className="py-6 text-center text-xs text-muted-foreground">The BOM matrix has no quantities to show.</p>;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Matrix view" className="inline-flex flex-wrap rounded-md border border-border p-0.5 text-xs">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              aria-pressed={view === v.id}
              onClick={() => setView(v.id)}
              className={`rounded px-2 py-0.5 ${view === v.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Show
          <select value={top} onChange={(e) => setTop(Number(e.target.value))} className="rounded-md border border-border bg-card px-1.5 py-0.5 text-xs text-foreground">
            {TOP.map((n) => <option key={n} value={n}>{n === 0 ? `All ${parts.length}` : `Top ${n}`}</option>)}
          </select>
          parts by total quantity
        </label>
      </div>
      <div
        ref={host}
        className="w-full"
        style={{ height: view === 'line' ? 420 : Math.min(900, Math.max(260, shown.length * 16 + 60)) }}
        role="img"
        aria-label={`BOM matrix ${VIEWS.find((v) => v.id === view)?.label ?? view}, ${shown.length} parts across ${assemblies.length} assemblies`}
      />
    </div>
  );
}
