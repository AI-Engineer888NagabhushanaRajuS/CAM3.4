import { describe, it, expect } from 'vitest';
import { makeChatActions } from '../src/rfq-chat/rfq-chat-actions.js';
import { UnknownOutcomeError, hashParams, type ActionDeps, type AuditLine } from '../src/rfq-chat/rfq-chat-actions-types.js';
import type { RfqStatus } from '../src/rfq-chat/rfq-chat-status.js';

const running: RfqStatus = { rfqId: 'RFQ-00007', exists: true, customer: 'Centum', project: 'Alpha', started: true, stage: 3, reviewPending: false, finished: false, steps: [] };

function setup(state: Partial<RfqStatus> = {}, over: Partial<ActionDeps> = {}) {
  const calls: string[] = [];
  const audit: AuditLine[] = [];
  let now = Date.parse('2026-11-05T10:00:00Z');
  let n = 0;
  let current: RfqStatus = { ...running, ...state };
  const deps = {
    now: () => now,
    newToken: () => `tok-${++n}`,
    pipelineState: async () => current,
    startPipeline: async (id: string) => {
      calls.push(`start:${id}`);
      return { status: 'TRIGGERED' };
    },
    appendAudit: async (l: AuditLine) => {
      audit.push(l);
    },
    ...over,
  } as unknown as ActionDeps;
  const actions = makeChatActions({ getApiKey: () => null, getSelectedModel: () => null }, deps);
  return { actions, calls, audit, tick: (ms: number) => { now += ms; }, setState: (s: Partial<RfqStatus>) => { current = { ...current, ...s }; } };
}

type S = ReturnType<typeof setup>;
async function propose(s: S, session = 's1') {
  const out = await s.actions.proposeStartPipeline({ sessionKey: session, rfqId: 'RFQ-00007' });
  if (out.ui?.type !== 'confirm_action') {
    throw new Error(`no card: ${out.message}`);
  }
  return out.ui;
}
const confirm = (s: S, token: string, decision: 'confirm' | 'cancel' = 'confirm', session = 's1') =>
  s.actions.confirm({ sessionKey: session, req: { confirmToken: token, decision } });

describe('proposeStartPipeline', () => {
  it('returns a start_pipeline card with the exact params, a 5 minute expiry and no call to the service', async () => {
    const s = setup();
    const ui = await propose(s);
    expect(ui.action).toBe('start_pipeline');
    expect(ui.params).toEqual({ rfqId: 'RFQ-00007', stage: 3, customer: 'Centum', project: 'Alpha' });
    expect(ui.expiresAt).toBe('2026-11-05T10:05:00.000Z');
    expect(s.calls).toEqual([]);
    expect(s.audit.map((a) => a.action)).toEqual(['propose']);
  });

  it.each([
    ['an unknown RFQ', { exists: false, started: false }, "can't find"],
    ['an RFQ with no run yet', { started: false, stage: null }, 'no pipeline run yet'],
    ['a finished RFQ', { finished: true, stage: 9 }, 'already finished'],
    ['an RFQ waiting for a human review', { reviewPending: true }, 'waiting for a human review'],
  ])('refuses %s with a plain message, no card, no write', async (_name, state, text) => {
    const s = setup(state);
    const out = await s.actions.proposeStartPipeline({ sessionKey: 's1', rfqId: 'RFQ-00007' });
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain(text);
    expect(s.calls).toEqual([]);
  });

  it('the review refusal sends the user to the review screen', async () => {
    const out = await setup({ reviewPending: true }).actions.proposeStartPipeline({ sessionKey: 's1', rfqId: 'RFQ-00007' });
    expect(out.message).toContain('review screen');
  });

  it('a failing database check is reported and nothing is issued', async () => {
    const s = setup({}, { pipelineState: async () => { throw new Error('db down'); } });
    const out = await s.actions.proposeStartPipeline({ sessionKey: 's1', rfqId: 'RFQ-00007' });
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('db down');
  });
});

