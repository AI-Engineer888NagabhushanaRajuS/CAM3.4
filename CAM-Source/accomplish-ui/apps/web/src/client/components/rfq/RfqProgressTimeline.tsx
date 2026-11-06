import { Check, Warning } from '@phosphor-icons/react';
import type { RfqSkillHistoryEntry } from '@/lib/accomplish';

interface RfqProgressTimelineProps {
  entries: RfqSkillHistoryEntry[];
}

type StepState = 'completed' | 'running' | 'failed';

function StepNode({ state }: { state: StepState }) {
  if (state === 'completed') {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
        <Check className="h-3 w-3" weight="bold" />
      </span>
    );
  }
  if (state === 'failed') {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-destructive text-destructive-foreground">
        <Warning className="h-3 w-3" weight="bold" />
      </span>
    );
  }
  return <span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-border border-t-primary" />;
}

const TITLE_CLASS: Record<StepState, string> = {
  completed: 'text-foreground',
  running: 'text-primary',
  failed: 'text-destructive',
};

/**
 * Vertical timeline/stepper for the right panel -- one node per skill that
 * has actually run or is running for the active RFQ, ordered by arrival.
 * Only real entries are rendered (no scaffolded/pre-known step list): this
 * environment's routing sequence doesn't match any single fixed skill set
 * across profiles, so pre-filling "upcoming" steps produced a second, wrong
 * list running in parallel with the real one. Seeded from
 * rfq.getSkillHistory (DB) on RFQ selection / resume / hard refresh, then
 * kept current by live rfq:skill-progress SSE events -- same data source as
 * the terminal log this replaces, only the rendering changed.
 */
export function RfqProgressTimeline({ entries }: RfqProgressTimelineProps) {
  if (entries.length === 0) {
    return (
      <div className="mx-5 flex min-h-[120px] items-center justify-center rounded-xl border border-border/70 bg-card p-5 font-mono text-xs text-muted-foreground">
        No progress yet for this RFQ.
      </div>
    );
  }

  return (
    <div className="px-5 py-4">
      {entries.map((entry, i) => {
        const state: StepState = entry.stepStatus === 'failed' ? 'failed' : entry.stepStatus === 'completed' ? 'completed' : 'running';
        const isLast = i === entries.length - 1;
        return (
          <div key={entry.skillCode} className="flex gap-2.5">
            <div className="flex flex-col items-center">
              <StepNode state={state} />
              {!isLast && (
                <div className={`w-[1.5px] flex-1 min-h-[12px] ${state === 'completed' ? 'bg-emerald-500' : 'bg-border'}`} />
              )}
            </div>
            <div className={`min-w-0 flex-1 ${isLast ? 'pb-0' : 'pb-3'}`}>
              {/* Exact backend skillName, never shortened. */}
              <p className={`text-sm font-bold leading-tight ${TITLE_CLASS[state]}`}>{entry.skillName}</p>
              {state === 'failed' && entry.error && (
                <p className="mt-1 text-xs leading-relaxed text-destructive/80">{entry.error}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
