import { describe, it, expect, vi } from 'vitest';
import { chatReply, type ChatServiceDeps, type RfqSummary } from '../src/rfq-chat/rfq-chat-service.js';
import type { ChatActionDeps, UiDirective } from '../src/rfq-chat/rfq-chat-contract.js';
import type { RfqStatus } from '../src/rfq-chat/rfq-chat-status.js';
import type { ChatModel } from '../src/rfq-chat/rfq-chat-types.js';

const rfq = (id: string, over: Partial<RfqSummary> = {}): RfqSummary => ({ rfqId: id, customer: 'Centum', project: 'Alpha', stage: 3, reviewPending: false, ...over });
const RFQS = [rfq('RFQ-00007'), rfq('RFQ-00008', { reviewPending: true })];
const state = (id: string, over: Partial<RfqStatus> = {}): RfqStatus => ({
  rfqId: id, exists: true, customer: 'Centum', project: 'Alpha', started: true, stage: 3, reviewPending: false, finished: false,
  steps: [{ name: 'Standardize BOM', state: 'done' }, { name: 'Fetch prices', state: 'running' }], ...over,
});

/** A model that is never reachable: the controls must not need it. */
const noModel = () => {
  const complete = vi.fn(async () => null);
  return { model: { label: 'none', complete } as ChatModel, complete };
};

function setup(over: Partial<ChatServiceDeps> = {}) {
  const { model, complete } = noModel();
  const proposeStartPipeline = vi.fn(async ({ rfqId }: { rfqId: string }) => ({
    message: `${rfqId} is at stage 3 of 9. Press Confirm.`,
    ui: { type: 'confirm_action', action: 'start_pipeline', summary: 's', params: { rfqId }, confirmToken: 'tk', expiresAt: 'x' } as UiDirective | undefined,
  }));
  const actions: ChatActionDeps = { proposeCreateRfq: vi.fn(), proposeStartPipeline, confirm: vi.fn() };
  const pipelineStatus = vi.fn(async (id: string) => state(id));
  const deps = { model: () => model, listRfqs: vi.fn(async () => RFQS), actions, sessionKey: 'u@x', pipelineStatus, ...over } as ChatServiceDeps;
  return { deps, complete, proposeStartPipeline, pipelineStatus };
}
const ask = (text: string, deps: ChatServiceDeps, scope?: string[]) =>
  chatReply({ rfqId: null, scope: scope ? { mode: 'rfqs', rfqIds: scope } : undefined, messages: [{ role: 'user', content: text }] }, deps);

describe('open', () => {
  it('"open RFQ-00007" hands the UI an open_rfq button and calls no model', async () => {
    const t = setup();
    const out = await ask('open RFQ-00007', t.deps);
    expect(out.ui).toEqual({ type: 'open_rfq', rfqId: 'RFQ-00007' });
    expect(out.rfq_id).toBe('RFQ-00007');
    expect(out.message).toContain('I do not change the screen myself');
    expect(t.complete).not.toHaveBeenCalled();
  });

  it('an unknown RFQ id goes to the existing disambiguate flow', async () => {
    const out = await ask('open RFQ-99999', setup().deps);
    expect(out.message).toContain('RFQ-99999');
    expect(out.ui).toMatchObject({ type: 'disambiguate' });
    expect(out.scope).toEqual({ mode: 'none' });
  });
});

describe('status (pipeline, from the database)', () => {
  it('"what stage is RFQ-00007 at?" answers stage n of 9, review and rows with no model', async () => {
    const t = setup();
    const out = await ask('what stage is RFQ-00007 at?', t.deps);
    expect(out.message).toContain('stage 3 of 9 (Get online pricing)');
    expect(out.message).toContain('Review pending: no.');
    expect(out.message).toContain('[DONE] Standardize BOM');
    expect(out.message).toContain('[RUNNING] Fetch prices');
    expect(t.complete).not.toHaveBeenCalled();
    expect(t.pipelineStatus).toHaveBeenCalledWith('RFQ-00007');
  });

  it('the single scoped RFQ counts as "the RFQ" when the message names none', async () => {
    const t = setup();
    const out = await ask('what stage is it at?', t.deps, ['RFQ-00008']);
    expect(t.pipelineStatus).toHaveBeenCalledWith('RFQ-00008');
    expect(out.rfq_id).toBe('RFQ-00008');
  });

  it('with no RFQ named and none scoped it asks which one, by the choice buttons', async () => {
    const out = await ask('is it stuck?', setup().deps);
    expect(out.ui).toMatchObject({ type: 'disambiguate' });
  });

  it('a list question over several RFQs is left to the data path (RFQ picker)', async () => {
    const out = await ask('which RFQs are waiting for review?', setup().deps);
    expect(out.ui).toMatchObject({ type: 'pick_rfq' });
  });

  it('says plainly when the status cannot be read, never invents one', async () => {
    const out = await ask('what stage is RFQ-00007 at?', setup({ pipelineStatus: undefined }).deps);
    expect(out.message).toContain("can't read the pipeline status");
  });
});

describe('workbook questions still go to the data path', () => {
  it('"what is the go / no-go status?" with no scope opens the picker, not a status answer', async () => {
    const t = setup();
    const out = await ask('what is the go / no-go status?', t.deps);
    expect(out.ui).toMatchObject({ type: 'pick_rfq' });
    expect(t.pipelineStatus).not.toHaveBeenCalled();
  });

  it('"what is the total spend?" and "show me the total export cost" are not controls', async () => {
    const t = setup();
    expect((await ask('what is the total spend', t.deps)).ui).toMatchObject({ type: 'pick_rfq' });
    expect((await ask('show me the total export cost', t.deps)).ui).toMatchObject({ type: 'pick_rfq' });
    expect(t.pipelineStatus).not.toHaveBeenCalled();
  });
});