describe('confirm start_pipeline', () => {
  it('Confirm resumes through the same endpoint, reports the steps and audits every one', async () => {
    const s = setup();
    const ui = await propose(s);
    const out = await confirm(s, ui.confirmToken);
    expect(out).toMatchObject({ ok: true, rfqId: 'RFQ-00007' });
    expect(out.steps.map((x) => `${x.step}:${x.status}`)).toEqual(['check_state:done', 'start_pipeline:done']);
    expect(s.calls).toEqual(['start:RFQ-00007']);
    expect(s.audit.map((a) => a.action)).toEqual(['propose', 'confirm.start', 'start_pipeline.check_state', 'start_pipeline.start_pipeline']);
    const hash = hashParams(ui.params);
    expect(s.audit.every((a) => a.paramHash === hash)).toBe(true);
    expect(s.audit.every((a) => a.who === 's1' && !Number.isNaN(Date.parse(a.when)))).toBe(true);
    expect(JSON.stringify(s.audit)).not.toContain('tok-1'); // the token is a secret: never in the log
  });

  it('Cancel starts nothing and says so', async () => {
    const s = setup();
    const ui = await propose(s);
    const out = await confirm(s, ui.confirmToken, 'cancel');
    expect(out).toMatchObject({ ok: true, steps: [] });
    expect(out.message).toContain('Nothing was started');
    expect(s.calls).toEqual([]);
  });

  it('the token is single use: a second Confirm is refused and calls nothing', async () => {
    const s = setup();
    const ui = await propose(s);
    await confirm(s, ui.confirmToken);
    const again = await confirm(s, ui.confirmToken);
    expect(again.ok).toBe(false);
    expect(again.message).toContain('unknown, already used or expired');
    expect(s.calls).toHaveLength(1);
  });

  it('another session cannot use or burn the card', async () => {
    const s = setup();
    const ui = await propose(s);
    const other = await confirm(s, ui.confirmToken, 'confirm', 's2');
    expect(other.message).toContain('another session');
    expect(other.message).toContain('Nothing was started');
    expect(s.calls).toEqual([]);
    expect((await confirm(s, ui.confirmToken)).ok).toBe(true); // the owner still can
  });

  it('expires after 5 minutes', async () => {
    const s = setup();
    const ui = await propose(s);
    s.tick(5 * 60 * 1000 + 1);
    const out = await confirm(s, ui.confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('expired');
    expect(s.calls).toEqual([]);
  });

  it('tampered params from the client are refused', async () => {
    const s = setup();
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm', params: { ...ui.params, rfqId: 'RFQ-00099' } } as never });
    expect(out.ok).toBe(false);
    expect(out.message).toContain('parameters changed');
    expect(s.calls).toEqual([]);
    expect(s.audit.map((a) => a.action)).toContain('confirm.refused');
  });

  it('no audit trail, no start', async () => {
    let calls = 0;
    const s = setup({}, { appendAudit: async () => { if (++calls > 1) { throw new Error('disk full'); } } });
    const ui = await propose(s);
    const out = await confirm(s, ui.confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('audit log is not writable');
    expect(s.calls).toEqual([]);
  });

  it('a card that went stale (the RFQ now waits for a review) refuses at confirm and starts nothing', async () => {
    const s = setup();
    const ui = await propose(s);
    s.setState({ reviewPending: true });
    const out = await confirm(s, ui.confirmToken);
    expect(out.ok).toBe(false);
    expect(out.steps).toMatchObject([{ step: 'check_state', status: 'failed' }]);
    expect(s.calls).toEqual([]);
  });

  it('a service that answers something other than TRIGGERED is a failed start, not a success', async () => {
    const s = setup({}, { startPipeline: async () => ({ status: 'ALREADY_PROCESSING' }) });
    const ui = await propose(s);
    const out = await confirm(s, ui.confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('ALREADY_PROCESSING');
    expect(out.message).toContain('was not resumed');
    expect(out.steps.at(-1)).toMatchObject({ step: 'start_pipeline', status: 'failed' });
  });

  it('TRIGGERED with outcome RESUMED or STARTED is reported as what the service did', async () => {
    const resumed = setup({}, { startPipeline: async () => ({ status: 'TRIGGERED', outcome: 'RESUMED' }) });
    const out = await confirm(resumed, (await propose(resumed)).confirmToken);
    expect(out.ok).toBe(true);
    expect(out.message).toContain('told to carry on');
    expect(out.steps.at(-1)?.detail).toContain('RESUMED');
    const started = setup({}, { startPipeline: async () => ({ status: 'TRIGGERED', outcome: 'STARTED' }) });
    expect((await confirm(started, (await propose(started)).confirmToken)).message).toContain('new run was started');
  });

  it.each(['RUNNING', 'COMPLETED', 'NOT_STARTED'])('TRIGGERED with outcome %s is a no-op: ok is false and the message says nothing was resumed', async (outcome) => {
    const s = setup({}, { startPipeline: async () => ({ status: 'TRIGGERED', outcome }) });
    const out = await confirm(s, (await propose(s)).confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('Nothing was resumed');
    expect(out.message).toContain(outcome);
    expect(out.steps.at(-1)).toMatchObject({ step: 'start_pipeline', status: 'failed' });
  });

  it('an outcome nobody knows is not reported as a resume', async () => {
    const s = setup({}, { startPipeline: async () => ({ status: 'TRIGGERED', outcome: 'WHATEVER' }) });
    const out = await confirm(s, (await propose(s)).confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain("can't say the pipeline was resumed");
  });

  it('an HTTP error says nothing was started; an unknown outcome says the run may have started', async () => {
    const http = setup({}, { startPipeline: async () => { throw new Error('the upload service answered HTTP 500'); } });
    const out1 = await confirm(http, (await propose(http)).confirmToken);
    expect(out1.message).toContain('Nothing was started');
    const lost = setup({}, { startPipeline: async () => { throw new UnknownOutcomeError('the upload service did not answer (timeout)'); } });
    const out2 = await confirm(lost, (await propose(lost)).confirmToken);
    expect(out2.message).toContain('may have received');
    expect(out2.message).not.toContain('Nothing was started');
  });

  it('two cards get two tokens; confirming one runs one start', async () => {
    const s = setup();
    const a = await propose(s);
    const b = await propose(s);
    expect(a.confirmToken).not.toBe(b.confirmToken);
    expect((await confirm(s, b.confirmToken)).ok).toBe(true);
    expect(s.calls).toEqual(['start:RFQ-00007']);
  });
});
