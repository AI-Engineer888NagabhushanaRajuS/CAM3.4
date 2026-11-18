import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowsOut, X } from '@phosphor-icons/react';
import type { RfqSkillHistoryEntry } from '@/lib/accomplish';

/**
 * The formula engine's run, as a status list: one row per pipeline step in run order, with the step's stored status and its
 * stored detail or error. Nothing is drawn or animated. The list is the live feed (rfq:skill-progress), so it updates as the
 * pipeline runs. It describes what each step did, not the model's reasoning.
 */

type Status = 'running' | 'completed' | 'warning' | 'failed' | 'skipped';

/** Stored status as shown: a step that ran but flagged something is a warning, as the timeline shows it. */
const statusOf = (e: RfqSkillHistoryEntry): Status => {
  if (e.stepStatus === 'completed' && e.warning) return 'warning';
  if (e.stepStatus === 'running' || e.stepStatus === 'failed' || e.stepStatus === 'skipped') return e.stepStatus;
  return 'completed';
};

const LABEL: Record<Status, string> = {
  running: 'Running',
  completed: 'Done',
  warning: 'Flagged',
  failed: 'Failed',
  skipped: 'Skipped',
};

// Dot colour comes from the app's own tokens: primary for running, muted for skipped, and the destructive token for failure.
const DOT: Record<Status, string> = {
  running: 'bg-primary animate-pulse',
  completed: 'bg-emerald-600 dark:bg-emerald-400',
  warning: 'bg-amber-600 dark:bg-amber-400',
  failed: 'bg-destructive',
  skipped: 'bg-muted-foreground/50',
};

const TEXT: Record<Status, string> = {
  running: 'text-primary',
  completed: 'text-muted-foreground',
  warning: 'text-amber-700 dark:text-amber-300',
  failed: 'text-destructive',
  skipped: 'text-muted-foreground',
};

/** The manifest skill a step belongs to (its name, as the left pane shows it), or null when no skill is linked. */
type SkillOf = (entry: RfqSkillHistoryEntry) => string | null;

function StepList({ entries, expanded, skillOf }: { entries: RfqSkillHistoryEntry[]; expanded: boolean; skillOf?: SkillOf }) {
  const counts = entries.reduce<Record<Status, number>>(
    (acc, e) => {
      acc[statusOf(e)] += 1;
      return acc;
    },
    { running: 0, completed: 0, warning: 0, failed: 0, skipped: 0 },
  );
  const summary = [
    `${entries.length} ${entries.length === 1 ? 'step' : 'steps'}`,
    counts.running ? `${counts.running} running` : null,
    counts.warning ? `${counts.warning} flagged` : null,
    counts.failed ? `${counts.failed} failed` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <section className={`flex min-h-0 flex-col rounded-xl border border-border bg-card ${expanded ? 'h-full' : ''}`} aria-label="Formula engine steps">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold text-foreground">Formula engine</h3>
        <p className="text-xs tabular-nums text-muted-foreground">{summary}</p>
      </header>
      {entries.length === 0 ? (
        <p className="px-4 py-6 text-center text-xs text-muted-foreground">No steps have run yet. They appear here as the pipeline runs.</p>
      ) : (
        <ol className={`min-h-0 divide-y divide-border overflow-y-auto ${expanded ? 'flex-1' : 'max-h-[260px]'}`}>
          {entries.map((e, i) => {
            const st = statusOf(e);
            const note = e.error ?? e.detail ?? null;
            return (
              <li key={e.skillCode} className="grid grid-cols-[1.5rem_1fr_auto] items-start gap-3 px-4 py-2.5">
                <span className="pt-0.5 text-xs tabular-nums text-muted-foreground">{String(i + 1).padStart(2, '0')}</span>
                <div className="min-w-0">
                  {skillOf?.(e) && <p className="truncate text-[11px] uppercase tracking-wide text-muted-foreground/80">{skillOf(e)}</p>}
                  <p className="truncate text-sm text-foreground">{e.skillName}</p>
                  {note && (
                    <p className={`mt-0.5 break-words text-xs ${st === 'failed' ? 'text-destructive' : 'text-muted-foreground'}`}>{note}</p>
                  )}
                </div>
                <span className={`flex items-center gap-1.5 whitespace-nowrap text-xs font-medium ${TEXT[st]}`}>
                  <span className={`inline-block h-2 w-2 rounded-full ${DOT[st]}`} aria-hidden />
                  {LABEL[st]}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <p className="border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
        What each step did, from its stored status and detail. Not the model&apos;s own reasoning.
      </p>
    </section>
  );
}

export function FormulaEngine3D({ entries, expanded = false, skillOf }: { entries: RfqSkillHistoryEntry[]; expanded?: boolean; skillOf?: SkillOf }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  if (expanded) {
    return (
      <div className="h-full p-4" data-testid="formula-engine-3d-expanded">
        <StepList entries={entries} expanded skillOf={skillOf} />
      </div>
    );
  }

  return (
    <div className="space-y-2 px-5" data-testid="formula-engine-3d">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowsOut className="h-3.5 w-3.5" aria-hidden /> Full screen
        </button>
      </div>
      <StepList entries={entries} expanded={false} skillOf={skillOf} />
      {open &&
        createPortal(
          <div role="dialog" aria-modal="true" aria-label="Formula engine, full screen" className="fixed inset-0 z-[90] flex flex-col bg-background p-6" data-testid="formula-engine-fullscreen">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold text-foreground">Formula engine</p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" aria-hidden /> Close
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <FormulaEngine3D entries={entries} expanded skillOf={skillOf} />
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
