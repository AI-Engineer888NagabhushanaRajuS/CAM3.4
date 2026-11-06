import { useEffect, useState } from 'react';
import { CheckCircle, MinusCircle, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { confirmAction, type ActionStep, type UiDirective } from '@/lib/chatContract';
import { OpenExportDirective } from './OpenDirectives';
import type { ConfirmOutcome } from './useAssistantChat';

type Confirm = Extract<UiDirective, { type: 'confirm_action' }>;

interface ConfirmActionCardProps {
  ui: Confirm;
  /** Set once the user has answered (kept on the message): the buttons never come back. */
  outcome?: ConfirmOutcome;
  onSettle: (outcome: ConfirmOutcome) => void;
}

const STEP_WORD: Record<ActionStep['status'], string> = { done: 'Done', failed: 'Failed', skipped: 'Skipped' };
const STEP_STYLE: Record<ActionStep['status'], string> = {
  done: 'text-emerald-700 dark:text-emerald-400',
  failed: 'text-destructive',
  skipped: 'text-muted-foreground',
};

const STEP_ICON = { done: CheckCircle, failed: WarningCircle, skipped: MinusCircle };

const text = (v: unknown): string => {
  if (typeof v === 'string') return v;
  if (v && typeof v === 'object' && typeof (v as { name?: unknown }).name === 'string') return (v as { name: string }).name;
  return JSON.stringify(v);
};
const label = (key: string) => key.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase());

const NOT_SET = 'Not set';
const str = (v: unknown): string => (typeof v === 'string' && v.trim() ? v : NOT_SET);

/** What the card lists. start_pipeline has fixed, named rows (null = shown in words); create_rfq lists whatever the daemon sent. */
function rowsOf(ui: Confirm): Array<[string, unknown]> {
  if (ui.action === 'edit_value') {
    const { rfqId, bomItemId, label: part, fieldLabel, before, after } = ui.params;
    const val = (v: unknown) => (v === null || v === undefined || v === '' ? 'Empty' : String(v));
    return [['RFQ', str(rfqId)], ['Item', `${str(part)} (bom item ${str(bomItemId)})`], ['Field', str(fieldLabel)], ['Current value', val(before)], ['New value', val(after)]];
  }
  if (ui.action !== 'start_pipeline') {
    return Object.entries(ui.params).map(([k, v]) => [label(k), v]);
  }
  const { rfqId, stage, customer, project } = ui.params;
  return [
    ['RFQ id', str(rfqId)],
    ['Stage', typeof stage === 'number' ? `Stage ${stage}` : 'Not started yet'],
    ['Customer', str(customer)],
    ['Project', str(project)],
  ];
}

function Value({ value }: { value: unknown }) {
  if (!Array.isArray(value)) return <>{text(value)}</>;
  if (value.length === 0) return <>None</>;
  return <ul className="list-inside list-disc">{value.map((v, i) => <li key={i} className="break-all">{text(v)}</li>)}</ul>;
}

function Steps({ steps }: { steps: ActionStep[] }) {
  if (steps.length === 0) return null;
  return (
    <ol className="space-y-1 text-xs" aria-label="Steps">
      {steps.map((s, i) => {
        const Icon = STEP_ICON[s.status];
        return (
          <li key={`${s.step}-${i}`} className="flex items-start gap-1.5">
            <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${STEP_STYLE[s.status]}`} weight="fill" aria-hidden />
            <span className="min-w-0 break-words text-foreground">
              {s.step}: <strong className={`font-semibold ${STEP_STYLE[s.status]}`}>{STEP_WORD[s.status]}</strong>{s.detail ? ` (${s.detail})` : ''}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The exact parameters of a write the assistant proposes, with Confirm / Cancel. One click, then both buttons are gone. */
export function ConfirmActionCard({ ui, outcome, onSettle }: ConfirmActionCardProps) {
  const [clicked, setClicked] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const expiry = Date.parse(ui.expiresAt);
  const expired = !outcome && expiry <= now;
  const open = !outcome && !clicked && !expired;

  useEffect(() => {
    if (!open || Number.isNaN(expiry)) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [open, expiry]);

  const answer = async (decision: 'confirm' | 'cancel') => {
    if (clicked) return;
    setClicked(true);
    try {
      const response = await confirmAction({ confirmToken: ui.confirmToken, decision });
      const state = decision === 'cancel' ? 'cancelled' : response.ok ? 'confirmed' : 'failed';
      onSettle({ state, response });
    } catch (err) {
      onSettle({ state: 'failed', error: err instanceof Error ? err.message : 'The request failed' });
    }
  };

  const response = outcome?.response;
  const until = Number.isNaN(expiry) ? null : new Date(expiry).toLocaleTimeString();
  return (
    <section className="mt-3 space-y-3 rounded-xl border border-border bg-background/60 p-3" aria-label="Confirm action">
      {ui.action === 'start_pipeline' && (
        <h4 className="text-sm font-semibold text-foreground">Start or resume the pipeline for {str(ui.params.rfqId)}</h4>
      )}
      {ui.action === 'edit_value' && (
        <h4 className="text-sm font-semibold text-foreground">Change {str(ui.params.fieldLabel)} and regenerate the reports</h4>
      )}
      <p className="text-sm font-medium text-foreground">{ui.summary}</p>
      <dl className="grid grid-cols-1 gap-x-3 gap-y-1.5 text-xs sm:grid-cols-[max-content_1fr]">
        {rowsOf(ui).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="min-w-0 break-words text-foreground"><Value value={v} /></dd>
          </div>
        ))}
      </dl>
      {open && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => void answer('confirm')}>Confirm</Button>
          <Button size="sm" variant="outline" onClick={() => void answer('cancel')}>Cancel</Button>
          {until && <span className="text-xs text-muted-foreground">Valid until {until}</span>}
        </div>
      )}
      {clicked && !outcome && <p role="status" className="text-xs text-muted-foreground">Working on it…</p>}
      {expired && <p role="status" className="text-xs font-medium text-amber-700 dark:text-amber-400">Expired: this confirmation is no longer valid. Ask again to get a new one.</p>}
      {outcome && (
        <div role="status" className="space-y-2">
          <p className="text-xs font-medium text-foreground">
            {outcome.state === 'cancelled' && 'Cancelled: nothing was changed.'}
            {outcome.state === 'confirmed' && 'Confirmed.'}
            {outcome.state === 'failed' && `Not completed${outcome.error ? `: ${outcome.error}` : '.'}`}
          </p>
          {response?.message && <p className="break-words text-xs text-muted-foreground">{response.message}</p>}
          {response && <Steps steps={response.steps} />}
          {response?.ui?.type === 'open_export' && <OpenExportDirective rfqId={response.ui.rfqId} busy={false} />}
          {response?.rfqId && <p className="text-xs text-foreground">RFQ: <strong className="font-semibold">{response.rfqId}</strong></p>}
        </div>
      )}
    </section>
  );
}
