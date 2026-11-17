import { describe, it, expect, vi, beforeEach } from 'vitest';

// The MCP client is replaced by a fake that serves pages, and can be told to fail one tool on purpose.
const calls: Array<{ tool: string; args: Record<string, unknown> }> = [];
let pages: Array<{ items: Array<Record<string, unknown>>; next_cursor: string | null }> = [];
let pending: Array<Record<string, unknown>> = [];
let failTool: Record<string, Error> = {};
let afterResolve: (() => void) | null = null;

vi.mock('../src/rfq-chat/rfq-chat-mcp-client.js', () => ({
  callMcpTool: async (_url: string, tool: string, args: Record<string, unknown>) => {
    calls.push({ tool, args });
    if (failTool[tool]) throw failTool[tool];
    if (tool === 'list_price_conflicts') {
      if (pages.length) {
        const page = pages[Math.min(calls.filter((c) => c.tool === 'list_price_conflicts').length - 1, pages.length - 1)];
        return page;
      }
      return { items: pending, next_cursor: null };
    }
    if (tool === 'resolve_price_conflicts') {
      const ids = (args.resolutions as Array<{ conflict_id: string }>).map((r) => r.conflict_id);
      pending = pending.filter((i) => !ids.includes(String(i.conflict_id)));
      afterResolve?.();
      return { ok: true };
    }
    if (tool === 'resume_price_gate') return { status: 'TRIGGERED', outcome: 'RESUMED' };
    throw new Error(`unexpected tool ${tool}`);
  },
}));

import { planResolveConflicts, runResolveConflicts, readAllConflicts } from '../src/rfq-chat/rfq-chat-actions-gate.js';

const item = (id: string, costing: unknown, erp: unknown, qw: unknown) => ({
  conflict_id: id,
  cpn: `CPN-${id}`,
  volume_no: '1',
  available_sources: {
    ...(costing !== undefined ? { costing: { price_conv: costing } } : {}),
    ...(erp !== undefined ? { erp: { price_conv: erp } } : {}),
    ...(qw !== undefined ? { qw: { price_conv: qw } } : {}),
  },
});
const SIGNED_IN = { email: 'person@example.com' };
const noAudit = async () => undefined;

beforeEach(() => {
  calls.length = 0;
  pages = [];
  failTool = {};
  afterResolve = null;
  pending = [item('a', 1, 2, 3), item('b', 4, undefined, 6)];
});

describe('planning the write', () => {
  it('plans one source for every pending conflict', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    expect(plan.params?.conflictIds).toEqual(['a', 'b']);
    expect(plan.params?.parts).toBe(2);
    expect(plan.message).toContain('QuoteWin price for all 2 conflicts');
  });

  it('refuses a source that some conflict has no price for, and names how many', async () => {
    pending = [item('c', 1, undefined, undefined)];
    const refused = await planResolveConflicts('RFQ-1', 'erp');
    expect(refused.params).toBeUndefined();
    expect(refused.message).toContain('no ERP price');
  });

  it('treats a non-numeric, NaN or infinite price as no price', async () => {
    for (const bad of ['12.5', Number.NaN, Number.POSITIVE_INFINITY, null]) {
      pending = [item('x', bad, 2, 3)];
      const plan = await planResolveConflicts('RFQ-1', 'costing');
      expect(plan.params, `price ${String(bad)}`).toBeUndefined();
    }
  });

  it('a conflict with no available_sources at all cannot take any source', async () => {
    pending = [{ conflict_id: 'n', cpn: 'CPN-n', volume_no: '1', available_sources: null }];
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    expect(plan.params).toBeUndefined();
    expect(plan.message).toContain('no QuoteWin price');
  });

  it('says so when nothing is waiting at the gate, and writes nothing', async () => {
    pending = [];
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    expect(plan.params).toBeUndefined();
    expect(plan.message).toContain('nothing to resolve');
    expect(calls.map((c) => c.tool)).not.toContain('resolve_price_conflicts');
  });

  it('reads every page before planning, so a long gate is never planned from its first page only', async () => {
    const first = [item('p1', 1, 1, 1), item('p2', 1, 1, 1)];
    const second = [item('p3', 1, 1, 1)];
    pages = [
      { items: first, next_cursor: 'c1' },
      { items: second, next_cursor: null },
    ];
    const all = await readAllConflicts('RFQ-1');
    expect(all.map((i) => i.conflict_id)).toEqual(['p1', 'p2', 'p3']);
    expect(calls.filter((c) => c.tool === 'list_price_conflicts').map((c) => c.args.cursor ?? null)).toEqual([null, 'c1']);
  });
});

