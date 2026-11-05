import { describe, it, expect, vi } from 'vitest';
import { chatReply, type ChatServiceDeps, type RfqSummary } from '../src/rfq-chat/rfq-chat-service.js';
import type { RfqEvidence } from '../src/rfq-chat/rfq-chat-client.js';
import type { ChatActionDeps } from '../src/rfq-chat/rfq-chat-contract.js';
import type { ChatMessage, ChatModel } from '../src/rfq-chat/rfq-chat-types.js';

const cite = (label: string) => ({ sourceType: 'excel_export' as const, label, identifier: { sheet: label } });
const row = (label: string, text: string, score = 5) => ({ text, citation: cite(label), score });
const evidence = (chunks: RfqEvidence['chunks'], over: Partial<RfqEvidence> = {}): RfqEvidence => ({
  chunks, namedIdentifiers: [], missingIdentifiers: [], matchedRows: chunks.length, rowsInResults: 100, workbook: 'X.xlsx', warning: null, ...over,
});

function scripted(...replies: Array<string | null>) {
  const calls: ChatMessage[][] = [];
  let i = 0;
  const model: ChatModel = {
    label: 'test-model',
    async complete(messages) {
      calls.push(messages);
      const text = replies[Math.min(i++, replies.length - 1)];
      return text === null ? null : { text, model: 'test-model' };
    },
  };
  return { model, calls };
}

const rfq = (n: number, over: Partial<RfqSummary> = {}): RfqSummary => ({
  rfqId: `RFQ-${String(n).padStart(5, '0')}`, customer: 'Centum', project: `P${n}`, stage: 3, reviewPending: false, ...over,
});
const two = [rfq(2), rfq(1)];

function deps(model: ChatModel, over: Partial<ChatServiceDeps> = {}): ChatServiceDeps & { listRfqs: ReturnType<typeof vi.fn> } {
  const listRfqs = vi.fn(async () => two);
  return { model: () => model, listRfqs, remember: vi.fn(), ...over } as ChatServiceDeps & { listRfqs: ReturnType<typeof vi.fn> };
}
const user = (content: string) => [{ role: 'user', content }];

