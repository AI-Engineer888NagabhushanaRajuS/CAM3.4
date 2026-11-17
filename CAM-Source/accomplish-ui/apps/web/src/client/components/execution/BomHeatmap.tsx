import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts';
import { applyPrefs, useDashboardPrefs, type DashboardPrefs } from '@/lib/dashboardPrefs';

/**
 * The BOM matrix (quantity of each part in each assembly). Two views of the same numbers: a line per part across the assemblies
 * (the default, so a part's usage reads as a trend), or a heat map of parts × assemblies. Parts are ordered by their grand total;
 * the selector shows the top N, so a 1,000-row BOM stays readable.
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
] as const;
type View = (typeof VIEWS)[number]['id'];

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
    const option: echarts.EChartsOption = view === 'line'
      ? {
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
        }
      : {
          tooltip: {
            formatter: (p: { value: [number, number, number] }) => `${shown[p.value[1]].part}<br/>${assemblies[p.value[0]]}: ${p.value[2].toLocaleString()}`,
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
    chart.setOption(option, true);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(host.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [shown, assemblies, view]);

  if (parts.length === 0 || assemblies.length === 0) return <p className="py-6 text-center text-xs text-muted-foreground">The BOM matrix has no quantities to show.</p>;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Matrix view" className="inline-flex rounded-md border border-border p-0.5 text-xs">
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
        aria-label={`BOM matrix ${view === 'line' ? 'line chart' : 'heat map'}, ${shown.length} parts across ${assemblies.length} assemblies`}
      />
    </div>
  );
}
