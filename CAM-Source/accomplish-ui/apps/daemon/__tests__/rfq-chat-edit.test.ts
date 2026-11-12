import { describe, it, expect, vi } from 'vitest';
import { makeChatActions } from '../src/rfq-chat/rfq-chat-actions.js';
import { UnknownOutcomeError, hashParams, type ActionDeps, type AuditLine, type BomRow, type EditResult } from '../src/rfq-chat/rfq-chat-actions-types.js';
import { coerceValue, parseEdit, resolveField, isEditRequest } from '../src/rfq-chat/rfq-chat-edit-fields.js';
import { classify } from '../src/rfq-chat/rfq-chat-intent.js';
import { chatReply, type ChatServiceDeps, type RfqSummary } from '../src/rfq-chat/rfq-chat-service.js';
import type { ManifestTree } from '../src/rfq-chat/rfq-chat-manifests.js';
import type { ChatModel } from '../src/rfq-chat/rfq-chat-types.js';

const row = (id: string, cpn: string, over: Partial<BomRow['values']> = {}, fg = 'FG1', volumeNo = 1): BomRow => ({
  bomItemId: id, volumeNo, cpn, mpn: `MPN-${cpn}`, fg, description: 'Resistor', values: { final_moq: 100, final_supp_name: 'Mouser', final_price_conv: 0.45, ...over },
});
const OK: EditResult = { applied: 1, before: { filename: 'CBOM_v1.xlsx' }, after: { filename: 'CBOM_v2.xlsx' }, diff: { total_changed_cells: 14, sheets: [{ sheet: 'CBOM', changed: 9 }, { sheet: 'Summary', changed: 5 }, { sheet: 'Manifest', changed: 0 }] } };

function setup(rows: BomRow[] = [row('b1', 'PN-100')], over: Partial<ActionDeps> = {}) {
  const calls: unknown[] = [];
  const audit: AuditLine[] = [];
  let now = Date.parse('2026-11-05T10:00:00Z');
  let n = 0;
  let current = rows;
  const deps = {
    now: () => now,
    newToken: () => `tok-${++n}`,
    findBomRows: async (_r: string, t: string) => current.filter((x) => [x.bomItemId, x.cpn, x.mpn].some((v) => v.toLowerCase() === t.toLowerCase())),
    editAndRegenerate: async (...a: unknown[]) => { calls.push(a); return OK; },
    appendAudit: async (l: AuditLine) => { audit.push(l); },
    ...over,
  } as unknown as ActionDeps;
  const actions = makeChatActions({ getApiKey: () => null, getSelectedModel: () => null }, deps);
  return { actions, calls, audit, tick: (ms: number) => { now += ms; }, setRows: (r: BomRow[]) => { current = r; } };
}
type S = ReturnType<typeof setup>;
const propose = (s: S, value = '500', target = 'PN-100', field = 'moq', session = 's1') => s.actions.proposeEditValue({ sessionKey: session, rfqId: 'RFQ-00007', target, fieldText: field, value });
async function card(s: S, value?: string) {
  const out = await propose(s, value);
  if (out.ui?.type !== 'confirm_action') throw new Error(`no card: ${out.message}`);
  return out.ui;
}
const confirm = (s: S, token: string, decision: 'confirm' | 'cancel' = 'confirm', session = 's1') => s.actions.confirm({ sessionKey: session, req: { confirmToken: token, decision } });

