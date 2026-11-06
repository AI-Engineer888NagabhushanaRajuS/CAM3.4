/**
 * The start_pipeline action: "resume / start the pipeline of RFQ-x" from the chat. planStartPipeline decides, from the
 * database, whether a confirmation card may be issued (refusals are plain messages and write nothing);
 * runStartPipeline is what Confirm runs: the same GET /api/dify/start/{rfqId} the left pane makes when it reopens an RFQ.
 * Token, session binding, param hash and the audit lines are shared with create_rfq (rfq-chat-actions.ts).
 */
import type { ActionConfirmResponse } from './rfq-chat-contract.js';
import { UnknownOutcomeError, type ActionDeps, type StartPipelineParams } from './rfq-chat-actions-types.js';
import { STAGE_NAMES, type RfqStatus } from './rfq-chat-status.js';

type Step = ActionConfirmResponse['steps'][number];

/** Why a start is refused right now, or null when it may go ahead. Used when proposing and again when confirming. */
// What the Temporal resume says it did (temporal_worker/client.py resume_rfq_workflow): TRIGGERED alone does not mean anything ran.
const OUTCOME_OK: Record<string, string> = {
  RESUMED: 'the parked run was told to carry on',
  STARTED: 'the previous run had ended, so a new run was started; it continues at the next skill',
};
const OUTCOME_NOOP: Record<string, string> = {
  RUNNING: 'the run is already running a step, so nothing was sent',
  COMPLETED: 'every skill already ran, so nothing was started',
  NOT_STARTED: 'no run was ever started for this RFQ, so there is nothing to resume',
};

export function startRefusal(s: RfqStatus): string | null {
  if (!s.exists) {
    return `I can't find ${s.rfqId} in the database, so I can't start anything.`;
  }
  if (!s.started) {
    return `${s.rfqId} has no pipeline run yet (no files were uploaded), so there is nothing to start or resume. Upload the BOM and Volume files first.`;
  }
  if (s.finished) {
    return `${s.rfqId} has already finished the pipeline (stage ${s.stage ?? 9} of 9), so there is nothing to resume. Ask me to export its reports if you want them.`;
  }
  if (s.reviewPending) {
    return `${s.rfqId} is waiting for a human review (stage ${s.stage ?? '?'} of 9). Resolve it on the review screen in the right pane and the same run continues; I did not start anything.`;
  }
  return null;
}

export async function planStartPipeline(
  deps: ActionDeps,
  rfqId: string,
): Promise<{ message: string; params?: StartPipelineParams; summary?: string }> {
  const s = await deps.pipelineState(rfqId);
  const refusal = startRefusal(s);
  if (refusal) {
    return { message: refusal };
  }
  const at = s.stage === null ? 'an unknown stage' : `stage ${s.stage} of 9 (${STAGE_NAMES[s.stage - 1]})`;
  return {
    message: `${rfqId} is at ${at}. Check the details and press Confirm to resume its pipeline; nothing happens until you do.`,
    params: { rfqId, stage: s.stage, customer: s.customer, project: s.project },
    summary: `Resume the pipeline of ${rfqId} (currently ${at}), the same as reopening it in the left pane.`,
  };
}

export async function runStartPipeline(
  deps: ActionDeps,
  p: StartPipelineParams,
  audit: (action: string, result: string) => Promise<void>,
): Promise<ActionConfirmResponse> {
  const steps: Step[] = [];
  const stop = async (name: string, why: string, message: string): Promise<ActionConfirmResponse> => {
    steps.push({ step: name, status: 'failed', detail: why });
    await audit(`start_pipeline.${name}`, `failed: ${why}`);
    return { ok: false, rfqId: p.rfqId, message, steps };
  };

  // The card may be minutes old: look again before touching anything.
  let refusal: string | null;
  try {
    refusal = startRefusal(await deps.pipelineState(p.rfqId));
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err);
    return stop('check_state', why, `Stopped at check_state: ${why}. Nothing was started.`);
  }
  if (refusal) {
    return stop('check_state', refusal, `Stopped: ${refusal}`);
  }
  steps.push({ step: 'check_state', status: 'done', detail: 'active run, not finished, no review pending' });
  await audit('start_pipeline.check_state', 'done');

  try {
    const { status, outcome } = await deps.startPipeline(p.rfqId);
    if (status !== 'TRIGGERED' && status !== 'SUCCESS') {
      return stop('start_pipeline', `the service answered ${status || 'no status'}`, `Stopped at start_pipeline: the service answered ${status || 'no status'}, so the pipeline was not resumed.`);
    }
    const noop = outcome ? OUTCOME_NOOP[outcome] : undefined;
    if (outcome && !OUTCOME_OK[outcome] && !noop) {
      return stop('start_pipeline', `unrecognised outcome ${outcome}`, `Stopped at start_pipeline: the service answered ${status} with the outcome ${outcome}, which I do not recognise, so I can't say the pipeline was resumed. Check ${p.rfqId} in the right pane.`);
    }
    if (noop) {
      return stop('start_pipeline', `${outcome}: ${noop}`, `Nothing was resumed: ${noop} (${outcome}).`);
    }
    const detail = outcome ? `${outcome}: ${OUTCOME_OK[outcome]}` : status;
    steps.push({ step: 'start_pipeline', status: 'done', detail });
    await audit('start_pipeline.start_pipeline', `done: ${detail}`);
    return { ok: true, rfqId: p.rfqId, message: `Resumed ${p.rfqId}: ${outcome ? OUTCOME_OK[outcome] : `the service answered ${status}`}. Follow the steps in the right pane.`, steps };
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err);
    if (err instanceof UnknownOutcomeError) {
      return stop('start_pipeline', why, `Stopped at start_pipeline: ${why}. The service may have received the request, so check ${p.rfqId} in the right pane before asking again.`);
    }
    return stop('start_pipeline', why, `Stopped at start_pipeline: ${why}. Nothing was started.`);
  }
}