describe('plain talk is a conversation, answered from the guide', () => {
  it('answers "HAI HOW TO USE THIS TOOL ?" from the guide with cited sections and no RFQ lookup', async () => {
    const { model, calls } = scripted('Hi! CAM 3.4 turns a customer BOM into a costed quote [1]. Ask about results and I open the RFQ picker [2].');
    const d = deps(model);
    const out = await chatReply({ rfqId: null, messages: user('HAI HOW TO USE THIS TOOL ?') }, d);
    expect(out.message).not.toContain('No relevant context');
    expect(out.message).toContain('costed quote');
    expect(out.citations.length).toBeGreaterThan(0);
    expect(out.citations.every((c) => c.label.startsWith('User guide: '))).toBe(true);
    expect(calls).toHaveLength(1);
    expect(d.listRfqs).not.toHaveBeenCalled();
    expect(out.ui).toBeUndefined();
  });

  it('shows the guide sections as written when the model is unreachable, never a canned line', async () => {
    const { model } = scripted(null);
    const out = await chatReply({ rfqId: null, messages: user('how do I create an RFQ?') }, deps(model));
    expect(out.message).toContain('Here is what the user guide says');
    expect(out.message).toContain('Create RFQ');
    expect(out.message).not.toContain('No relevant context');
    expect(out.model).toBeNull();
    expect(out.citations.map((c) => c.label).join('|')).toContain('Create an RFQ');
  });

  it('shows the guide when the model states a figure the guide does not contain', async () => {
    const { model, calls } = scripted('Uploading takes 45 minutes [1].');
    const out = await chatReply({ rfqId: null, messages: user('how do I upload the BOM file?') }, deps(model));
    expect(out.message).not.toContain('45 minutes');
    expect(out.message).toContain('Here is what the user guide says');
    expect(calls).toHaveLength(1);
  });

  it('answers a how-to even when an RFQ is chosen (the chat is not stuck on that RFQ)', async () => {
    const { model } = scripted('Open **Upload file** in the left pane [1].');
    const out = await chatReply({ rfqId: 'RFQ-00001', messages: user('how do I upload the BOM file?') }, deps(model));
    expect(out.citations[0].label).toMatch(/^User guide/);
    expect(out.scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-00001'] });
  });
});

describe('ordinary conversation: no RFQ data from the model', () => {
  it('lets the model chat and passes a reply with no data claims', async () => {
    const { model, calls } = scripted('Happy to help whenever you need me.');
    const out = await chatReply({ rfqId: null, messages: user('thanks!') }, deps(model));
    expect(out.message).toBe('Happy to help whenever you need me.');
    expect(out.model).toBe('test-model');
    expect(calls).toHaveLength(1);
    expect(calls[0][0].content).toContain('NO access to any RFQ');
  });

  it('regenerates once when the reply carries RFQ ids, part numbers or figures the user never wrote', async () => {
    const { model, calls } = scripted('Last time RFQ-00001 had UBR03225 at 5000 pieces.', 'Glad that helped.');
    const out = await chatReply({ rfqId: null, messages: user('ok cool') }, deps(model));
    expect(out.message).toBe('Glad that helped.');
    expect(calls).toHaveLength(2);
    expect(calls[1].at(-1)?.content).toContain('RFQ-00001');
  });

  it('withholds a reply that keeps stating data, and offers the RFQ picker', async () => {
    const { model, calls } = scripted('RFQ-00001 has an MOQ of 5000.', 'RFQ-00001 has an MOQ of 5000.');
    const out = await chatReply({ rfqId: null, messages: user('ok cool') }, deps(model));
    expect(out.message).not.toContain('MOQ of 5000.');
    expect(out.message).toContain('did not show it');
    expect(out.ui?.type).toBe('pick_rfq');
    expect(calls).toHaveLength(2);
  });

  it('treats the model handing the message back as an RFQ-data question', async () => {
    const { model, calls } = scripted('NEEDS_RFQ_DATA');
    const out = await chatReply({ rfqId: null, messages: user('so what came of it') }, deps(model));
    expect(out.ui?.type).toBe('pick_rfq');
    expect(calls).toHaveLength(1);
  });

  it('says plainly when the model is down, without inventing an answer', async () => {
    const { model } = scripted(null);
    const out = await chatReply({ rfqId: null, messages: user('thanks!') }, deps(model));
    expect(out.message).toContain("isn't reachable");
    expect(out.model).toBeNull();
  });
});

describe('a data question needs a scope', () => {
  it('with no scope opens the RFQ picker from the database list, without asking a model', async () => {
    const { model, calls } = scripted('x');
    const withExports = vi.fn(async (r: RfqSummary[]) => r.map((x) => ({ ...x, hasExport: x.rfqId === 'RFQ-00001' })));
    const out = await chatReply({ rfqId: null, messages: user('what is the go / no-go status?') }, deps(model, { withExports }));
    expect(out.ui?.type).toBe('pick_rfq');
    if (out.ui?.type === 'pick_rfq') {
      expect(out.ui.options.map((o) => [o.rfqId, o.hasExport])).toEqual([['RFQ-00002', false], ['RFQ-00001', true]]);
      expect(out.ui.allowAll && out.ui.allowMultiple).toBe(true);
    }
    expect(out.message).toContain('Which RFQ do you mean?');
    expect(out.scope).toEqual({ mode: 'none' });
    expect(calls).toHaveLength(0);
  });

  it('says there are no RFQs when the list is empty instead of opening an empty picker', async () => {
    const { model } = scripted('x');
    const out = await chatReply({ rfqId: null, messages: user('status of the report') }, deps(model, { listRfqs: async () => [] }));
    expect(out.message).toContain('no RFQs yet');
    expect(out.ui).toBeUndefined();
  });

  it('one RFQ in scope goes through the grounded flow, unchanged', async () => {
    const { model, calls } = scripted('UBR03225 has an MOQ of 5000 [1].');
    const retrieve = vi.fn(async () => evidence([row('CBOM!A5:E5', 'CBOM, row 5: Part Number=UBR03225; MOQ=5000')]));
    const out = await chatReply({ rfqId: null, scope: { mode: 'rfqs', rfqIds: ['RFQ-00001'] }, messages: user('MOQ of UBR03225?') }, deps(model, { retrieve }));
    expect(out.rfq_id).toBe('RFQ-00001');
    expect(out.message).toBe('UBR03225 has an MOQ of 5000 (CBOM!A5:E5).');
    expect(out.scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-00001'] });
    expect(retrieve).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(1);
  });

  it('the per-RFQ route (rfqId in the URL) is the same as a one-RFQ scope', async () => {
    const { model } = scripted('UBR03225 has an MOQ of 5000 [1].');
    const retrieve = vi.fn(async () => evidence([row('CBOM!A5:E5', 'CBOM, row 5: Part Number=UBR03225; MOQ=5000')]));
    const out = await chatReply({ rfqId: 'RFQ-00002', messages: user('MOQ of UBR03225?') }, deps(model, { retrieve }));
    expect(out.rfq_id).toBe('RFQ-00002');
    expect(retrieve).toHaveBeenCalledWith(expect.objectContaining({ rfqId: 'RFQ-00002' }));
  });

  it('an RFQ the question names beats the chips', async () => {
    const { model } = scripted('UBR03225 has an MOQ of 5000 [1].');
    const retrieve = vi.fn(async () => evidence([row('CBOM!A5:E5', 'CBOM, row 5: Part Number=UBR03225; MOQ=5000')]));
    const out = await chatReply({ rfqId: null, scope: { mode: 'all' }, messages: user('In rfq-00001 what is the MOQ of UBR03225?') }, deps(model, { retrieve }));
    expect(out.rfq_id).toBe('RFQ-00001');
    expect(out.scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-00001'] });
  });
});

describe('several RFQs and All context: a per-RFQ table, no model', () => {
  const byRfq: Record<string, RfqEvidence | null> = {
    'RFQ-00001': evidence([row('CBOM!A5:E5', 'CBOM, row 5: Part Number=UBR03225; Supplier=YAGEO; MOQ=5000; Lead Time=22')]),
    'RFQ-00002': evidence([row('CBOM!A9:E9', 'CBOM, row 9: Part Number=UBR03226; Supplier=MURATA; MOQ=7000; Lead Time=9')]),
  };
  const retrieve = vi.fn(async (p: { rfqId: string }) => byRfq[p.rfqId] ?? null);

  it('answers a chosen set as a table with the RFQ id in each citation', async () => {
    const { model, calls } = scripted('x');
    const out = await chatReply({ rfqId: null, scope: { mode: 'rfqs', rfqIds: ['RFQ-00001', 'RFQ-00002'] }, messages: user('which suppliers are used?') }, deps(model, { retrieve }));
    expect(out.message).toContain('| RFQ-00001 |');
    expect(out.message).toContain('Supplier=YAGEO');
    expect(out.message).toContain('| RFQ-00002 |');
    expect(out.citations.map((c) => c.label)).toEqual(['RFQ-00001 · CBOM!A5:E5', 'RFQ-00002 · CBOM!A9:E9']);
    expect(out.scope).toEqual({ mode: 'rfqs', rfqIds: ['RFQ-00001', 'RFQ-00002'] });
    expect(out.rfq_id).toBeNull();
    expect(out.ui).toBeUndefined();
    expect(calls).toHaveLength(0);
  });

  it('All context spans every RFQ in the list', async () => {
    const { model } = scripted('x');
    const out = await chatReply({ rfqId: null, scope: { mode: 'all' }, messages: user('which suppliers are used?') }, deps(model, { retrieve }));
    expect(out.message).toContain('Across all 2 RFQs');
    expect(out.scope).toEqual({ mode: 'all' });
    expect(out.citations).toHaveLength(2);
  });

  it('shows an RFQ the results service cannot read as such, not as an empty answer', async () => {
    const { model } = scripted('x');
    const partial = vi.fn(async (p: { rfqId: string }) => (p.rfqId === 'RFQ-00001' ? byRfq['RFQ-00001'] : null));
    const out = await chatReply({ rfqId: null, scope: { mode: 'all' }, messages: user('which suppliers are used?') }, deps(model, { retrieve: partial }));
    expect(out.message).toContain('| RFQ-00002 | Results service not reachable | - |');
  });

  it('above 25 RFQs asks the user to narrow and queries nothing', async () => {
    const { model, calls } = scripted('x');
    const many = Array.from({ length: 26 }, (_, i) => rfq(i + 1));
    const spy = vi.fn(async () => null);
    const out = await chatReply({ rfqId: null, scope: { mode: 'all' }, messages: user('which suppliers are used?') }, deps(model, { listRfqs: async () => many, retrieve: spy }));
    expect(out.message).toContain('at most 25');
    expect(out.ui?.type).toBe('pick_rfq');
    expect(spy).not.toHaveBeenCalled();
    expect(calls).toHaveLength(0);
  });

  it('a part in two RFQs with different values is a conflict: both sides cited, the user chooses', async () => {
    const { model, calls } = scripted('x');
    const conflicting = vi.fn(async (p: { rfqId: string }) => evidence([
      row(`CBOM!${p.rfqId}`, `CBOM, row 5: Part Number=UBR03225; MOQ=${p.rfqId === 'RFQ-00001' ? 5000 : 7000}`),
    ]));
    const out = await chatReply({ rfqId: null, scope: { mode: 'all' }, messages: user('MOQ of UBR03225?') }, deps(model, { retrieve: conflicting }));
    expect(out.message).toContain('The results disagree');
    expect(out.message).toMatch(/\| UBR03225 \| MOQ \| RFQ-00001 \| 5000 \|/);
    expect(out.message).toMatch(/\| UBR03225 \| MOQ \| RFQ-00002 \| 7000 \|/);
    expect(out.citations.map((c) => c.label)).toEqual(expect.arrayContaining(['RFQ-00001 · CBOM!RFQ-00001', 'RFQ-00002 · CBOM!RFQ-00002']));
    expect(out.ui?.type).toBe('disambiguate');
    if (out.ui?.type === 'disambiguate') expect(out.ui.options.map((o) => o.id).sort()).toEqual(['RFQ-00001', 'RFQ-00002']);
    expect(calls).toHaveLength(0);
  });

  it('a question naming two RFQs shows both and offers to continue with one', async () => {
    const { model } = scripted('x');
    const out = await chatReply({ rfqId: null, messages: user('compare the suppliers in RFQ-00001 and RFQ-00002') }, deps(model, { retrieve }));
    expect(out.message).toContain('| RFQ-00001 |');
    expect(out.message).toContain('| RFQ-00002 |');
    expect(out.ui?.type).toBe('disambiguate');
  });

  it('an RFQ id that does not exist is stated, with the real ones to choose from', async () => {
    const { model } = scripted('x');
    const out = await chatReply({ rfqId: null, messages: user('status of RFQ-99999?') }, deps(model, { retrieve }));
    expect(out.message).toContain("can't find `RFQ-99999`");
    expect(out.ui?.type).toBe('disambiguate');
    if (out.ui?.type === 'disambiguate') expect(out.ui.options.map((o) => o.id)).toEqual(['RFQ-00002', 'RFQ-00001']);
    expect(retrieve).not.toHaveBeenCalledWith(expect.objectContaining({ rfqId: 'RFQ-99999' }));
  });

  it('refuses a part number that none of the RFQs has, without a model and without a figure', async () => {
    const { model, calls } = scripted('UBR99999 costs 5');
    const none = vi.fn(async () => evidence([row('CBOM!A5:E5', 'CBOM, row 5: Part Number=UBR03225; MOQ=5000')], { namedIdentifiers: ['ubr99999'], missingIdentifiers: ['ubr99999'] }));
    const out = await chatReply({ rfqId: null, scope: { mode: 'all' }, messages: user('price of UBR99999?') }, deps(model, { retrieve: none }));
    expect(out.message).toContain("can't find `UBR99999`");
    expect(out.message).not.toMatch(/MOQ|5000/);
    expect(out.citations).toEqual([]);
    expect(calls).toHaveLength(0);
  });
});

describe('create-RFQ intent goes to the action path, never writes in the chat', () => {
  const card = { type: 'confirm_action' as const, action: 'create_rfq' as const, summary: 's', params: { rfqId: 'RFQ-00003' }, confirmToken: 't', expiresAt: '2026-11-05T12:00:00Z' };

  it('asks the action service with the session and the attached files, and returns its card', async () => {
    const { model, calls } = scripted('x');
    const proposeCreateRfq = vi.fn(async () => ({ message: 'Ready to create RFQ-00003.', ui: card }));
    const actions: ChatActionDeps = { proposeCreateRfq, proposeStartPipeline: vi.fn(), confirm: vi.fn() };
    const fileRefs = [{ attachmentId: 'a1', name: 'bom.xlsx' }];
    const out = await chatReply({ rfqId: null, fileRefs, messages: user('create an RFQ from this BOM for Centum, project Alpha') }, deps(model, { actions, sessionKey: 'tester@x' }));
    expect(proposeCreateRfq).toHaveBeenCalledWith({ sessionKey: 'tester@x', request: 'create an RFQ from this BOM for Centum, project Alpha', fileRefs });
    expect(out.ui).toEqual(card);
    expect(out.message).toBe('Ready to create RFQ-00003.');
    expect(calls).toHaveLength(0);
    expect(actions.confirm).not.toHaveBeenCalled();
  });

  it('passes the action service its refusal or question as the message', async () => {
    const { model } = scripted('x');
    const actions: ChatActionDeps = { proposeCreateRfq: async () => ({ message: 'To create the RFQ I still need the customer.' }), proposeStartPipeline: vi.fn(), confirm: vi.fn() };
    const out = await chatReply({ rfqId: null, messages: user('make a new RFQ') }, deps(model, { actions }));
    expect(out.message).toContain('still need the customer');
    expect(out.ui).toBeUndefined();
  });

  it('says it cannot when no action service is wired', async () => {
    const { model } = scripted('x');
    const out = await chatReply({ rfqId: null, messages: user('create an RFQ from this file') }, deps(model));
    expect(out.message).toContain('not available here');
  });
});

it('rejects a request with no user message', async () => {
  await expect(chatReply({ rfqId: null, messages: [] }, deps(scripted('x').model))).rejects.toThrow('No user message found');
});