describe('edit fields and sentence parsing', () => {
  it('reads the sentence, with the RFQ anywhere and a part prefix', () => {
    expect(parseEdit('set the MOQ of PN-100 to 500 in RFQ-00007')).toEqual({ fieldText: 'MOQ', target: 'PN-100', value: '500' });
    expect(parseEdit('For RFQ-00007 please change lead time for part number ABC-1 to 14 days.')).toEqual({ fieldText: 'lead time', target: 'ABC-1', value: '14 days' });
    expect(parseEdit('update the supplier of "PN 1" to Digi-Key')?.target).toBe('PN 1');
  });
  it('maps labels, names and synonyms to the nine allow-listed fields only', () => {
    expect(resolveField('MOQ')?.name).toBe('final_moq');
    expect(resolveField('the unit price')?.name).toBe('final_price_conv');
    expect(resolveField('original price')?.name).toBe('final_price_original');
    expect(resolveField('final_lead_time')?.name).toBe('final_lead_time');
    expect(resolveField('vendor')?.name).toBe('final_supp_name');
    expect(resolveField('cpn')).toBeNull();
    expect(resolveField('stage')).toBeNull();
  });
  it('rejects values that do not fit the field', () => {
    const f = (t: string) => resolveField(t)!;
    expect(coerceValue(f('moq'), '1,000')).toEqual({ value: 1000 });
    expect(coerceValue(f('price'), '$0.45')).toEqual({ value: 0.45 });
    expect(coerceValue(f('lead time'), '14 days')).toEqual({ value: 14 });
    expect(coerceValue(f('moq'), 'lots')).toHaveProperty('error');
    expect(coerceValue(f('moq'), '-5')).toHaveProperty('error');
    expect(coerceValue(f('lead time'), '2.5')).toHaveProperty('error');
    expect(coerceValue(f('currency'), 'dollars')).toHaveProperty('error');
    expect(coerceValue(f('currency'), 'usd')).toEqual({ value: 'USD' });
  });
  it('routes only real edits: "change the model to x" is not an edit, how-to is not an edit', () => {
    expect(classify('set the MOQ of PN-100 to 500 in RFQ-00007')).toBe('edit');
    expect(isEditRequest('change the model to qwen')).toBe(false);
    expect(classify('how do I set the moq of a part to 500?')).not.toBe('edit');
    expect(classify('what is the moq of PN-100 in RFQ-00007?')).toBe('data');
  });
  it('routes manifest requests, but not with an RFQ id', () => {
    expect(classify('open the Input Standardization manifest')).toBe('manifest');
    expect(classify('show skill 4 json')).toBe('manifest');
    expect(classify('show the manifest of RFQ-00007')).not.toBe('manifest');
  });
});

