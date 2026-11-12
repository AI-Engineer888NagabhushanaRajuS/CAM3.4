/**
 * SPEC-020: "open the Input Standardization manifest" gives a button that opens the manifest editor (#/manifests?path=...).
 * Rules decide, no model: the skill is found by number ("skill 4", "SKILL_04", "4th skill") or by the words of its name, and
 * the answer is a fixed sentence. The manifest list comes through an injectable loader: the real one reads the agent
 * manifest's skill_sequence from the manifests folder, the same index GET /api/manifests builds its tree from.
 */
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import type { ChatReply } from './rfq-chat-types.js';

export interface ManifestTree {
  agent: { path: string; name: string; skills: Array<{ path: string; id: string; name: string; sequence: number }> } | null;
  reporting: { path: string; name: string } | null;
}
export type LoadManifests = () => Promise<ManifestTree>;

const AGENT_FILE = join('agent', 'agent_manifest.json');
const REPORTING_FILE = join('reporting', 'cam_isatvon_manifest.json');

/** The manifests folder sits in the repo next to docs/: CAM_MANIFESTS_DIR, else look upward from the working directory and from this file (tsup bundles to CJS). */
function findManifestsDir(): string | null {
  const override = process.env.CAM_MANIFESTS_DIR;
  if (override && existsSync(join(override, AGENT_FILE))) {
    return override;
  }
  for (const start of [process.cwd(), typeof __dirname === 'string' ? __dirname : ''].filter(Boolean)) {
    let dir = resolve(start);
    for (let i = 0; i < 8; i++) {
      if (existsSync(join(dir, 'manifests', AGENT_FILE))) {
        return join(dir, 'manifests');
      }
      dir = dirname(dir);
    }
  }
  return null;
}

export const loadManifestTree: LoadManifests = async () => {
  const root = findManifestsDir();
  if (!root) {
    throw new Error('the manifests folder was not found');
  }
  // Manifests are data: parsed, never executed.
  const agent = JSON.parse(readFileSync(join(root, AGENT_FILE), 'utf8')) as {
    agent_metadata?: { agent_name?: string };
    skill_sequence?: Array<{ sequence: number; skill_id: string; manifest_file: string; name: string }>;
  };
  return {
    agent: {
      path: 'agent/agent_manifest.json',
      name: agent.agent_metadata?.agent_name ?? 'Agent manifest',
      skills: (agent.skill_sequence ?? []).map((s) => ({ path: s.manifest_file, id: s.skill_id, name: s.name, sequence: s.sequence })),
    },
    reporting: existsSync(join(root, REPORTING_FILE)) ? { path: 'reporting/cam_isatvon_manifest.json', name: 'Reporting manifest' } : null,
  };
};

const FILLER = new Set(['the', 'a', 'an', 'me', 'my', 'please', 'skill', 'skills', 'manifest', 'manifests', 'json', 'file', 'in', 'editor', 'to', 'for', 'of', 'and', 'open', 'show', 'view', 'display', 'edit', 'go', 'take', 'pull', 'up', 'can', 'you', 'could']);
const words = (s: string): string[] => s.toLowerCase().replace(/&/g, ' ').split(/[^a-z0-9]+/).filter(Boolean);
const NUMBER = /\bskill[\s_#]*(?:no\.?|number)?[\s_#]*0?(\d{1,2})\b|\b0?(\d{1,2})(?:st|nd|rd|th)?\s+skill\b/i;

const OPEN_NOTE = 'It opens in the manifest editor. Saving versions it; a skill\'s enabled flag switches its pipeline steps, its sequence and ui_actions shape the left pane, and the rest is design input.';

export async function manifestReply(question: string, load: LoadManifests | undefined, hasRfqScope: boolean): Promise<Partial<ChatReply> & { message: string } | null> {
  if (!load) {
    return { message: "I can't read the manifest list here. Open Manifests from the app menu." };
  }
  let tree: ManifestTree;
  try {
    tree = await load();
  } catch (err) {
    return { message: `I can't read the manifest list right now (${err instanceof Error ? err.message : String(err)}).` };
  }
  const skills = tree.agent?.skills ?? [];
  const open = (path: string, label: string) => ({ message: `Press the button to open ${label} in the editor. ${OPEN_NOTE}`, ui: { type: 'open_manifest' as const, path, label } });
  const rest = words(question).filter((w) => !FILLER.has(w));
  const num = NUMBER.exec(question);
  const n = num ? Number(num[1] ?? num[2]) : null;

  // "skill 4" is the number in the skill's id (SKILL_04), not its place in the run order (SPEC-025 made `sequence` the execution order).
  const no = (s: { id: string }): number => Number(/(\d+)/.exec(s.id)?.[1]);
  if (n !== null && skills.some((s) => no(s) === n)) {
    const s = skills.find((x) => no(x) === n)!;
    return open(s.path, `skill ${no(s)}, ${s.name}`);
  }
  if (tree.agent && rest.length === 1 && rest[0] === 'agent') {
    return open(tree.agent.path, tree.agent.name);
  }
  if (tree.reporting && rest.length === 1 && ['reporting', 'report', 'reports'].includes(rest[0])) {
    return open(tree.reporting.path, tree.reporting.name);
  }
  const named = rest.length === 0 ? [] : skills.filter((s) => {
    const have = words(s.name);
    return rest.every((w) => have.includes(w)) || have.filter((w) => w !== 'and').every((w) => rest.includes(w));
  });
  if (named.length === 1) {
    return open(named[0].path, `${named[0].name} (skill ${no(named[0])})`);
  }
  // With an RFQ in view, "show the manifest" / "show the skill history" are about that RFQ's workbook, not the editor: a data question.
  const clearlyEditor = /\bjson\b/i.test(question) || (rest.length > 0 && /\bmanifests?\b/i.test(question)) || (rest.length === 0 && /\bskill\b/i.test(question));
  if (hasRfqScope && !clearlyEditor) {
    return null;
  }
  const list = (named.length > 1 ? named : skills).map((s) => `${no(s)}. ${s.name}`).join('; ');
  const what = named.length > 1 ? 'That matches more than one skill manifest' : skills.length ? "I can't tell which manifest you mean" : 'There are no skill manifests on this machine';
  return { message: `${what}${skills.length ? `: ${list}. Say "open the <name> manifest" or "open skill <number>"` : ''}.${tree.agent ? ' "Open the agent manifest" and "open the reporting manifest" also work.' : ''}` };
}
