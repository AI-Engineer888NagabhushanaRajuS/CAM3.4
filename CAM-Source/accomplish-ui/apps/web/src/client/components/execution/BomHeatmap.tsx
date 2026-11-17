import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';

/**
 * The BOM matrix as a heat map: one row per part, one column per assembly, the colour is the quantity of that part in that assembly.
 * Parts are ordered by their grand total; the selector shows the top N, so a 1,000-row BOM stays readable.
 */
export interface MatrixPart {
  part: string;
  quantities: Record<string, number>;
  grand_total: number | null;
  commodity: string | null;
}

const TOP = [25, 50, 100, 0];

export function BomHeatmap({ assemblies, parts }: { assemblies: string[]; parts: MatrixPart[] }) {
  const [top, setTop] = useState(50);
  const host = useRef<HTMLDivElement>(null);

  const shown = useMemo(() => {
    const ordered = [...parts].sort((a, b) => (b.grand_total ?? 0) - (a.grand_total ?? 0));
    return top > 0 ? ordered.slice(0, top) : ordered;
  }, [parts, top]);

  useEffect(() => {
    if (!host.current || shown.length === 0) return undefined;
    const chart = echarts.init(host.current, undefined, { renderer: 'canvas' });
    const data: [number, number, number][] = [];
    shown.forEach((p, y) => assemblies.forEach((a, x) => data.push([x, y, p.quantities[a] ?? 0])));
    const max = Math.max(1, ...data.map((d) => d[2]));
    chart.setOption({
      tooltip: {
        formatter: (p: { value: [number, number, number] }) => `${shown[p.value[1]].part}<br/>${assemblies[p.value[0]]}: ${p.value[2].toLocaleString()}`,
      },
      grid: { left: 12, right: 60, top: 12, bottom: 40, containLabel: true },
      xAxis: { type: 'category', data: assemblies, splitArea: { show: true } },
      yAxis: { type: 'category', data: shown.map((p) => p.part), splitArea: { show: true }, axisLabel: { fontSize: 10 } },
      visualMap: { min: 0, max, calculable: true, orient: 'vertical', right: 0, top: 'center', inRange: { color: ['#f7fbff', '#22a8c9', '#3300aa'] } },
      series: [{ type: 'heatmap', data, label: { show: shown.length <= 30, fontSize: 10 }, emphasis: { itemStyle: { shadowBlur: 6 } } }],
    } as echarts.EChartsOption);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(host.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [shown, assemblies]);

  if (parts.length === 0 || assemblies.length === 0) return <p className="py-6 text-center text-xs text-muted-foreground">The BOM matrix has no quantities to show.</p>;

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        Show
        <select value={top} onChange={(e) => setTop(Number(e.target.value))} className="rounded-md border border-border bg-card px-1.5 py-0.5 text-xs text-foreground">
          {TOP.map((n) => <option key={n} value={n}>{n === 0 ? `All ${parts.length}` : `Top ${n}`}</option>)}
        </select>
        parts by total quantity
      </label>
      <div
        ref={host}
        className="w-full"
        style={{ height: Math.min(900, Math.max(260, shown.length * 16 + 60)) }}
        role="img"
        aria-label={`BOM matrix heat map, ${shown.length} parts across ${assemblies.length} assemblies`}
      />
    </div>
  );
}