describe('proposeEditValue', () => {
  it('issues an edit_value card with current and new value and calls nothing', async () => {
    const s = setup();
    const ui = await card(s);
    expect(ui.action).toBe('edit_value');
    expect(ui.params).toEqual({ rfqId: 'RFQ-00007', bomItemId: 'b1', label: 'PN-100', field: 'final_moq', fieldLabel: 'MOQ', before: 100, after: 500, volumeNo: null, volumes: [{ volumeNo: 1, before: 100 }] });
    expect(ui.expiresAt).toBe('2026-11-05T10:05:00.000Z');
    expect(s.calls).toEqual([]);
    expect(s.audit.map((a) => a.action)).toEqual(['propose']);
  });
  it.each([
    ['an unknown field', 'PN-100', 'stage', '5', 'not an editable value'],
    ['a missing part', '', 'moq', '5', 'which part'],
    ['a non-numeric value', 'PN-100', 'moq', 'lots', 'plain non-negative number'],
    ['an unknown part', 'NOPE-1', 'moq', '5', "can't find"],
    ['the same value', 'PN-100', 'moq', '100', 'already 100'],
  ])('refuses %s with a plain message, no card, no write', async (_n, target, field, value, text) => {
    const s = setup();
    const out = await propose(s, value, target, field);
    expect(out.ui).toBeUndefined();
    expect(out.message.toLowerCase()).toContain(text.toLowerCase());
    expect(s.calls).toEqual([]);
  });
  it('lists the editable fields when the field is unknown', async () => {
    const out = await propose(setup(), '5', 'PN-100', 'stage');
    expect(out.message).toContain('final_moq');
    expect(out.message).toContain('final_lead_time');
  });
  it('asks for the bom item id only when the matches are different ids, listing distinct ids with FG and description', async () => {
    const out = await propose(setup([row('b1', 'PN-100'), row('b1', 'PN-100', {}, 'FG1', 2), row('b2', 'PN-100', {}, 'FG2')]));
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('matches 2 different bom items');
    expect(out.message).toContain('b1 (PN-100, FG FG1, Resistor)');
    expect(out.message).toContain('b2 (PN-100, FG FG2, Resistor)');
    expect(out.message.match(/b1 \(/g)).toHaveLength(1);
  });
  it('one bom item id with a row per volume is ONE target: the card lists each volume and applies to all', async () => {
    const s = setup([row('b1', '2N7002BK,215', { final_price_conv: 0.1 }), row('b1', '2N7002BK,215', { final_price_conv: 0.2 }, 'FG1', 2)]);
    const out = await s.actions.proposeEditValue({ sessionKey: 's1', rfqId: 'RFQ-00007', target: '2N7002BK,215', fieldText: 'unit price', value: '0.1222' });
    if (out.ui?.type !== 'confirm_action') throw new Error(out.message);
    expect(out.ui.params).toMatchObject({ bomItemId: 'b1', before: 'Volume 1: 0.1; Volume 2: 0.2', after: 0.1222, volumeNo: null, volumes: [{ volumeNo: 1, before: 0.1 }, { volumeNo: 2, before: 0.2 }] });
    expect(out.ui.summary).toContain('all 2 volume rows');
    expect(out.message).toContain('every volume row');
    const done = await confirm(s, out.ui.confirmToken);
    expect(done.ok).toBe(true);
    expect(s.calls).toEqual([['RFQ-00007', { bomItemId: 'b1', field: 'final_price_conv', value: 0.1222 }, expect.any(String)]]); // no volumeNo: the bridge edits every volume row
  });
  it('an explicit "volume 2" edits that volume only and sends volume_no', async () => {
    const s = setup([row('b1', 'PN-100'), row('b1', 'PN-100', { final_moq: 120 }, 'FG1', 2)]);
    const out = await s.actions.proposeEditValue({ sessionKey: 's1', rfqId: 'RFQ-00007', target: 'PN-100', fieldText: 'moq', value: '500', volume: 2 });
    if (out.ui?.type !== 'confirm_action') throw new Error(out.message);
    expect(out.ui.params).toMatchObject({ before: 120, volumeNo: 2, volumes: [{ volumeNo: 2, before: 120 }] });
    await confirm(s, out.ui.confirmToken);
    expect(s.calls).toEqual([['RFQ-00007', { bomItemId: 'b1', field: 'final_moq', value: 500, volumeNo: 2 }, expect.any(String)]]);
    const none = await s.actions.proposeEditValue({ sessionKey: 's1', rfqId: 'RFQ-00007', target: 'PN-100', fieldText: 'moq', value: '5', volume: 7 });
    expect(none.ui).toBeUndefined();
    expect(none.message).toContain('no volume 7');
  });
  it('Confirm re-checks every volume: a change in one volume stops it', async () => {
    const s = setup([row('b1', 'PN-100'), row('b1', 'PN-100', {}, 'FG1', 2)]);
    const ui = await card(s);
    s.setRows([row('b1', 'PN-100'), row('b1', 'PN-100', { final_moq: 999 }, 'FG1', 2)]);
    const out = await confirm(s, ui.confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('(volume 2)');
    expect(s.calls).toEqual([]);
  });
  it('a part number with a comma is one token, and "volume N" is read from the sentence', () => {
    expect(parseEdit('set the unit price of part 2N7002BK,215 to 0.1222 for RFQ-CENTUM-PROOF-24')).toEqual({ fieldText: 'unit price', target: '2N7002BK,215', value: '0.1222' });
    expect(parseEdit('set the moq of PN-100 in volume 2 to 500 in RFQ-00007')).toEqual({ fieldText: 'moq', target: 'PN-100', value: '500', volume: 2 });
    expect(parseEdit('set the moq of PN-100 to 500 for vol 2 in RFQ-00007')?.volume).toBe(2);
  });
  it('a bom item id picks its row even when a cpn equals another id', async () => {
    const out = await propose(setup([row('b1', 'b2'), row('b2', 'PN-9')]), '500', 'b2');
    expect(out.ui).toMatchObject({ params: { bomItemId: 'b2' } });
  });
  it('a failing bridge read is reported and nothing is issued', async () => {
    const out = await propose(setup([], { findBomRows: async () => { throw new Error('bridge down'); } }));
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('bridge down');
  });
});

describe('confirm edit_value', () => {
  it('Confirm sends exactly the card edit, reports the version, cells and sheets, and attaches open_export', async () => {
    const s = setup();
    const ui = await card(s);
    const out = await confirm(s, ui.confirmToken);
    expect(out.ok).toBe(true);
    expect(s.calls).toEqual([['RFQ-00007', { bomItemId: 'b1', field: 'final_moq', value: 500 }, expect.stringContaining('MOQ')]]);
    expect(out.message).toContain('CBOM_v2.xlsx');
    expect(out.message).toContain('14 changed cells across 2 sheets');
    expect(out.message).toContain('downloadable');
    expect(out.ui).toEqual({ type: 'open_export', rfqId: 'RFQ-00007' });
    expect(out.steps.map((x) => `${x.step}:${x.status}`)).toEqual(['check_row:done', 'edit_and_regenerate:done']);
    expect(s.audit.map((a) => a.action)).toEqual(['propose', 'confirm.start', 'edit_value.check_row', 'edit_value.edit_and_regenerate']);
    expect(s.audit.every((a) => a.paramHash === hashParams(ui.params))).toBe(true);
    expect(JSON.stringify(s.audit)).not.toContain('tok-1');
  });
  it('says so when there was no earlier version to compare', async () => {
    const s = setup([row('b1', 'PN-100')], { editAndRegenerate: async () => ({ ...OK, before: null, diff: null }) });
    const out = await confirm(s, (await card(s)).confirmToken);
    expect(out.ok).toBe(true);
    expect(out.message).toContain('No cell comparison');
  });
  it('a bridge refusal reports the failed step honestly, no export button', async () => {
    const s = setup([row('b1', 'PN-100')], { editAndRegenerate: async () => { throw new Error('the reporting service answered HTTP 500: boom'); } });
    const out = await confirm(s, (await card(s)).confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('Stopped at edit_and_regenerate');
    expect(out.message).toContain('boom');
    expect(out.message).toContain('not kept');
    expect(out.ui).toBeUndefined();
    expect(out.steps.at(-1)).toMatchObject({ step: 'edit_and_regenerate', status: 'failed' });
  });
  it('an unknown outcome tells the user to check before asking again', async () => {
    const s = setup([row('b1', 'PN-100')], { editAndRegenerate: async () => { throw new UnknownOutcomeError('timeout'); } });
    const out = await confirm(s, (await card(s)).confirmToken);
    expect(out.message).toContain('may have been applied');
  });
  it('applied 0 is not reported as success', async () => {
    const s = setup([row('b1', 'PN-100')], { editAndRegenerate: async () => ({ ...OK, applied: 0 }) });
    expect((await confirm(s, (await card(s)).confirmToken)).ok).toBe(false);
  });
  it('stops when the value changed since the card was issued', async () => {
    const s = setup();
    const ui = await card(s);
    s.setRows([row('b1', 'PN-100', { final_moq: 250 })]);
    const out = await confirm(s, ui.confirmToken);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('changed since');
    expect(s.calls).toEqual([]);
  });
  it('Cancel changes nothing', async () => {
    const s = setup();
    const out = await confirm(s, (await card(s)).confirmToken, 'cancel');
    expect(out).toMatchObject({ ok: true, steps: [] });
    expect(out.message).toContain('Nothing was changed');
    expect(s.calls).toEqual([]);
  });
  it('token lifecycle: single use, session bound, expires after 5 minutes', async () => {
    const s = setup();
    const ui = await card(s);
    expect((await confirm(s, ui.confirmToken, 'confirm', 's2')).message).toContain('another session');
    expect((await confirm(s, ui.confirmToken)).ok).toBe(true);
    expect((await confirm(s, ui.confirmToken)).message).toContain('unknown, already used or expired');
    expect(s.calls).toHaveLength(1);
    s.setRows([row('b1', 'PN-100')]);
    const late = await card(s);
    s.tick(5 * 60_000 + 1);
    const out = await confirm(s, late.confirmToken);
    expect(out.message).toContain('expired');
    expect(out.message).toContain('Nothing was changed');
    expect(s.calls).toHaveLength(1);
  });
  it('changed params at confirm are refused', async () => {
    const s = setup();
    const ui = await card(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm', params: { ...ui.params, after: 999999 } } as never });
    expect(out.ok).toBe(false);
    expect(s.calls).toEqual([]);
  });
  it('no audit trail, no write', async () => {
    let fail = false;
    const s = setup([row('b1', 'PN-100')], { appendAudit: async () => { if (fail) throw new Error('disk'); } });
    const ui = await card(s);
    fail = true;
    const out = await confirm(s, ui.confirmToken);
    expect(out.message).toContain('audit log is not writable');
    expect(s.calls).toEqual([]);
  });
});

const rfq = (id: string): RfqSummary => ({ rfqId: id, customer: 'C', project: 'P', stage: 3, reviewPending: false });
const TREE: ManifestTree = {
  agent: { path: 'agent/agent_manifest.json', name: 'CAM Agent', skills: [
    { path: 'skills/skill_01.json', id: 'SKILL_01', name: 'Input Standardization', sequence: 1 },
    // sequence is the run order (SPEC-025): SKILL_04 runs third, yet "skill 4" still means SKILL_04
    { path: 'skills/skill_04.json', id: 'SKILL_04', name: 'Distributor & Source Selection', sequence: 3 },
    { path: 'skills/skill_09.json', id: 'SKILL_09', name: 'Reporting', sequence: 9 },
  ] },
  reporting: { path: 'reporting/cam.json', name: 'Reporting manifest' },
};
function chat(over: Partial<ChatServiceDeps> = {}) {
  const complete = vi.fn(async () => null);
  const proposeEditValue = vi.fn(async (p: { rfqId: string }) => ({ message: `card for ${p.rfqId}`, ui: undefined }));
  const deps = { model: () => ({ label: 'none', complete } as ChatModel), listRfqs: async () => [rfq('RFQ-00007'), rfq('RFQ-00008')], manifests: async () => TREE, actions: { proposeCreateRfq: vi.fn(), proposeStartPipeline: vi.fn(), proposeEditValue, confirm: vi.fn() }, sessionKey: 'u', ...over } as unknown as ChatServiceDeps;
  const ask = (text: string, scope?: string[]) => chatReply({ rfqId: null, scope: scope ? { mode: 'rfqs', rfqIds: scope } : undefined, messages: [{ role: 'user', content: text }] }, deps);
  return { ask, complete, proposeEditValue };
}

describe('service: edit intent', () => {
  it('passes the parsed edit with the named RFQ and calls no model', async () => {
    const t = chat();
    const out = await t.ask('set the MOQ of PN-100 to 500 in RFQ-00007');
    expect(t.proposeEditValue).toHaveBeenCalledWith({ sessionKey: 'u', rfqId: 'RFQ-00007', target: 'PN-100', fieldText: 'MOQ', value: '500' });
    expect(out.message).toBe('card for RFQ-00007');
    expect(t.complete).not.toHaveBeenCalled();
  });
  it('uses the single scoped RFQ when none is named', async () => {
    const t = chat();
    await t.ask('change the supplier of PN-100 to Digi-Key', ['RFQ-00008']);
    expect(t.proposeEditValue).toHaveBeenCalledWith(expect.objectContaining({ rfqId: 'RFQ-00008' }));
  });
  it('asks which RFQ when none is named or scoped, and refuses an unknown RFQ', async () => {
    const t = chat();
    expect((await t.ask('set the moq of PN-100 to 5')).ui).toMatchObject({ type: 'disambiguate' });
    expect((await t.ask('set the moq of PN-100 to 5 in RFQ-99999')).message).toContain('RFQ-99999');
    expect(t.proposeEditValue).not.toHaveBeenCalled();
  });
});

describe('service: open manifest', () => {
  it('"open the Input Standardization manifest" gives an open_manifest button', async () => {
    const out = await chat().ask('open the Input Standardization manifest');
    expect(out.ui).toEqual({ type: 'open_manifest', path: 'skills/skill_01.json', label: 'Input Standardization (skill 1)' });
    expect(out.message).toContain('enabled flag switches its pipeline steps');
  });
  it('finds a skill by number, by part of its name, and the agent and reporting manifests', async () => {
    const t = chat();
    expect((await t.ask('show skill 4 json')).ui).toMatchObject({ path: 'skills/skill_04.json' });
    expect((await t.ask('open the distributor selection skill')).ui).toMatchObject({ path: 'skills/skill_04.json' });
    expect((await t.ask('open the agent manifest')).ui).toMatchObject({ path: 'agent/agent_manifest.json' });
    expect((await t.ask('open the reporting manifest')).ui).toMatchObject({ path: 'reporting/cam.json' });
  });
  it('an unknown name lists the skill names, no button', async () => {
    const out = await chat().ask('open the Quantum Teleport manifest');
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('1. Input Standardization');
    expect(out.message).toContain('4. Distributor & Source Selection');
  });
  it('a loader failure is said plainly', async () => {
    const out = await chat({ manifests: async () => { throw new Error('no folder'); } }).ask('open skill 2');
    expect(out.message).toContain('no folder');
  });
});
