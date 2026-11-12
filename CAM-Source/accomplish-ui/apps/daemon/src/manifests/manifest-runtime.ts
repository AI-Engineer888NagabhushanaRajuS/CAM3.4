/**
 * SPEC-025: a skill's `enabled` flag in the manifests really switches its pipeline tools on or off.
 * The pipeline already skips any tool that is in no quote_routing_profiles.routing_sequence (fastapi_router's ROUTING GATE reads it fresh on
 * every call), and the Settings > Skills toggle writes that table. This file is the same switch driven from the manifest, and back:
 *   manifest save          -> applySkillEnabled()  -> routing_sequence
 *   Settings toggle        -> syncManifestFromTool() -> the skill's `enabled` in its manifest file
 * Skills with no tool in system_skills_registry (SKILL_05) stay display-only.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { hashText, manifestsDir, resolveManifestPath } from './manifest-paths.js';
import { saveManifest } from './manifest-store.js';
import { buildTree } from './manifest-tree.js';

export interface Db {
  query(sql: string, params?: unknown[]): Promise<{ rows: Array<Record<string, unknown>> }>;
}

/** Manifest skill -> the backend macro_category numbers of its tools (the pane's STAGE_SKILL x MACRO_CATEGORY_TO_STAGE, 0 = staged intake). */
export const SKILL_MACROS: Record<string, number[]> = {
  SKILL_01: [0, 1],
  SKILL_02: [2],
  SKILL_04: [3],
  SKILL_06: [4],
  SKILL_03: [5],
  SKILL_07: [6],
  SKILL_08: [7],
  SKILL_10: [8],
  SKILL_09: [9],
};

/** A tool that is switched off remembers the profiles it was in, so switching on puts it back only there (RFQ_Flow's gerber step must not land in Standard_BOM_Flow). */
const MEMORY = 'skill_toggle_memory';
const DEFAULT_PROFILE = 'Standard_BOM_Flow';

interface Tool {
  name: string;
  index: number;
  macro: number;
}

async function registryTools(db: Db): Promise<Tool[]> {
  // Run order = macro_category, then skill_index (a step added later, like Feasibility & Risk at macro 5, sits between its neighbours without renumbering).
  const r = await db.query('SELECT mcp_tool_name, skill_index, macro_category FROM system_skills_registry WHERE is_active = true ORDER BY macro_category, skill_index');
  return r.rows.map((x) => ({ name: String(x.mcp_tool_name), index: Number(x.skill_index), macro: Number(x.macro_category) }));
}

const seq = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : typeof v === 'string' ? (JSON.parse(v) as string[]) : []);

/**
 * An RFQ's rfq_process_stage counts the steps it has done, by position in its routing sequence. Switching a tool on or off in the middle of that
 * sequence moves every later step by one, so an RFQ already past that point must move with it, or it would repeat or skip a step on resume.
 * The new stage is the position after the last step in `after` that the RFQ has done (a step added behind it is skipped for that RFQ, one added ahead of it runs next). Standard_BOM_Flow RFQs only (no RFQ_Flow exists in this deployment;
 * a volume-file RFQ is left alone when an RFQ_Flow profile does).
 */
export async function realignInFlight(logic: Db, meta: Db, before: string[], after: string[]): Promise<number> {
  const rfqFlow = (await logic.query(`SELECT 1 FROM quote_routing_profiles WHERE profile_name = 'RFQ_Flow' AND jsonb_array_length(routing_sequence) > 0`)).rows.length > 0;
  const { rows } = await meta.query(
    `SELECT rfq_id, rfq_process_stage FROM rfq_process_tracking WHERE is_active AND rfq_process_stage > 0` +
    (rfqFlow ? ` AND rfq_id NOT IN (SELECT rfq_id FROM rfq_file_telemetry WHERE file_role = 'VOLUME')` : ''));
  let moved = 0;
  for (const r of rows) {
    const done = new Set(before.slice(0, Number(r.rfq_process_stage)));
    const stage = after.reduce((n, t, i) => (done.has(t) ? i + 1 : n), 0);
    if (stage !== Number(r.rfq_process_stage)) {
      await meta.query('UPDATE rfq_process_tracking SET rfq_process_stage = $1, updated_at = NOW() WHERE rfq_id = $2 AND is_active', [stage, r.rfq_id]);
      moved++;
    }
  }
  return moved;
}

