import { describe, it, expect } from 'vitest';
import { describeStatus, fetchRfqStatus, stageNumber, type RfqStatus, type StatusDb } from '../src/rfq-chat/rfq-chat-status.js';

const skills = [
  { skill_index: 1, skill_name: 'Standardize BOM', macro_category: 1, mcp_tool_name: 'std' },
  { skill_index: 2, skill_name: 'Fetch prices', macro_category: 3, mcp_tool_name: 'price' },
  { skill_index: 3, skill_name: 'Export CBOM', macro_category: 8, mcp_tool_name: 'cbom' },
];

/** A fake of the two databases: answers by what the SQL asks for. */
function fakeDb(o: { project?: boolean; stage?: number; hitl?: boolean; volume?: boolean }): StatusDb {
  return {
    fileMeta: {
      query: async (sql) => {
        if (sql.includes('FROM rfq_project_tracking')) {
          return { rows: o.project === false ? [] : [{ customer_name: 'Centum', project_name: 'Alpha' }] };
        }
        if (sql.includes('FROM rfq_process_tracking')) {
          return { rows: o.stage === undefined ? [] : [{ rfq_process_stage: o.stage, hitl_required: o.hitl === true }] };
        }
        return { rows: o.volume ? [{ '?column?': 1 }] : [] }; // rfq_file_telemetry VOLUME check
      },
    },
    registry: {
      query: async (sql, params) => {
        if (sql.includes('quote_routing_profiles')) {
          return { rows: params?.[0] === 'Standard_BOM_Flow' ? [{ routing_sequence: ['std', 'price', 'cbom'] }] : [] };
        }
        // by position in the routing sequence (SPEC-025): the tools run so far, and the macro_category of one tool
        if (sql.includes('mcp_tool_name = ANY')) {
          return { rows: skills.filter((s) => (params?.[0] as string[]).includes(s.mcp_tool_name)) };
        }
        if (sql.includes('SELECT macro_category FROM')) {
          return { rows: skills.filter((s) => s.mcp_tool_name === params?.[0]).map((s) => ({ macro_category: s.macro_category })) };
        }
        return { rows: [] };
      },
    },
  };
}
const status = (o: Parameters<typeof fakeDb>[0]) => fetchRfqStatus('RFQ-00007', async () => fakeDb(o));

describe('fetchRfqStatus', () => {
  it('a running RFQ: stage from the next skill, DONE and RUNNING rows, no review', async () => {
    const s = await status({ stage: 1 });
    expect(s).toMatchObject({ exists: true, started: true, finished: false, reviewPending: false, stage: 3, customer: 'Centum' });
    expect(s.steps).toEqual([{ name: 'Standardize BOM', state: 'done' }, { name: 'Fetch prices', state: 'running' }]);
  });

  it('a finished RFQ uses the last real skill and has no running row', async () => {
    const s = await status({ stage: 3 });
    expect(s).toMatchObject({ finished: true, stage: 8 });
    expect(s.steps.every((x) => x.state === 'done')).toBe(true);
  });

  it('hitl_required is the pending review', async () => {
    expect((await status({ stage: 1, hitl: true })).reviewPending).toBe(true);
  });

  it('an RFQ that exists with no run is not started; an unknown id does not exist', async () => {
    expect(await status({})).toMatchObject({ exists: true, started: false, stage: null, steps: [] });
    expect(await status({ project: false })).toMatchObject({ exists: false, started: false });
  });
});

describe('describeStatus', () => {
  const base: RfqStatus = { rfqId: 'RFQ-00007', exists: true, customer: 'Centum', project: 'Alpha', started: true, stage: 3, reviewPending: false, finished: false, steps: [], failure: null };

  it('names an uncleared failure and the next step, the way the chat must say it', () => {
    const text = describeStatus({ ...base, failure: { skill: 'Standardize QuoteWin', detail: 'No QuoteWin file uploaded for rfq_id=RFQ-00007' } });
    expect(text).toContain('Failed: Standardize QuoteWin: No QuoteWin file uploaded');
    expect(text).toContain('Upload the missing file, then resume the run.');
    expect(describeStatus(base)).not.toContain('Failed:');
  });

  it('says stage n of 9 with the stage name, review pending and the tagged rows', () => {
    const text = describeStatus({ ...base, steps: [{ name: 'Standardize BOM', state: 'done' }, { name: 'Fetch prices', state: 'running' }, { name: 'X', state: 'failed' }] });
    expect(text).toContain('stage 3 of 9 (Get online pricing)');
    expect(text).toContain('Review pending: no.');
    expect(text).toContain('[DONE] Standardize BOM\n[RUNNING] Fetch prices\n[FAILED] X');
  });

  it('says a review is waiting for a person', () => {
    expect(describeStatus({ ...base, reviewPending: true })).toContain('Review pending: yes');
  });

  it('says plainly when nothing has started or the RFQ does not exist', () => {
    expect(describeStatus({ ...base, started: false, stage: null })).toContain('no pipeline run has started');
    expect(describeStatus({ ...base, exists: false })).toContain("can't find");
  });

  it('maps macro categories to stages 1..9 (0 counts as the first)', () => {
    expect([0, 1, 4, 9, 12, null].map(stageNumber)).toEqual([1, 1, 4, 9, 9, null]);
  });
});
