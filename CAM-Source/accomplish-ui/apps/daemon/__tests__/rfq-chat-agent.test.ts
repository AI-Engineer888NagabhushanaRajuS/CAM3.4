import { describe, expect, it } from 'vitest';
import { runAgent, runTool, AGENT_TOOLS } from '../src/rfq-chat/rfq-chat-agent.js';
import type { ChatModel, ToolTurn } from '../src/rfq-chat/rfq-chat-types.js';

const rfqs = Array.from({ length: 173 }, (_, i) => ({
  rfqId: `RFQ-${String(i + 1).padStart(3, '0')}`,
  customer: i % 2 ? 'Acme' : 'Globex',
  project: `Project ${i + 1}`,
  stage: 9,
  reviewPending: false,
  hasExport: false,
}));

const deps = {
  listRfqs: async () => rfqs,
  pipelineStatus: async (rfqId: string) => ({ rfqId, exists: true, stage: 9 }),
  retrieve: async () => ({ chunks: [{ text: 'Summary!A4: 10.66', citation: { sheet: 'Summary', cell: 'A4' } }] }),
  dashboard: async () => [{ text: 'card: MOQ cost', citation: { sheet: 'Dashboard', cell: 'B2' } }],
  memory: async () => null,
} as unknown as Parameters<typeof runAgent>[3];

/** A scripted model: each call pops the next turn. */
function scripted(turns: ToolTurn[]): ChatModel & { seen: unknown[][] } {
  const seen: unknown[][] = [];
  return {
    label: 'fake',
    seen,
    async complete() {
      return null;
    },
    async callTools(messages: unknown[]) {
      seen.push(messages.slice());
      return turns.shift() ?? null;
    },
  };
}

describe('RFQ assistant agent', () => {
  it('pages the whole RFQ list instead of stopping at 25', async () => {
    const first = await runTool('list_rfqs', { limit: 50 }, deps);
    expect((first as { total: number }).total).toBe(173);
    expect((first as { rows: unknown[] }).rows).toHaveLength(50);
    const last = await runTool('list_rfqs', { offset: 150, limit: 50 }, deps);
    expect((last as { rows: unknown[] }).rows).toHaveLength(23);
  });

  it('filters by customer before paging', async () => {
    const acme = await runTool('list_rfqs', { search: 'acme', limit: 50 }, deps);
    expect((acme as { total: number }).total).toBe(86);
  });

  it('runs tool calls and answers from their results', async () => {
    const model = scripted([
      { text: '', toolCalls: [{ id: 'c1', name: 'list_rfqs', args: { search: 'globex', limit: 3 } }], model: 'fake', assistant: { role: 'assistant' } },
      { text: 'There are 87 Globex RFQs.', toolCalls: [], model: 'fake', assistant: {} },
    ]);
    const answer = await runAgent('Which RFQs are Globex?', [], model, deps);
    expect(answer).toEqual({ message: 'There are 87 Globex RFQs.', model: 'fake' });
    // the second model call received the tool result
    const second = model.seen[1];
    const toolMessage = second.find((m) => (m as { role: string }).role === 'tool') as { content: string; tool_call_id: string };
    expect(toolMessage.tool_call_id).toBe('c1');
    expect(toolMessage.content).toContain('RFQ-003');
  });

  it('returns null when the model cannot take tool calls, so the older path answers', async () => {
    const plain: ChatModel = { label: 'plain', complete: async () => null };
    expect(await runAgent('hi', [], plain, deps)).toBeNull();
  });

  it('stops after the step cap rather than looping', async () => {
    const forever: ToolTurn[] = Array.from({ length: 20 }, (_, i) => ({
      text: '', toolCalls: [{ id: `c${i}`, name: 'rfq_status', args: { rfq_id: 'RFQ-001' } }], model: 'fake', assistant: {},
    }));
    const answer = await runAgent('loop', [], scripted(forever), deps);
    expect(answer?.message).toMatch(/stopped after 8 steps/);
  });

  it('reports an unknown tool as data the model can read', async () => {
    expect(await runTool('drop_tables', {}, deps)).toEqual({ error: 'unknown tool drop_tables' });
  });

  it('exposes the five tools by name', () => {
    expect(AGENT_TOOLS.map((t) => t.function.name)).toEqual(['list_rfqs', 'rfq_status', 'rfq_evidence', 'rfq_dashboard', 'memory_search']);
  });
});