/** Switch every tool of one skill on or off in every routing profile. Returns the tool names it touched. */
export async function applySkillEnabled(db: Db, skillId: string, enabled: boolean, meta?: Db): Promise<string[]> {
  const macros = SKILL_MACROS[skillId];
  if (!macros) {
    return [];
  }
  const tools = (await registryTools(db)).filter((t) => macros.includes(t.macro));
  if (tools.length === 0) {
    return [];
  }
  await db.query(`CREATE TABLE IF NOT EXISTS ${MEMORY} (tool_name text PRIMARY KEY, profiles jsonb NOT NULL)`);
  const all = await registryTools(db);
  const order = new Map(all.map((t, i) => [t.name, i]));   // `all` is already in run order
  const profiles = (await db.query('SELECT profile_name, routing_sequence FROM quote_routing_profiles')).rows.map((p) => ({ name: String(p.profile_name), sequence: seq(p.routing_sequence) }));
  const remembered = new Map((await db.query(`SELECT tool_name, profiles FROM ${MEMORY}`)).rows.map((m) => [String(m.tool_name), seq(m.profiles)]));
  const touched = new Set(tools.map((t) => t.name));

  for (const p of profiles) {
    let next = p.sequence;
    if (enabled) {
      const add = tools.map((t) => t.name).filter((n) => {
        const homes = remembered.get(n);
        const live = profiles.some((q) => q.sequence.includes(n));
        return !p.sequence.includes(n) && (homes ? homes.includes(p.name) : !live && p.name === DEFAULT_PROFILE);
      });
      next = [...p.sequence, ...add].sort((a, b) => (order.get(a) ?? Infinity) - (order.get(b) ?? Infinity));
    } else {
      next = p.sequence.filter((n) => !touched.has(n));
    }
    if (next.join('\n') !== p.sequence.join('\n')) {
      await db.query('UPDATE quote_routing_profiles SET routing_sequence = $1::jsonb, updated_at = NOW() WHERE profile_name = $2', [JSON.stringify(next), p.name]);
      if (meta && p.name === DEFAULT_PROFILE) {
        await realignInFlight(db, meta, p.sequence, next);
      }
    }
  }
  for (const t of tools) {
    if (enabled) {
      await db.query(`DELETE FROM ${MEMORY} WHERE tool_name = $1`, [t.name]);
    } else {
      const was = profiles.filter((p) => p.sequence.includes(t.name)).map((p) => p.name);
      if (was.length > 0) {
        await db.query(`INSERT INTO ${MEMORY} (tool_name, profiles) VALUES ($1, $2::jsonb) ON CONFLICT (tool_name) DO UPDATE SET profiles = EXCLUDED.profiles`, [t.name, JSON.stringify(was)]);
      }
    }
  }
  return tools.map((t) => t.name);
}

/** skill id -> enabled, as the manifest tree reads it from disk now. */
export function enabledBySkill(): Map<string, boolean> {
  return new Map((buildTree().agent?.skills ?? []).map((s) => [s.id, s.enabled]));
}

/** The Settings toggle changed one tool: bring the skill's `enabled` in the manifest in line (on when any of its tools runs). Returns the skill id it rewrote, or null. */
export async function syncManifestFromTool(db: Db, toolName: string, who: string): Promise<string | null> {
  const tools = await registryTools(db);
  const macro = tools.find((t) => t.name === toolName)?.macro;
  const skillId = Object.keys(SKILL_MACROS).find((k) => macro !== undefined && SKILL_MACROS[k].includes(macro));
  if (!skillId) {
    return null;
  }
  const live = new Set((await db.query('SELECT DISTINCT tool FROM quote_routing_profiles, jsonb_array_elements_text(routing_sequence) AS tool')).rows.map((r) => String(r.tool)));
  const anyOn = tools.some((t) => SKILL_MACROS[skillId].includes(t.macro) && live.has(t.name));
  const node = buildTree().agent?.skills.find((s) => s.id === skillId);
  const p = node && resolveManifestPath(node.path);
  const abs = p && join(manifestsDir(), p.rel);
  if (!p || !abs || !existsSync(abs)) {
    return null;
  }
  const old = readFileSync(abs, 'utf8');
  const doc = JSON.parse(old);
  // Only the skill file's own flag is the Settings toggle's to change; a skill the agent manifest switched off stays off.
  if ((doc.skill_metadata.enabled !== false) === anyOn) {
    return null;
  }
  if (anyOn) {
    delete doc.skill_metadata.enabled;
  } else {
    doc.skill_metadata.enabled = false;
  }
  const res = saveManifest(p, JSON.stringify(doc, null, 2) + '\n', hashText(old), who);
  return res.code === 200 ? skillId : null;
}
