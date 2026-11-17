/**
 * Shown while a run's output is being built, and hidden once the output exists. A single-tone die drawn in SVG: traces run across
 * it and signal pulses travel along them. The centre names the step the pipeline is on now (its real stored name). Motion stops
 * for users who ask for reduced motion.
 */

const GRID = 6;
const CELL = 40;
const PAD = 30;
const SIZE = PAD * 2 + CELL * (GRID - 1);

// Trace paths: a fixed set of routes across the die, so the drawing is the same on every render.
const TRACES: string[] = Array.from({ length: GRID }, (_, r) => {
  const y = PAD + r * CELL;
  return `M ${PAD} ${y} H ${PAD + CELL * ((r * 2) % (GRID - 1))} V ${PAD + CELL * ((r + 2) % (GRID - 1))} H ${SIZE - PAD}`;
}).concat(
  Array.from({ length: GRID }, (_, c) => {
    const x = PAD + c * CELL;
    return `M ${x} ${PAD} V ${PAD + CELL * ((c * 3) % (GRID - 1))} H ${PAD + CELL * ((c + 1) % (GRID - 1))} V ${SIZE - PAD}`;
  }),
);

export function ProcessingChip({ step, done, total }: { step: string | null; done: number; total: number }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4" data-testid="processing-chip" role="status" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-foreground">Building the output</p>
        <p className="text-xs tabular-nums text-muted-foreground">
          {total > 0 ? `${done} of ${total} steps` : 'waiting for the first step'}
        </p>
      </div>
      <div className="mt-3 flex justify-center">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE * 3} height={SIZE * 3} className="max-w-full" aria-hidden>
          <rect x={PAD - 14} y={PAD - 14} width={SIZE - (PAD - 14) * 2} height={SIZE - (PAD - 14) * 2} rx="6" className="fill-muted stroke-border" strokeWidth="1" />
          {TRACES.map((d, i) => (
            <path key={`t${i}`} d={d} className="fill-none stroke-border" strokeWidth="1.5" />
          ))}
          {TRACES.map((d, i) => (
            <path
              key={`p${i}`}
              d={d}
              pathLength={100}
              className="fill-none stroke-primary processing-pulse"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray="8 92"
              style={{ animationDelay: `${(i % 6) * 0.35}s` }}
            />
          ))}
          <rect x={SIZE / 2 - 34} y={SIZE / 2 - 22} width="68" height="44" rx="6" className="fill-card stroke-primary" strokeWidth="1.5" />
          <text x={SIZE / 2} y={SIZE / 2 + 4} textAnchor="middle" className="fill-foreground" style={{ fontSize: 9, fontWeight: 600 }}>
            {step ? step.slice(0, 11) : 'idle'}
          </text>
        </svg>
      </div>
      <p className="mt-2 text-center text-xs text-muted-foreground">{step ? `On: ${step}` : 'Nothing is running right now.'}</p>
      <style>{`
        .processing-pulse { animation: processing-pulse 2.4s linear infinite; }
        @keyframes processing-pulse { from { stroke-dashoffset: 0; } to { stroke-dashoffset: -100; } }
        @media (prefers-reduced-motion: reduce) { .processing-pulse { animation: none; opacity: 0.6; } }
      `}</style>
    </div>
  );
}
