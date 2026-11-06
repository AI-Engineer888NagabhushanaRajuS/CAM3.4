import { useCallback, useEffect, useState } from 'react';
import { ArrowClockwise, Brain, ShieldCheck, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { formatBytes } from '@/lib/rfqAttachments';
import { getMemoryStatus, getTelemetry, type MemoryStatus, type Telemetry } from '@/lib/securityTelemetry';
import { PerimeterSteps } from '@/components/rfq/PerimeterSteps';

const TONE = {
  ok: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  warn: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  bad: 'border-destructive/30 bg-destructive/10 text-destructive',
};
const DECISION_TONE = { released: TONE.ok, quarantined: TONE.bad, error: TONE.warn } as const;
const DECISION_TEXT = { released: 'Released', quarantined: 'Quarantined', error: 'Held' } as const;
const COUNTS = [['released', 'Released', TONE.ok], ['quarantined', 'Quarantined', TONE.bad], ['held', 'Held', TONE.warn], ['error', 'Unreadable log lines', TONE.warn]] as const;

const Chip = ({ tone, children }: { tone: string; children: React.ReactNode }) => (
  <span className={cn('inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-medium', tone)}>{children}</span>
);

function MemoryCard({ memory }: { memory: MemoryStatus | null }) {
  const m = memory?.available ? memory : null;
  return (
    <section className="rounded-xl border border-border p-4" aria-label="Cognee memory">
      <h4 className="flex items-center gap-2 text-sm font-semibold text-foreground"><Brain className="h-4 w-4" aria-hidden />Cognee memory</h4>
      {memory && !memory.available && <p className="mt-2 text-xs text-muted-foreground">Memory service not reachable: {memory.reason}</p>}
      {m && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-foreground">
          <Chip tone={m.provider === 'ollama' ? TONE.warn : TONE.ok}>{m.provider === 'ollama' ? 'Provider: local (Ollama)' : 'Provider: cloud (OpenRouter)'}</Chip>
          <Chip tone={m.writesEnabled ? TONE.ok : TONE.warn}>Writes {m.writesEnabled ? 'on' : 'off'}</Chip>
          <span>{m.running} running, {m.queued} queued (up to {m.maxConcurrent} at once)</span>
        </div>
      )}
      {m && !m.writesEnabled && (
        <p className="mt-2 text-xs text-muted-foreground">
          To turn writes on, set RFQ_MEMORY_LLM_WRITES=1 and, to avoid loading the local GPU, RFQ_MEMORY_LLM_PROVIDER=openrouter with a key in .env, then rebuild rfq-memory-server.
        </p>
      )}
    </section>
  );
}

function Decisions({ data }: { data: Telemetry }) {
  if (data.recent.length === 0) {
    return <p className="rounded-xl border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">No files scanned in the last 30 days.</p>;
  }
  return (
    <div className="max-h-72 overflow-auto rounded-xl border border-border">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-muted/60 text-muted-foreground">
          <tr>{['Time', 'Scope', 'File', 'Decision', 'Reason'].map((h) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.recent.map((r, i) => (
            <tr key={`${r.time}-${r.name}-${i}`}>
              <td className="whitespace-nowrap px-2 py-1.5 text-muted-foreground">{r.time.replace('T', ' ').slice(0, 16)}</td>
              <td className="px-2 py-1.5">{r.scope}</td>
              <td className="max-w-40 truncate px-2 py-1.5 text-foreground" title={r.name}>{r.name}</td>
              <td className="px-2 py-1.5"><Chip tone={DECISION_TONE[r.decision] ?? TONE.warn}>{DECISION_TEXT[r.decision] ?? r.decision}</Chip></td>
              <td className="px-2 py-1.5 text-muted-foreground">{r.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Settings -> Security: engine health, the perimeter, what was released or stopped, and the memory write switch. */
export function SecurityTab() {
  const [data, setData] = useState<Telemetry | null>(null);
  const [memory, setMemory] = useState<MemoryStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [t, m] = await Promise.allSettled([getTelemetry(), getMemoryStatus()]);
    if (t.status === 'fulfilled') setData(t.value);
    else setError(t.reason instanceof Error ? t.reason.message : 'Could not load security telemetry');
    setMemory(m.status === 'fulfilled' ? m.value : { available: false, reason: 'status request failed' });
    setLoading(false);
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-4" data-testid="security-tab">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted-foreground">Attached files are released only when both engines clear them. Last 30 days; names and verdicts only, never file contents.</p>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
          <ArrowClockwise className={cn('mr-1.5 h-4 w-4', loading && 'animate-spin motion-reduce:animate-none')} aria-hidden />Refresh
        </Button>
      </div>
      {loading && !data && <p role="status" className="text-sm text-muted-foreground">Loading security status…</p>}
      {error && (
        <p role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
          <WarningCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />{error}. Attachments stay fail-closed: nothing is released without both engines.
        </p>
      )}
      {data && (
        <>
          <PerimeterSteps phase="result" engines={data.engines} />
          <div className="grid gap-3 sm:grid-cols-2">
            {data.engines.map((e) => (
              <section key={e.id} className="rounded-xl border border-border p-4" aria-label={e.label}>
                <h4 className="flex items-center gap-2 text-sm font-semibold text-foreground"><ShieldCheck className="h-4 w-4" aria-hidden />{e.label}</h4>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-foreground">
                  <Chip tone={e.status === 'ok' ? TONE.ok : TONE.bad}>{e.status === 'ok' ? 'Working' : 'Unavailable'}</Chip>
                  {e.signatures != null && <span>{e.signatures.toLocaleString('en-US')} signatures</span>}
                </div>
                <p className="mt-1.5 break-words text-xs text-muted-foreground">{e.detail}</p>
              </section>
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Decisions in the last 30 days">
            {COUNTS.map(([k, label, tone]) => (
              <div key={k} className={cn('rounded-xl border px-3 py-2', tone)}>
                <dt className="text-[11px] font-medium">{label}</dt>
                <dd className="text-xl font-semibold">{data.counts[k]}</dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-muted-foreground">
            Policy: fail-closed, at most {data.policy.maxFiles} files, {formatBytes(data.policy.maxFileBytes)} each and {formatBytes(data.policy.maxTotalBytes)} per scan; larger picks are sent in waves.
          </p>
          <section aria-label="Recent decisions">
            <h4 className="mb-1.5 text-sm font-semibold text-foreground">Recent decisions</h4>
            <Decisions data={data} />
          </section>
        </>
      )}
      <MemoryCard memory={memory} />
    </div>
  );
}
