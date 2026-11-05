/**
 * Pipeline progress of one RFQ, from the database only (no model, no workbook): which of the 9 workflow stages it is at,
 * whether it waits for a human review, and the last skill rows. The SQL mirrors rfq.getProcessStage and rfq.getSkillHistory
 * in browser-api-server.ts (the UI's own progress log), so the chat and the right pane say the same thing.
 */

/** The nine stages of WORKFLOW_STAGES in apps/web App.tsx (mainHeading), in order; stage n = macro_category n (0 counts as 1). */
export const STAGE_NAMES = [
  'Upload file', 'Extract features', 'Get online pricing', 'ERP & Quoting tools', 'Analyze feasibility & Risks',
  'Consolidate Pricing Sources', 'Finalize price', 'Quote Readiness', 'Reports & Analytics',
];

export interface StatusStep {
  name: string;
  state: 'done' | 'running' | 'failed';
}

export interface RfqStatus {
  rfqId: string;
  /** In rfq_project_tracking or rfq_process_tracking. */
  exists: boolean;
  customer: string | null;
  project: string | null;
  /** A pipeline run was ever started (an active rfq_process_tracking row exists). */
  started: boolean;
  /** Stage n of 9; null before the pipeline started. */
  stage: number | null;
  reviewPending: boolean;
  finished: boolean;
  /** Skill rows that ran or are running, in order. */
  steps: StatusStep[];
}

type Rows = { rows: Array<Record<string, unknown>> };
export interface Queryable {
  query(sql: string, params?: unknown[]): Promise<Rows>;
}
export interface StatusDb {
  /** file_metadata_db: rfq_project_tracking, rfq_process_tracking, rfq_file_telemetry. */
  fileMeta: Queryable;
  /** logic db: quote_routing_profiles, system_skills_registry. */
  registry: Queryable;
}

const realDb = async (): Promise<StatusDb> => {
  const { fileMetadataPool, pgPool } = await import('../db.js'); // lazy: db.ts refuses to load without its env vars
  return { fileMeta: fileMetadataPool, registry: pgPool };
};

export const stageNumber = (macro: unknown): number | null =>
  typeof macro === 'number' ? Math.min(9, Math.max(1, macro)) : null;

const toSteps = (rows: Rows['rows'], done: (r: Record<string, unknown>) => boolean): StatusStep[] =>
  rows.map((r) => ({ name: String(r.skill_name), state: done(r) ? 'done' : 'running' }));

/** Skill rows, finished flag and stage for an active run. Same detection of RFQ_Flow vs Standard_BOM_Flow as the UI path (a VOLUME file = RFQ_Flow). */
async function progress(db: StatusDb, rfqId: string, completed: number): Promise<{ steps: StatusStep[]; finished: boolean; macro: unknown }> {
  const volume = await db.fileMeta.query(`SELECT 1 FROM rfq_file_telemetry WHERE rfq_id = $1 AND file_role = 'VOLUME' LIMIT 1`, [rfqId]);
  const profile = async (name: string) =>
    (await db.registry.query(`SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = $1`, [name])).rows[0]?.routing_sequence as string[] | undefined;
  const flow = volume.rows.length > 0 ? await profile('RFQ_Flow') : undefined;
  if (flow && flow.length > 0) {
    const upper = Math.min(completed, flow.length - 1);
    const tools = flow.slice(0, upper + 1);
    const { rows } = await db.registry.query(
      `SELECT skill_index, skill_name, macro_category, mcp_tool_name FROM system_skills_registry WHERE mcp_tool_name = ANY($1) ORDER BY skill_index`, [tools]);
    const macro = (await db.registry.query(`SELECT macro_category FROM system_skills_registry WHERE mcp_tool_name = $1`, [flow[upper]])).rows[0]?.macro_category;
    return { steps: toSteps(rows, (r) => tools.indexOf(String(r.mcp_tool_name)) < completed), finished: completed >= flow.length, macro };
  }
  const std = await profile('Standard_BOM_Flow');
  const last = std?.[std.length - 1];
  const max = last
    ? (await db.registry.query(`SELECT skill_index FROM system_skills_registry WHERE mcp_tool_name = $1`, [last])).rows[0]?.skill_index
    : undefined;
  const maxIndex = typeof max === 'number' ? max : null;
  const finished = maxIndex !== null && completed >= maxIndex;
  const upperBound = maxIndex === null ? completed + 1 : Math.min(completed + 1, maxIndex);
  const { rows } = await db.registry.query(
    `SELECT skill_index, skill_name, macro_category, mcp_tool_name FROM system_skills_registry WHERE skill_index <= $1 ORDER BY skill_index`, [upperBound]);
  // the skill that just halted or is next: completed + 1, or the last real one once everything ran
  const macro = rows.find((r) => r.skill_index === (finished ? maxIndex : completed + 1))?.macro_category ?? rows[rows.length - 1]?.macro_category;
  return { steps: toSteps(rows, (r) => typeof r.skill_index === 'number' && r.skill_index <= completed), finished, macro };
}

/** ponytail: the DB records only completed and running skills; a failure is visible live in the right pane but is not stored, so 'failed' is never set here. */
export async function fetchRfqStatus(rfqId: string, dbSource: () => Promise<StatusDb> = realDb): Promise<RfqStatus> {
  const db = await dbSource();
  const meta = await db.fileMeta.query(`SELECT customer_name, project_name FROM rfq_project_tracking WHERE rfq_id = $1 LIMIT 1`, [rfqId]);
  const run = await db.fileMeta.query(`SELECT rfq_process_stage, hitl_required FROM rfq_process_tracking WHERE rfq_id = $1 AND is_active LIMIT 1`, [rfqId]);
  const base = {
    rfqId,
    exists: meta.rows.length > 0 || run.rows.length > 0,
    customer: (meta.rows[0]?.customer_name as string | undefined) ?? null,
    project: (meta.rows[0]?.project_name as string | undefined) ?? null,
  };
  const completed = run.rows[0]?.rfq_process_stage;
  if (typeof completed !== 'number') {
    return { ...base, started: false, stage: null, reviewPending: false, finished: false, steps: [] };
  }
  const p = await progress(db, rfqId, completed);
  return { ...base, started: true, stage: stageNumber(p.macro), reviewPending: run.rows[0]?.hitl_required === true, finished: p.finished, steps: p.steps };
}

const TAG = { done: '[DONE]', running: '[RUNNING]', failed: '[FAILED]' } as const;
const SHOWN_STEPS = 5;

/** The plain-language answer to "where is it?", every fact from the status row. */
export function describeStatus(s: RfqStatus): string {
  const who = [s.customer, s.project].filter(Boolean).join(' · ');
  const head = `${s.rfqId}${who ? ` (${who})` : ''}`;
  if (!s.exists) {
    return `I can't find ${s.rfqId} in the database.`;
  }
  if (!s.started) {
    return `${head} was created but no pipeline run has started yet: no files were uploaded. Upload the BOM and Volume files first.`;
  }
  const stage = s.stage === null ? 'stage unknown' : `stage ${s.stage} of 9 (${STAGE_NAMES[s.stage - 1]})`;
  const state = s.finished ? 'The pipeline has finished.' : 'The pipeline has not finished.';
  const review = s.reviewPending ? 'Review pending: yes, it is waiting for a person; resolve it on the review screen in the right pane.' : 'Review pending: no.';
  const recent = s.steps.slice(-SHOWN_STEPS).map((x) => `${TAG[x.state]} ${x.name}`).join('\n');
  return `${head}: ${stage}. ${state} ${review}${recent ? `\n\nLast steps:\n${recent}` : ''}`;
}
