import { describe, it, expect } from 'vitest';
import { makeChatActions } from '../src/rfq-chat/rfq-chat-actions.js';
import { chatStagingId, hashParams, sha12, UnknownOutcomeError, type ActionDeps, type AuditLine } from '../src/rfq-chat/rfq-chat-actions-types.js';

const enc = (s: string) => new TextEncoder().encode(s);
const BOM = enc('bom bytes');
const VOL = enc('volume bytes');
const files = [
  { attachmentId: sha12(BOM), name: 'acme-bom.xlsx' },
  { attachmentId: sha12(VOL), name: 'acme-volume.xlsx' },
];
const REQUEST = 'create an RFQ for Acme Corp, project Widget';

/** Fakes for every network and database call; `calls` records what was done, `over` replaces behaviour per test. */
function setup(over: Partial<ActionDeps> = {}, released = files) {
  const calls: string[] = [];
  const audit: AuditLine[] = [];
  let clock = Date.parse('2026-11-05T10:00:00Z');
  let n = 0;
  const deps: ActionDeps = {
    now: () => clock,
    newToken: () => `tok-${++n}`,
    listCustomers: async () => [{ customerId: 'c1', customerName: 'Acme Corp' }, { customerId: 'c2', customerName: 'Globex' }],
    listProjects: async () => [
      { projectId: 'p1', customerId: 'c1', projectName: 'Widget' },
      { projectId: 'p2', customerId: 'c2', projectName: 'Gadget' },
    ],
    nextRfqId: async () => 'RFQ-000042',
    listAttachments: async (scope) => {
      calls.push(`list:${scope}`);
      return released.map((f) => ({ attachmentId: f.attachmentId, name: f.name, sha256: null }));
    },
    readAttachment: async (_scope, id) => {
      calls.push(`read:${id}`);
      return id === sha12(BOM) ? BOM : VOL;
    },
    createRfq: async (p) => {
      calls.push(`createRfq:${p.rfqId}`);
    },
    scanFiles: async (_id, f) => {
      calls.push('scan');
      return f.map((x) => ({ name: x.name, decision: 'released' as const, attachmentId: sha12(x.bytes) }));
    },
    deleteAttachment: async (_id, a) => {
      calls.push(`deleteAttachment:${a}`);
    },
    upload: async () => {
      calls.push('upload');
      return { pipelineStatus: 'TRIGGERED' };
    },
    deleteRfqRows: async (id) => {
      calls.push(`deleteRfqRows:${id}`);
    },
    appendAudit: async (l) => {
      audit.push(l);
    },
    ...over,
  };
  // After a scan the released files are listed under the new id too.
  const actions = makeChatActions({ getApiKey: () => null, getSelectedModel: () => null }, deps);
  return { actions, calls, audit, tick: (ms: number) => { clock += ms; } };
}

async function propose(s: ReturnType<typeof setup>, session = 's1') {
  const out = await s.actions.proposeCreateRfq({ sessionKey: session, request: REQUEST, fileRefs: files });
  if (out.ui?.type !== 'confirm_action') {
    throw new Error(`no card: ${out.message}`);
  }
  return out.ui;
}

const created = (calls: string[]) => calls.filter((c) => c.startsWith('createRfq'));

describe('proposeCreateRfq', () => {
  it('returns a confirmation card with the exact parameters and no write', async () => {
    const s = setup();
    const ui = await propose(s);
    expect(ui.action).toBe('create_rfq');
    expect(ui.params).toMatchObject({ rfqId: 'RFQ-000042', customer: { id: 'c1' }, project: { id: 'p1' } });
    expect((ui.params as { files: Array<{ role: string }> }).files.map((f) => f.role)).toEqual(['BOM', 'VOLUME']);
    expect(ui.expiresAt).toBe('2026-11-05T10:05:00.000Z');
    expect(created(s.calls)).toEqual([]);
  });

  it('asks (plain message, no card) when customer and project are missing', async () => {
    const s = setup();
    const out = await s.actions.proposeCreateRfq({ sessionKey: 's1', request: 'make me an rfq', fileRefs: files });
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('Acme Corp');
    expect(out.message).toContain('Globex');
  });

  it('asks for the Volume file when only the BOM is attached', async () => {
    const s = setup();
    const out = await s.actions.proposeCreateRfq({ sessionKey: 's1', request: REQUEST, fileRefs: [files[0]] });
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('Volume');
  });

  it('never proceeds with a file that is not released (quarantined or held)', async () => {
    const s = setup({}, [files[1]]); // the BOM was quarantined, so it is not in the released list
    const out = await s.actions.proposeCreateRfq({ sessionKey: 's1', request: REQUEST, fileRefs: files });
    expect(out.ui).toBeUndefined();
    expect(out.message).toContain('acme-bom.xlsx is not a released attachment');
    expect(s.audit.map((a) => a.action)).toContain('propose.blocked');
  });

  it('reads files from the chat staging scope unless the ref names one', async () => {
    const s = setup();
    await propose(s, 'session-x');
    expect(s.calls).toContain(`list:${chatStagingId('session-x')}`);
  });
});

