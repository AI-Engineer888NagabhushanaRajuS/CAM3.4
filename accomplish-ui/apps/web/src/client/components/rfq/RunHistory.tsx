import { useCallback, useEffect, useState } from 'react';
import { ArrowsClockwise, CheckCircle, CircleNotch, HourglassMedium, Prohibit, StopCircle, WarningCircle } from '@phosphor-icons/react';
import { badgeWord, fetchAllRuns, fetchRuns, formatDuration, summarizeByUser, type RunEntry, type RunStatus } from '@/lib/runHistory';
import { cn } from '@/lib/utils';

export type RightView = 'workflow' | 'history';

const POLL_MS = 5000;
const BUTTON = 'inline-flex min-h-7 items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-semibold text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50';

const LOOK: Record<RunStatus, { Icon: typeof CheckCircle; tone: string; spin?: boolean }> = {
  running: { Icon: CircleNotch, tone: 'text-primary', spin: true },
  waiting: { Icon: HourglassMedium, tone: 'text-amber-700 dark:text-amber-400' },
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
function Row({ run, onRerun, busy, latest, onOpenRfq }: { run: RunEntry; onRerun: () => void; busy: boolean; latest: boolean; onOpenRfq?: (id: string) => void }) {
  const { Icon, tone, spin } = LOOK[run.status];
  const f = run.failure;
  return (
    <li className="rounded-lg border border-border bg-card p-3" data-testid="run-row">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {onOpenRfq && run.rfq_id && (
          <button type="button" className="font-mono text-xs font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onOpenRfq(run.rfq_id as string)} title={`Open ${run.rfq_id}`}>
            {run.rfq_id}
          </button>
        )}
        <span className={cn('inline-flex items-center gap-1.5 text-sm font-semibold', tone)}>
          <Icon className={cn('h-4 w-4', spin && 'animate-spin motion-reduce:animate-none')} weight="fill" aria-hidden />
          {badgeWord(run)}
        </span>
        <span className="text-xs text-muted-foreground">
          {run.started_at ? new Date(run.started_at).toLocaleString() : 'start time unknown'}
        </span>
        <span className="text-xs text-muted-foreground">
          {run.status === 'running' || run.status === 'waiting' ? 'in progress' : formatDuration(run.duration_ms)}
        </span>
        <span className="text-xs text-muted-foreground" title={run.started_by_email ?? undefined}>by {run.started_by}</span>
      </div>
      {run.status === 'waiting' && (
        <p className="mt-2 text-xs text-foreground/85">
          {run.waiting_on ?? 'A step'} finished and is waiting for a person to review it. Open the Workflow view to review, then continue.
        </p>
      )}
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

/** Shown in the Workflow view when the newest run failed: the pill and the stage list only learn of failures that send a progress event, and a wrong input file does not. */
export function FailedRunNotice({ run, onOpenHistory }: { run: RunEntry | null; onOpenHistory: () => void }) {
  if (!run || run.status !== 'failed' || !run.failure) return null;
  return (
    <div role="alert" className="mx-5 mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs" data-testid="failed-run-notice">
      <WarningCircle className="h-4 w-4 shrink-0 text-destructive" weight="fill" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-foreground">{run.failure.title}</span>
        <span className="block text-foreground/85">{run.failure.next_step}</span>
      </span>
      <button type="button" className={BUTTON} onClick={onOpenHistory}>See history</button>
    </div>
  );
}

type Scope = 'rfq' | 'all';

/**
 * Pipeline runs, newest first, a failure explained in plain words (SPEC-021). With an RFQ open: that RFQ's runs, or the runs of every
 * RFQ ("All RFQs": for an admin all users, for anybody else their own: the daemon decides). With no RFQ open: the all-RFQs list.
 */
export function RunHistory({ rfqId, onRerun, onOpenRfq, isAdmin = false }: {
  rfqId: string | null;
  onRerun: (rfqId: string) => Promise<void> | void;
  onOpenRfq?: (rfqId: string) => void;
  isAdmin?: boolean;
}) {
  const [scope, setScope] = useState<Scope>(rfqId ? 'rfq' : 'all');
  const [runs, setRuns] = useState<RunEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [who, setWho] = useState<string | null>(null); // the person the all-RFQs list is narrowed to
  const mode: Scope = rfqId ? scope : 'all';

  useEffect(() => { setScope(rfqId ? 'rfq' : 'all'); }, [rfqId]);

  const load = useCallback(async () => {
    try {
      setRuns(mode === 'rfq' && rfqId ? await fetchRuns(rfqId) : await fetchAllRuns());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'unknown error');
    }
  }, [mode, rfqId]);

  useEffect(() => { setRuns(null); void load(); }, [load]);
  const anyRunning = runs?.some((r) => r.status === 'running' || r.status === 'waiting') ?? false;
  useEffect(() => {
    if (!anyRunning) return undefined;
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [anyRunning, load]);

  const rerun = async () => {
    if (!rfqId) return;
    setBusy(true);
    try { await onRerun(rfqId); } finally { setBusy(false); }
    setTimeout(() => void load(), 1500);
  };

  const everyone = isAdmin ? 'All RFQs' : 'My runs';
  const people = mode === 'all' && runs ? summarizeByUser(runs) : [];
  const shown = who && runs ? runs.filter((r) => r.started_by === who) : runs;
  const picked = people.find((p) => p.who === who);
  return (
    <section aria-label={mode === 'rfq' ? `Run history of ${rfqId}` : isAdmin ? 'Run history of all RFQs' : 'My run history'} className="h-full overflow-y-auto p-4" data-testid="run-history">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <h3 className="text-sm font-bold text-foreground">
          Run history <span className="font-normal text-muted-foreground">{mode === 'rfq' ? rfqId : isAdmin ? 'all RFQs, all users' : 'the runs you started'}</span>
        </h3>
        <div className="flex items-center gap-2">
          {rfqId && (
            <div role="group" aria-label="Which runs" className="inline-flex rounded-full border border-border bg-muted/40 p-0.5">
              {([['rfq', 'This RFQ'], ['all', everyone]] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={mode === id}
                  onClick={() => setScope(id)}
                  className={cn('min-h-7 rounded-full px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    mode === id ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          <button type="button" className={BUTTON} onClick={() => void load()}>Refresh</button>
        </div>
      </div>
      {error && (
        <p role="alert" className="mb-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
          Could not load the run history: {error}.
        </p>
      )}
      {people.length > 1 && (
        <div role="group" aria-label="Who started the runs" className="mb-3 flex flex-wrap gap-1.5">
          {[{ who: null, label: `Everyone (${runs?.length ?? 0})` }, ...people.map((p) => ({ who: p.who, label: `${p.who} (${p.total})` }))].map((c) => (
            <button
              key={c.who ?? 'everyone'}
              type="button"
              aria-pressed={who === c.who}
              onClick={() => setWho(c.who)}
              className={cn('min-h-7 rounded-full border px-2.5 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                who === c.who ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground')}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
      {picked && (
        <p className="mb-3 text-xs text-muted-foreground" data-testid="user-summary">
          <b className="text-foreground">{picked.who}</b>: {picked.total} run{picked.total === 1 ? '' : 's'} &middot; {picked.passed} passed &middot; {picked.failed} failed &middot; {picked.open} open
        </p>
      )}
      {runs === null && !error && <p role="status" className="text-sm text-muted-foreground">Loading runs...</p>}
      {runs !== null && runs.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {mode === 'rfq' ? 'No runs yet. A run starts when files are uploaded or the pipeline is continued.' : 'No runs recorded yet. Runs appear here as soon as someone uploads files or continues a pipeline.'}
        </p>
      )}
      {shown !== null && shown.length > 0 && (
        <ul className="space-y-2" aria-live="polite">
          {shown.map((r, i) => (
            <Row key={`${r.rfq_id ?? ''}-${r.run_id}`} run={r} latest={mode === 'rfq' && i === 0} busy={busy} onRerun={() => void rerun()} onOpenRfq={mode === 'all' ? onOpenRfq : undefined} />
          ))}
        </ul>
      )}
    </section>
  );
}
