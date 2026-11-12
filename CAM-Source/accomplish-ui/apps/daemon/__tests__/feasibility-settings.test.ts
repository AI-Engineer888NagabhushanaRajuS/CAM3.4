import { describe, it, expect } from 'vitest';
import { FEASIBILITY_DEFAULTS, feasibilityFromRow, validateFeasibilitySettings } from '../src/feasibility-settings.js';

const base = { ...FEASIBILITY_DEFAULTS };

describe('Settings > Feasibility rules', () => {
  it('an empty saved row means nothing is saved yet: the defaults apply', () => {
    expect(feasibilityFromRow(null)).toEqual({ settings: FEASIBILITY_DEFAULTS, saved: false });
    expect(feasibilityFromRow({})).toEqual({ settings: FEASIBILITY_DEFAULTS, saved: false });
    expect(feasibilityFromRow({ lead_time_limit_weeks: 12 })).toMatchObject({ saved: true, settings: { lead_time_limit_weeks: 12 } });
  });

  it('a valid set is returned checked: statuses trimmed, upper-cased, de-duplicated', () => {
    const out = validateFeasibilitySettings({ ...base, cannot_build_statuses: [' eol ', 'EOL', 'discontinued'], constraints: [] });
    expect(out.cannot_build_statuses).toEqual(['EOL', 'DISCONTINUED']);
    expect(out.lead_time_limit_weeks).toBe(20);
  });

  it('a lead-time limit outside 0-520 weeks is refused with the reason', () => {
    expect(() => validateFeasibilitySettings({ ...base, lead_time_limit_weeks: 0 })).toThrow(/lead-time limit/);
    expect(() => validateFeasibilitySettings({ ...base, lead_time_limit_weeks: 9999 })).toThrow(/lead-time limit/);
  });

  it('a machine rule must name a known column, a known operator and effect, and a value unless the operator needs none', () => {
    const rule = { name: 'No 0201', column: 'description', operator: 'contains', value: '0201', effect: 'cannot_build' };
    expect(validateFeasibilitySettings({ ...base, constraints: [rule] }).constraints).toEqual([rule]);
    expect(() => validateFeasibilitySettings({ ...base, constraints: [{ ...rule, column: 'drop table' }] })).toThrow(/unknown column/);
    expect(() => validateFeasibilitySettings({ ...base, constraints: [{ ...rule, operator: 'like' }] })).toThrow(/unknown operator/);
    expect(() => validateFeasibilitySettings({ ...base, constraints: [{ ...rule, effect: 'maybe' }] })).toThrow(/unknown effect/);
    expect(() => validateFeasibilitySettings({ ...base, constraints: [{ ...rule, value: '' }] })).toThrow(/needs a value/);
    expect(() => validateFeasibilitySettings({ ...base, constraints: [{ ...rule, name: '' }] })).toThrow(/needs a name/);
    const empty = { ...rule, operator: 'empty', value: '' };
    expect(validateFeasibilitySettings({ ...base, constraints: [empty] }).constraints).toHaveLength(1);
  });

  it('a numeric comparison needs a number', () => {
    const rule = { name: 'Heavy', column: 'quantity', operator: 'gt', value: 'ten', effect: 'high' };
    expect(() => validateFeasibilitySettings({ ...base, constraints: [rule] })).toThrow(/not a number/);
  });
});