describe('confirmation token', () => {
  it('is single use: the replay is refused and nothing is created twice', async () => {
    const s = setup();
    const ui = await propose(s);
    const first = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(first.ok).toBe(true);
    const replay = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(replay.ok).toBe(false);
    expect(replay.message).toContain('already used');
    expect(created(s.calls)).toHaveLength(1);
  });

  it('expires after 5 minutes', async () => {
    const s = setup();
    const ui = await propose(s);
    s.tick(5 * 60 * 1000 + 1);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.ok).toBe(false);
    expect(out.message).toContain('expired');
    expect(created(s.calls)).toEqual([]);
  });

  it('still works just inside 5 minutes', async () => {
    const s = setup();
    const ui = await propose(s);
    s.tick(5 * 60 * 1000 - 1);
    expect((await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } })).ok).toBe(true);
  });

  it('is bound to the session: another session is refused and cannot burn the owner card', async () => {
    const s = setup();
    const ui = await propose(s, 's1');
    const other = await s.actions.confirm({ sessionKey: 's2', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(other.ok).toBe(false);
    expect(created(s.calls)).toEqual([]);
    expect((await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } })).ok).toBe(true);
  });

  it('is bound to the parameters: echoed params that differ are refused and the card is dead', async () => {
    const s = setup();
    const ui = await propose(s);
    const tampered = { ...ui.params, rfqId: 'RFQ-000001' };
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm', params: tampered } as never });
    expect(out.ok).toBe(false);
    expect(out.message).toContain('parameters changed');
    expect(created(s.calls)).toEqual([]);
    expect((await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } })).ok).toBe(false);
  });

  it('mutating the params object the card carried does not change what gets created', async () => {
    const s = setup();
    const ui = await propose(s);
    (ui.params as { rfqId: string }).rfqId = 'RFQ-999999';
    await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(created(s.calls)).toEqual(['createRfq:RFQ-000042']);
  });

  it('refuses an unknown token', async () => {
    const s = setup();
    expect((await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: 'nope', decision: 'confirm' } })).ok).toBe(false);
  });
});

