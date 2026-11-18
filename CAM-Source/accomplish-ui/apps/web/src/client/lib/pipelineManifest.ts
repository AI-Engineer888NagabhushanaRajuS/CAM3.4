/**
 * SPEC-023: the left pane follows the manifests. The agent manifest lists the skills and each skill file its sub-skills;
 * `enabled: false` on a skill or sub-skill (edited in #/manifests) switches it off in the pane, a skill with no flag is on.
 * The pane's stage ids stay as they are (the live progress is keyed on them); this file only says which skill backs which stage.
 */
import { useEffect, useState } from 'react';
import { fetchManifestTree, type ManifestTree, type SkillNode } from './manifestsApi';

/** Stage of the left pane -> the manifest skill that backs it. supplierRfq (SKILL_05) has no backend step yet: it shows its manifest sub-skills and reads "Not in this pipeline". */
export const STAGE_SKILL: Record<string, string> = {
  intake: 'SKILL_01',
  extraction: 'SKILL_02',
  risk: 'SKILL_03',
  pricing: 'SKILL_04',
  supplierRfq: 'SKILL_05',
  erpDataSync: 'SKILL_06',
  pricingConsolidation: 'SKILL_07',
  priceDecision: 'SKILL_08',
  reportingAnalytics: 'SKILL_09',
  quoteReadiness: 'SKILL_10',
};

/** The manifest skill of a stage, or undefined while the manifests have not loaded (the pane then behaves as before). */
export function skillForStage(tree: ManifestTree | null, stageId: string): SkillNode | undefined {
  const id = STAGE_SKILL[stageId];
  return id ? tree?.agent?.skills.find((s) => s.id === id) : undefined;
}

/** SPEC-025: the stages in the manifest's `sequence` order. Stable, so with no manifest (or a stage it does not name) the built-in order stays. */
export function orderStages<T extends { id: string }>(stages: readonly T[], tree: ManifestTree | null): T[] {
  const at = (id: string) => skillForStage(tree, id)?.sequence ?? Number.MAX_SAFE_INTEGER;
  return [...stages].sort((a, b) => at(a.id) - at(b.id));
}

/** SPEC-025: the buttons under a stage: the skill's `ui_actions` when the manifest lists them (an empty list = none), else the built-in ones. */
export function stageActions(skill: SkillNode | undefined, builtIn: ReadonlyArray<{ label: string; action: string }>): ReadonlyArray<{ label: string; action: string }> {
  return skill?.uiActions ?? builtIn;
}

/** Skills of the manifest that no stage shows. */
export function unwiredSkills(tree: ManifestTree | null): SkillNode[] {
  const wired = new Set(Object.values(STAGE_SKILL));
  return tree?.agent?.skills.filter((s) => !wired.has(s.id)) ?? [];
}

const REFRESH_MS = 20_000;

/** The manifest tree, refreshed every 20 s and when the tab regains focus, so an edit in #/manifests shows without a reload. Null until loaded or when the service says no. */
export function usePipelineManifest(): ManifestTree | null {
  const [tree, setTree] = useState<ManifestTree | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => {
      fetchManifestTree().then((t) => { if (alive) setTree(t); }, () => { /* signed out or daemon down: keep what is shown */ });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    const onVisible = () => { if (document.visibilityState === 'visible') load(); };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', load);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', load);
    };
  }, []);
  return tree;
}