describe('running the write', () => {
  it('records the source for each conflict with the signed-in email, then resumes when nothing is left', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    const done = await runResolveConflicts(plan.params!, SIGNED_IN, noAudit);
    expect(done.ok).toBe(true);
    const resolve = calls.find((c) => c.tool === 'resolve_price_conflicts')!;
    expect(resolve.args.resolved_by).toBe('person@example.com');
    expect((resolve.args.resolutions as Array<Record<string, string>>).every((r) => r.resolved_source === 'qw')).toBe(true);
    expect(calls.map((c) => c.tool)).toContain('resume_price_gate');
    expect(done.message).toContain('resumed the run');
  });

  it('only sends the conflicts that are still pending when it runs (someone resolved one meanwhile)', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    pending = [item('b', 4, undefined, 6)]; // 'a' was resolved elsewhere
    await runResolveConflicts(plan.params!, SIGNED_IN, noAudit);
    const resolve = calls.find((c) => c.tool === 'resolve_price_conflicts')!;
    expect((resolve.args.resolutions as Array<{ conflict_id: string }>).map((r) => r.conflict_id)).toEqual(['b']);
  });

  it('does nothing and says so when every conflict was resolved since planning', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    pending = [];
    const out = await runResolveConflicts(plan.params!, SIGNED_IN, noAudit);
    expect(out.ok).toBe(true);
    expect(out.message).toContain('already resolved');
    expect(calls.map((c) => c.tool)).not.toContain('resolve_price_conflicts');
    expect(calls.map((c) => c.tool)).not.toContain('resume_price_gate');
  });

  it('a conflict that appeared after planning keeps the run at the gate (it is not resumed past an unplanned conflict)', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    afterResolve = () => {
      pending.push(item('new', 1, 1, 1));
    };
    const out = await runResolveConflicts(plan.params!, SIGNED_IN, noAudit);
    expect(out.message).toContain('still pending');
    expect(calls.map((c) => c.tool)).not.toContain('resume_price_gate');
  });

  it('a failing resolve stops before the resume and says nothing was resumed', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    failTool = { resolve_price_conflicts: new Error('HITL router answered 500') };
    const out = await runResolveConflicts(plan.params!, SIGNED_IN, noAudit);
    expect(out.ok).toBe(false);
    expect(out.steps.at(-1)).toMatchObject({ step: 'resolve', status: 'failed' });
    expect(out.message).toContain('Nothing was resumed');
    expect(calls.map((c) => c.tool)).not.toContain('resume_price_gate');
  });

  it('a failing resume after the decisions are recorded says they were recorded and tells the person where to resume', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    failTool = { resume_price_gate: new Error('upload server answered 503') };
    const out = await runResolveConflicts(plan.params!, SIGNED_IN, noAudit);
    expect(out.ok).toBe(false);
    expect(out.message).toContain('are recorded');
    expect(out.message).toContain('left pane');
    expect(out.steps.map((s) => s.step)).toContain('resolve');
  });

  it('when the gate cannot be re-read after recording, it does not guess: no resume', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    // The first read (before recording) works; the read after the resolve fails.
    afterResolve = () => {
      failTool = { list_price_conflicts: new Error('HITL router unreachable') };
    };
    const out = await runResolveConflicts(plan.params!, SIGNED_IN, noAudit);
    expect(calls.filter((c) => c.tool === 'resolve_price_conflicts')).toHaveLength(1);
    expect(out.ok).toBe(true);
    expect(out.message).toContain('could not re-read');
    expect(calls.map((c) => c.tool)).not.toContain('resume_price_gate');
  });

  it('refuses to record anything without a signed-in email', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    calls.length = 0;
    const out = await runResolveConflicts(plan.params!, undefined, noAudit);
    expect(out.ok).toBe(false);
    expect(calls).toHaveLength(0);
  });

  it('an empty conflict list in the card is already resolved, not an error', async () => {
    const out = await runResolveConflicts({ rfqId: 'RFQ-1', source: 'qw', conflictIds: [], parts: 0 }, SIGNED_IN, noAudit);
    expect(out.ok).toBe(true);
    expect(calls.map((c) => c.tool)).not.toContain('resolve_price_conflicts');
  });

  it('an audit line is written for each step it takes', async () => {
    const plan = await planResolveConflicts('RFQ-1', 'qw');
    const audited: string[] = [];
    await runResolveConflicts(plan.params!, SIGNED_IN, async (action) => {
      audited.push(action);
    });
    expect(audited).toEqual(['resolve_conflicts.check_state', 'resolve_conflicts.resolve', 'resolve_conflicts.resume']);
  });
});

import { controlIntent, classify } from '../src/rfq-chat/rfq-chat-intent.js';

describe('which messages reach the gate', () => {
  it.each([
    'what price conflicts are waiting for RFQ-000062?',
    'show the price source conflicts of RFQ-000062',
    'use QuoteWin for the conflicts of RFQ-000062',
    'resolve the conflicts for RFQ-000062',
    'how many pending conflicts are there in RFQ-000062',
  ])('%s goes to the price gate', (text) => {
    expect(controlIntent(text)).toBe('price_gate');
    expect(classify(text)).toBe('price_gate');
  });

  it.each([
    'which parts have conflicts in the BOM sheet?',
    'are there conflicts with the manifest?',
    'explain the price of RFQ-000062',
  ])('%s is not the gate', (text) => {
    expect(controlIntent(text)).not.toBe('price_gate');
  });
});
