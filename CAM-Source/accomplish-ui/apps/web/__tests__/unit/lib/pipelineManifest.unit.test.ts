import { describe, it, expect } from 'vitest';
import { orderStages, skillForStage, stageActions, STAGE_SKILL, unwiredSkills } from '@/lib/pipelineManifest';
import type { ManifestTree, SkillNode } from '@/lib/manifestsApi';

const skill = (n: number, over: Partial<SkillNode> = {}): SkillNode => ({
  path: `skills/s${n}.json`, id: `SKILL_${String(n).padStart(2, '0')}`, name: `Skill ${n}`, sequence: n, version: '1.5.0-draft', status: 'DRAFT', hash: 'h',
  subSkills: [{ id: `${n}.1`, name: 'First', type: 'Automated Processing', stepCount: 2, enabled: true }], enabled: true, ...over,
});
const tree = (skills: SkillNode[]): ManifestTree => ({
  agent: { path: 'agent/a.json', id: 'A', name: 'Agent', version: '1', status: 'DRAFT', hash: 'h', skills }, reporting: null, approved: [], runtime: [],
});

describe('left pane follows the manifests (SPEC-023)', () => {
  it('maps a stage to the skill that backs it; before the manifests load there is nothing to follow', () => {
    const t = tree(Array.from({ length: 10 }, (_, i) => skill(i + 1)));
    expect(skillForStage(t, 'intake')?.id).toBe('SKILL_01');
    expect(skillForStage(t, 'priceDecision')?.id).toBe('SKILL_08');
    expect(skillForStage(t, 'nope')).toBeUndefined();
    expect(skillForStage(null, 'intake')).toBeUndefined();
  });

  it('a skill switched off in the manifest is visible as enabled:false on its stage', () => {
    const t = tree([skill(1), skill(2, { enabled: false })]);
    expect(skillForStage(t, 'extraction')?.enabled).toBe(false);
    expect(skillForStage(t, 'intake')?.enabled).toBe(true);
  });

  it('SPEC-025: the stages follow the manifest sequence, and keep the built-in order without a manifest', () => {
    const stages = [{ id: 'intake' }, { id: 'extraction' }, { id: 'pricing' }];
    expect(orderStages(stages, null).map((s) => s.id)).toEqual(['intake', 'extraction', 'pricing']);
    const t = tree([skill(1, { sequence: 3 }), skill(2, { sequence: 1 }), skill(4, { sequence: 2 })]);
    expect(orderStages(stages, t).map((s) => s.id)).toEqual(['extraction', 'pricing', 'intake']);
  });

  it('SPEC-025: the buttons come from the skill\'s ui_actions; none listed means the built-in ones, an empty list means none', () => {
    const builtIn = [{ label: 'Old', action: 'jump' }];
    expect(stageActions(undefined, builtIn)).toEqual(builtIn);
    expect(stageActions(skill(1), builtIn)).toEqual(builtIn);
    expect(stageActions(skill(1, { uiActions: [{ label: 'New', action: 'scan' }] }), builtIn)).toEqual([{ label: 'New', action: 'scan' }]);
    expect(stageActions(skill(1, { uiActions: [] }), builtIn)).toEqual([]);
  });

  it('the supplier RFQ skill has no stage and is reported as not wired', () => {
    expect(Object.values(STAGE_SKILL)).not.toContain('SKILL_05');
    const t = tree(Array.from({ length: 10 }, (_, i) => skill(i + 1)));
    expect(unwiredSkills(t).map((s) => s.id)).toEqual(['SKILL_05']);
    expect(unwiredSkills(null)).toEqual([]);
  });
});