describe('resume / start (a write: only a confirmation card)', () => {
  it('asks the action service for a card for the named RFQ and returns it unchanged', async () => {
    const t = setup();
    const out = await ask('resume the pipeline for RFQ-00007', t.deps);
    expect(t.proposeStartPipeline).toHaveBeenCalledWith({ sessionKey: 'u@x', rfqId: 'RFQ-00007' });
    expect(out.ui).toMatchObject({ type: 'confirm_action', action: 'start_pipeline', confirmToken: 'tk' });
    expect(t.complete).not.toHaveBeenCalled();
  });

  it('uses the scoped RFQ when none is named', async () => {
    const t = setup();
    await ask('continue the pipeline', t.deps, ['RFQ-00008']);
    expect(t.proposeStartPipeline).toHaveBeenCalledWith({ sessionKey: 'u@x', rfqId: 'RFQ-00008' });
  });

  it('relays the action service refusal as a plain message with no directive', async () => {
    const t = setup();
    t.proposeStartPipeline.mockResolvedValueOnce({ message: 'RFQ-00008 is waiting for a human review. Resolve it in the right pane.', ui: undefined });
    const out = await ask('start the pipeline for RFQ-00008', t.deps);
    expect(out.message).toContain('waiting for a human review');
    expect(out.ui).toBeUndefined();
  });

  it('an unknown RFQ never reaches the action service', async () => {
    const t = setup();
    const out = await ask('start the pipeline for RFQ-99999', t.deps);
    expect(t.proposeStartPipeline).not.toHaveBeenCalled();
    expect(out.ui).toMatchObject({ type: 'disambiguate' });
  });

  it('two RFQs named: asks which, starts nothing', async () => {
    const t = setup();
    const out = await ask('resume RFQ-00007 and RFQ-00008', t.deps);
    expect(t.proposeStartPipeline).not.toHaveBeenCalled();
    expect(out.ui).toMatchObject({ type: 'disambiguate' });
  });

  it('without an action service it says so and does nothing', async () => {
    const out = await ask('resume the pipeline for RFQ-00007', setup({ actions: undefined }).deps);
    expect(out.message).toContain('not available here');
    expect(out.ui).toBeUndefined();
  });

  it('"create an RFQ and start the pipeline" is still the create action', async () => {
    const t = setup();
    (t.deps.actions!.proposeCreateRfq as ReturnType<typeof vi.fn>).mockResolvedValue({ message: 'need customer' });
    await ask('create an RFQ and start the pipeline', t.deps);
    expect(t.deps.actions!.proposeCreateRfq).toHaveBeenCalled();
    expect(t.proposeStartPipeline).not.toHaveBeenCalled();
  });
});

describe('export', () => {
  it('opens the downloads when the RFQ has an export', async () => {
    const withExports = vi.fn(async (r: RfqSummary[]) => r.map((x) => ({ ...x, hasExport: true })));
    const out = await ask('export the reports for RFQ-00007', setup({ withExports }).deps);
    expect(out.ui).toEqual({ type: 'open_export', rfqId: 'RFQ-00007' });
    expect(withExports).toHaveBeenCalledWith([expect.objectContaining({ rfqId: 'RFQ-00007' })]);
  });

  it('says none exists yet, with no button, when it has none', async () => {
    const withExports = vi.fn(async (r: RfqSummary[]) => r.map((x) => ({ ...x, hasExport: false })));
    const out = await ask('download the workbook', setup({ withExports }).deps, ['RFQ-00007']);
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('no exported reports yet');
  });
});

describe('upload and settings', () => {
  it('"upload a file" gives the ask_upload button with the accepted types and mentions both engines', async () => {
    const t = setup();
    const out = await ask('upload a file', t.deps);
    expect(out.ui).toMatchObject({ type: 'ask_upload', accept: ['.xlsx', '.xls', '.csv', '.pdf', '.docx', '.txt'] });
    expect(out.message).toContain('Both security engines');
    expect(t.deps.listRfqs).not.toHaveBeenCalled();
    expect(t.complete).not.toHaveBeenCalled();
  });

  it('an upload together with a create request stays the create action', async () => {
    const t = setup();
    (t.deps.actions!.proposeCreateRfq as ReturnType<typeof vi.fn>).mockResolvedValue({ message: 'need files' });
    const out = await ask('upload this file and create the rfq', t.deps);
    expect(out.message).toBe('need files');
  });

  it('settings: open_settings button plus the line about the header switch', async () => {
    const out = await ask('use my openrouter api key', setup().deps);
    expect(out.ui).toEqual({ type: 'open_settings', section: 'providers' });
    expect(out.message).toContain('Local / OpenRouter / Auto switch is in the assistant header');
  });
});

describe('how-to and help still come from the guide', () => {
  it('"what can you do" is answered from the guide section on the controls', async () => {
    const out = await ask('what can you do', setup().deps); // model unreachable: the sections are shown as written
    expect(out.message).toContain('What the assistant can do for you');
    expect(out.message).toContain('Resume or start the pipeline');
    expect(out.citations.map((c) => c.label).join('|')).toContain('What the assistant can do for you');
  });

  it('"how do I export the reports" is a how-to, not a download', async () => {
    const out = await ask('how do I export the reports', setup().deps);
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('user guide');
  });
});