describe('confirm', () => {
  it('cancel creates nothing and says so', async () => {
    const s = setup();
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'cancel' } });
    expect(out).toMatchObject({ ok: true, steps: [] });
    expect(out.message).toContain('Nothing was created');
    expect(s.calls.filter((c) => !c.startsWith('list:'))).toEqual([]);
  });

  it('runs every step in order and returns the RFQ id', async () => {
    const s = setup();
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.ok).toBe(true);
    expect(out.rfqId).toBe('RFQ-000042');
    expect(out.steps.map((x) => `${x.step}:${x.status}`)).toEqual([
      'create_rfq:done', 'fetch_files:done', 'scan_files:done', 'upload_files:done', 'start_pipeline:done',
    ]);
  });

  it('a file quarantined by the re-scan stops at scan_files, uploads nothing and rolls back', async () => {
    const s = setup({
      scanFiles: async (_id, f) => f.map((x, i) => ({ name: x.name, decision: i === 0 ? ('quarantined' as const) : ('released' as const), attachmentId: i === 0 ? null : sha12(x.bytes) })),
    });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.ok).toBe(false);
    expect(out.message).toContain('Stopped at scan_files');
    expect(out.steps.map((x) => `${x.step}:${x.status}`)).toEqual(['create_rfq:done', 'fetch_files:done', 'scan_files:failed', 'rollback:done']);
    expect(s.calls).not.toContain('upload');
    expect(s.calls).toContain('deleteRfqRows:RFQ-000042');
    expect(out.message).toContain('removed again');
  });

  it('a failed createRfq stops at step 1: nothing else is attempted, nothing to roll back', async () => {
    const s = setup({ createRfq: async () => { throw new Error('RFQ ID already exists'); } });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.steps).toEqual([{ step: 'create_rfq', status: 'failed', detail: 'RFQ ID already exists' }]);
    expect(out.message).toContain('Nothing was created');
    expect(s.calls.filter((c) => c === 'scan' || c === 'upload' || c.startsWith('deleteRfqRows'))).toEqual([]);
  });

  it('a checksum mismatch on the stored file stops at fetch_files and rolls back', async () => {
    const s = setup({ readAttachment: async () => enc('swapped bytes') });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.message).toContain('checksum mismatch');
    expect(out.steps.at(-1)).toMatchObject({ step: 'rollback', status: 'done' });
  });

  it('an upload rejected by the server rolls back and names the step', async () => {
    const s = setup({ upload: async () => { throw new Error('the upload service answered HTTP 500'); } });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.message).toContain('Stopped at upload_files');
    expect(out.steps.map((x) => x.step)).toEqual(['create_rfq', 'fetch_files', 'scan_files', 'upload_files', 'rollback']);
    expect(s.calls).toContain('deleteRfqRows:RFQ-000042');
  });

  it('an upload with an unknown outcome deletes nothing and says what may exist', async () => {
    const s = setup({ upload: async () => { throw new UnknownOutcomeError('timed out'); } });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.ok).toBe(false);
    expect(out.rfqId).toBe('RFQ-000042');
    expect(out.message).toContain('did not delete anything');
    expect(s.calls.some((c) => c.startsWith('deleteRfqRows'))).toBe(false);
  });

  it('a pipeline that did not start keeps the RFQ and tells the user how to continue', async () => {
    const s = setup({ upload: async () => ({ pipelineStatus: 'CONNECTION_REFUSED' }) });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.ok).toBe(false);
    expect(out.message).toContain('Stopped at start_pipeline');
    expect(out.message).toContain('Continue');
    expect(out.steps.at(-1)).toMatchObject({ step: 'start_pipeline', status: 'failed' });
    expect(s.calls.some((c) => c.startsWith('deleteRfqRows'))).toBe(false);
  });

  it('a failed rollback says the RFQ still exists', async () => {
    const s = setup({ upload: async () => { throw new Error('boom'); }, deleteRfqRows: async () => { throw new Error('db down'); } });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.steps.at(-1)).toMatchObject({ step: 'rollback', status: 'failed' });
    expect(out.message).toContain('still exists');
  });

  it('writes nothing when the audit log cannot be written', async () => {
    const s = setup({ appendAudit: async () => { throw new Error('disk full'); } });
    const ui = await propose(s);
    const out = await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(out.ok).toBe(false);
    expect(created(s.calls)).toEqual([]);
  });
});

describe('audit', () => {
  it('appends who, ISO time, action, parameter hash and result for the proposal and every step', async () => {
    const s = setup();
    const ui = await propose(s);
    await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    expect(s.audit.map((a) => a.action)).toEqual([
      'propose', 'confirm.start',
      'create_rfq.create_rfq', 'create_rfq.fetch_files', 'create_rfq.scan_files', 'create_rfq.upload_files', 'create_rfq.start_pipeline',
    ]);
    for (const line of s.audit) {
      expect(line.who).toBe('s1');
      expect(new Date(line.when).toISOString()).toBe(line.when);
      expect(line.paramHash).toMatch(/^[0-9a-f]{64}$/);
      expect(line.result).not.toBe('');
    }
    expect(s.audit[0].paramHash).toBe(hashParams(ui.params));
  });

  it('records refusals and cancels', async () => {
    const s = setup();
    const ui = await propose(s);
    await s.actions.confirm({ sessionKey: 's2', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'cancel' } });
    expect(s.audit.map((a) => a.action).slice(-2)).toEqual(['confirm.refused', 'confirm.cancel']);
  });

  it('never puts file bytes or a bearer token in the audit lines', async () => {
    const s = setup();
    const ui = await propose(s);
    await s.actions.confirm({ sessionKey: 's1', req: { confirmToken: ui.confirmToken, decision: 'confirm' } });
    const text = JSON.stringify(s.audit);
    expect(text).not.toContain('Bearer');
    expect(text).not.toContain(ui.confirmToken);
  });
});
