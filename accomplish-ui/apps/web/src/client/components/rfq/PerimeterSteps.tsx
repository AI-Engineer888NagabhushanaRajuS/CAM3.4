import { cn } from '@/lib/utils';
import type { EngineStatus } from '@/lib/rfqAttachments';

export type Phase = 'review' | 'scanning' | 'result';

const STEPS = ['Select', 'Quarantine', 'BuLL*Sav', 'Repel', 'Verdict'] as const;
const WORDS = { now: 'in progress', done: 'done', alert: 'needs attention', todo: 'not started' };

/** The five stages of the perimeter. Quarantine to Repel run together on the server, so they are shown as one running block. */
export function PerimeterSteps({ phase, engines }: { phase: Phase; engines?: EngineStatus[] }) {
  const failed = engines?.some((e) => e.status !== 'ok') ?? false;
  const state = (i: number) =>
    phase === 'review' ? (i === 0 ? 'now' : 'todo')
    : phase === 'scanning' ? (i === 0 ? 'done' : i < 4 ? 'now' : 'todo')
    : i === 2 || i === 3 ? (failed ? 'alert' : 'done') : 'done';
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-[11px]" aria-label="Security pipeline">
      {STEPS.map((label, i) => (
        <li key={label} className="flex items-center gap-1.5" aria-current={state(i) === 'now' ? 'step' : undefined}>
          <span className={cn('rounded-full border px-2 py-0.5 font-medium', {
            'border-primary/40 bg-primary/10 text-primary': state(i) === 'now',
            'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400': state(i) === 'done',
            'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400': state(i) === 'alert',
            'border-border text-muted-foreground': state(i) === 'todo',
          })}>
            {label}
            <span className="sr-only"> ({WORDS[state(i)]})</span>
          </span>
          {i < STEPS.length - 1 && <span aria-hidden className="h-px w-3 bg-border" />}
        </li>
      ))}
    </ol>
  );
}
