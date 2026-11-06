import { useEffect, useState } from 'react';
import { badgeWord, fetchAllRuns, formatDuration, type RunEntry } from '@/lib/runHistory';

/** The pipeline runs one user started (read from Temporal through the daemon; an admin sees any user's). Loaded when the card opens it. */
export function UserActivity({ email }: { email: string }) {
  const [runs, setRuns] = useState<RunEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    fetchAllRuns({ by: email, limit: 10 })
      .then((r) => { if (!stopped) setRuns(r); })
      .catch((e: unknown) => { if (!stopped) setError(e instanceof Error ? e.message : 'unknown error'); });
    return () => { stopped = true; };
  }, [email]);

  if (error) return <p role="alert" className="mt-2 text-[11px] text-destructive">Could not load the activity: {error}.</p>;
  if (runs === null) return <p role="status" className="mt-2 text-[11px] text-muted-foreground">Loading activity...</p>;
  if (runs.length === 0) return <p className="mt-2 text-[11px] text-muted-foreground">No runs started by this user yet. (Runs from before this tracking show no user.)</p>;
  return (
    <ul className="mt-2 space-y-1" aria-label={`Recent runs started by ${email}`} data-testid="user-activity">
      {runs.map((r) => (
        <li key={`${r.rfq_id}-${r.run_id}`} className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-muted-foreground">
          <span className="font-mono font-semibold text-foreground">{r.rfq_id}</span>
          <span className="font-medium text-foreground">{badgeWord(r)}</span>
          <span>{r.started_at ? new Date(r.started_at).toLocaleString() : ''}</span>
          <span>{r.status === 'running' || r.status === 'waiting' ? 'in progress' : formatDuration(r.duration_ms)}</span>
        </li>
      ))}
    </ul>
  );
}
