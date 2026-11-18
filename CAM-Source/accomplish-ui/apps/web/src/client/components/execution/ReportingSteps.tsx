import { type ReactNode, useCallback, useEffect, useState } from 'react';
import { CheckCircle, Circle, CircleNotch } from '@phosphor-icons/react';
import { RFQ_UPLOAD_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { getSession } from '@/lib/session';
import type { RfqSkillHistoryEntry } from '@/lib/accomplish';

/**
 * The reporting and quote steps of one RFQ, in the manifest's order: 9.1 to 9.4 (Reporting via BullMind) and 10.4 (Approve and
 * send). Each row's state is read from the run: the report step's stored status, the exported workbook, and the recorded approval.
 * 10.4 is a human sign-off: it is enabled once the output exists, and the approval is stored with the signed-in person's email.
 * No e-mail is sent by this step.
 */

type RowState = 'done' | 'ready' | 'waiting';

const STATE_ICON: Record<RowState, ReactNode> = {
  done: <CheckCircle weight="fill" className="h-4 w-4 text-emerald-600 dark:text-emerald-400" aria-hidden />,
  ready: <CircleNotch className="h-4 w-4 animate-spin text-primary" aria-hidden />,
  waiting: <Circle className="h-4 w-4 text-muted-foreground/60" aria-hidden />,
};
const STATE_LABEL: Record<RowState, string> = { done: 'Done', ready: 'Running', waiting: 'Waiting' };

interface Approval {
  approved: boolean;
  approved_by?: string;
  approved_at?: string;
}

export function ReportingSteps({
  rfqId,
  entries,
  outputReady,
}: {
  rfqId: string;
  entries: RfqSkillHistoryEntry[];
  outputReady: boolean;
}) {
  const [approval, setApproval] = useState<Approval | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/${encodeURIComponent(rfqId)}/quote-approval`, rfqId);
      if (res.ok) setApproval((await res.json()) as Approval);
    } catch {
      // The approval status is shown when the service answers; until then 10.4 waits.
    }
  }, [rfqId]);

  useEffect(() => {
    void load();
  }, [load, outputReady]);

  const reportsDone = entries.some((e) => /generate_?reports$/i.test(e.skillCode) && e.stepStatus === 'completed');
  const approved = approval?.approved === true;

  const approve = async () => {
    const who = getSession()?.user.email ?? '';
    if (!who) {
      setError('Sign in again: the approval is recorded with your email.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/${encodeURIComponent(rfqId)}/quote-approval`, rfqId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved_by: who }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `The approval was not recorded (status ${res.status}).`);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The approval was not recorded.');
    } finally {
      setBusy(false);
    }
  };

  const rows: Array<{ id: string; title: string; state: RowState; note?: string; human?: boolean }> = [
    { id: '9.1', title: 'JSON: receive and query', state: reportsDone ? 'done' : 'ready' },
    { id: '9.2', title: 'Excel reports', state: outputReady ? 'done' : reportsDone ? 'ready' : 'waiting' },
    { id: '9.3', title: 'Dashboards and Q&A', state: outputReady ? 'done' : 'waiting' },
    { id: '9.4', title: 'Review', state: outputReady ? 'ready' : 'waiting', human: true, note: 'Open Output, then Review the workbook' },
    {
      id: '10.4',
      title: 'Approve and send quote readiness',
      state: approved ? 'done' : outputReady ? 'ready' : 'waiting',
      human: true,
      note: approved ? `Approved by ${approval?.approved_by ?? ''}` : outputReady ? 'Waiting for your approval' : 'After the output is ready',
    },
  ];

  return (
    <section className="rounded-xl border border-border bg-card p-4" aria-label="Reporting and quote steps">
      <ol className="space-y-2.5">
        {rows.map((r) => (
          <li key={r.id} className="grid grid-cols-[2.25rem_1fr_auto] items-center gap-3">
            <span className="text-xs tabular-nums text-muted-foreground">{r.id}</span>
            <div className="min-w-0">
              <p className="truncate text-sm text-foreground">{r.title}</p>
              {r.note && <p className="truncate text-xs text-muted-foreground">{r.note}</p>}
            </div>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {STATE_ICON[r.state]}
              {r.human && r.state === 'ready' ? 'Your turn' : STATE_LABEL[r.state]}
            </span>
          </li>
        ))}
      </ol>
      {!approved && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4">
          <button
            type="button"
            onClick={() => void approve()}
            disabled={!outputReady || busy}
            className="rounded-md bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {busy ? 'Recording…' : 'Approve and send quote readiness'}
          </button>
          <p className="text-xs text-muted-foreground">Recorded with your email. Nothing is sent to the client by this step.</p>
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-xs text-destructive">{error}</p>}
    </section>
  );
}
