import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import 'echarts-gl';

/**
 * Cost per set for every assembly and every volume, as 3D bars: assembly along one axis, volume along the other, cost up.
 * The values are the ones the cost-per-set card shows (the workbook's own Summary); hover a bar for its exact figure, drag to turn it.
 */
export function VolumeBars3D({ assemblies, volumes, values, unit }: { assemblies: string[]; volumes: string[]; values: number[][]; unit: string }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current) return undefined;
    const chart = echarts.init(host.current, undefined, { renderer: 'canvas' });
    const data: [number, number, number][] = [];
    values.forEach((row, i) => row.forEach((v, j) => { if (Number.isFinite(v)) data.push([i, j, v]); }));
    chart.setOption({
      tooltip: {
        formatter: (p: { value: [number, number, number] }) =>
          `${assemblies[p.value[0]]}<br/>${volumes[p.value[1]]}: ${p.value[2].toLocaleString(undefined, { maximumFractionDigits: 2 })}${unit ? ` ${unit}` : ''}`,
      },
      visualMap: { min: 0, max: Math.max(1, ...data.map((d) => d[2])), inRange: { color: ['#c7e9f7', '#22a8c9', '#3300aa'] }, dimension: 2, show: true, right: 0, top: 'center' },
      xAxis3D: { type: 'category', data: assemblies, name: 'Assembly' },
      yAxis3D: { type: 'category', data: volumes, name: 'Volume' },
      zAxis3D: { type: 'value', name: unit ? `Cost per set (${unit})` : 'Cost per set' },
      grid3D: { boxWidth: 140, boxDepth: 80, viewControl: { autoRotate: false, alpha: 22, beta: 30 }, light: { main: { intensity: 1.2 } } },
      series: [{ type: 'bar3D', data, shading: 'lambert', barSize: 18, label: { show: false } }],
    } as echarts.EChartsOption);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(host.current);
    return () => { ro.disconnect(); chart.dispose(); };
  // Keyed by the values, not the array identities: the dashboard builds new arrays on every render.
  }, [JSON.stringify(assemblies), JSON.stringify(volumes), JSON.stringify(values), unit]);

  return <div ref={host} className="h-[360px] w-full" role="img" aria-label="Cost per set by assembly and volume, 3D" />;
}
