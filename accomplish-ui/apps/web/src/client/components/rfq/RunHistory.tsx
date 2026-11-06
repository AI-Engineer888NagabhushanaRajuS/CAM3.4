import { useCallback, useEffect, useState } from 'react';
import { ArrowsClockwise, CheckCircle, CircleNotch, Prohibit, StopCircle, WarningCircle } from '@phosphor-icons/react';
import { badgeWord, fetchRuns, formatDuration, type RunEntry, type RunStatus } from '@/lib/runHistory';
import { cn } from '@/lib/utils';

export type RightView = 'workflow' | 'history';

const POLL_MS = 5000;
const BUTTON = 'inline-flex min-h-7 items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-semibold text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50';

const LOOK: Record<RunStatus, { Icon: typeof CheckCircle; tone: string; spin?: boolean }> = {
  running: { Icon: CircleNotch, tone: 'text-primary', spin: true },
  passed: { Icon: CheckCircle, tone: 'text-emerald-700 dark:text-emerald-400' },
  failed: { Icon: WarningCircle, tone: 'text-destructive' },
  stopped: { Icon: StopCircle, tone: 'text-amber-700 dark:text-amber-400' },
  replaced: { Icon: ArrowsClockwise, tone: 'text-muted-foreground' },
  cancelled: { Icon: Prohibit, tone: 'text-muted-foreground' },
};

/** Workflow | History switch for the right pane (the header of the output column). */
export function RightViewToggle({ view, onChange }: { view: RightView; onChange: (v: RightView) => void }) {
  return (
    <div role="group" aria-label="Right pane view" className="inline-flex rounded-full border border-border bg-muted/40 p-0.5">
      {(['workflow', 'history'] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={view === v}
          onClick={() => onChange(v)}
          className={cn(
            'min-h-7 rounded-full px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            view === v ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {v === 'workflow' ? 'Workflow' : 'History'}
        </button>
      ))}
    </div>
  );
}

/** `latest`: only the newest run can be repeated (a rerun resumes the RFQ, it does not replay an old run). */
function Row({ run, onRerun, busy, latest }: { run: RunEntry; onRerun: () => void; busy: boolean; latest: boolean }) {
  const { Icon, tone, spin } = LOOK[run.status];
  const f = run.failure;
  return (
    <li className="rounded-lg border border-border bg-card p-3" data-testid="run-row">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={cn('inline-flex items-center gap-1.5 text-sm font-semibold', tone)}>
          <Icon className={cn('h-4 w-4', spin && 'animate-spin motion-reduce:animate-none')} weight="fill" aria-hidden />
          {badgeWord(run)}
        </span>
        <span className="text-xs text-muted-foreground">
          {run.started_at ? new Date(run.started_at).toLocaleString() : 'start time unknown'}
        </span>
        <span className="text-xs text-muted-foreground">
          {run.status === 'running' ? 'in progress' : formatDuration(run.duration_ms)}
        </span>
        <span className="text-xs text-muted-foreground">by {run.started_by}</span>
      </div>
      {f && (
        <div className="mt-2 space-y-1.5 text-xs">
          <p className="text-sm font-semibold text-foreground">{f.title}</p>
          <p className="text-foreground/85">{f.cause}</p>
          <p className="font-medium text-foreground">{f.next_step}</p>
          <details className="text-muted-foreground">
            <summary className="cursor-pointer select-none">Technical details</summary>
            <p className="mt-1 break-words font-mono">{f.raw || 'No details were reported.'}</p>
          </details>
          {run.can_rerun && latest && (
            <button type="button" className={BUTTON} disabled={busy} onClick={onRerun}>
              <ArrowsClockwise className="h-3.5 w-3.5" aria-hidden />
              {busy ? 'Starting...' : 'Run again'}
            </button>
          )}
        </div>
      )}
    </li>
  );
}

/** Every pipeline run of this RFQ, newest first, a failure explained in plain words (SPEC-021). */
export function RunHistory({ rfqId, onRerun }: { rfqId: string; onRerun: (rfqId: string) => Promise<void> | void }) {
  const [runs, setRuns] = useState<RunEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRuns(await fetchRuns(rfqId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'unknown error');
    }
  }, [rfqId]);

  useEffect(() => { setRuns(null); void load(); }, [load]);
  const anyRunning = runs?.some((r) => r.status === 'running') ?? false;
  useEffect(() => {
    if (!anyRunning) return undefined;
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [anyRunning, load]);

  const rerun = async () => {
    setBusy(true);
    try { await onRerun(rfqId); } finally { setBusy(false); }
    setTimeout(() => void load(), 1500);
  };

  return (
    <section aria-label={`Run history of ${rfqId}`} className="h-full overflow-y-auto p-4" data-testid="run-history">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-bold text-foreground">Run history <span className="font-normal text-muted-foreground">{rfqId}</span></h3>
        <button type="button" className={BUTTON} onClick={() => void load()}>Refresh</button>
      </div>
      {error && (
        <p role="alert" className="mb-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
          Could not load the run history: {error}.
        </p>
      )}
      {runs === null && !error && <p role="status" className="text-sm text-muted-foreground">Loading runs...</p>}
      {runs !== null && runs.length === 0 && (
        <p className="text-sm text-muted-foreground">No runs yet. A run starts when files are uploaded or the pipeline is continued.</p>
      )}
      {runs !== null && runs.length > 0 && (
        <ul className="space-y-2" aria-live="polite">
          {runs.map((r, i) => <Row key={r.run_id} run={r} latest={i === 0} busy={busy} onRerun={() => void rerun()} />)}
        </ul>
      )}
    </section>
  );
}
