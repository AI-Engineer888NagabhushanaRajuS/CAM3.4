/**
 * Feasibility & Risk rules (Settings > Feasibility), stored in logic_db.feasibility_settings (one row, id = 1).
 * The reporting pipeline (mcp-tools/reporting/superset/reports/feasibility_risk.py) reads the same row on every run.
 * A row whose settings are empty means "nothing saved yet": the documented defaults apply, and the pipeline says so.
 */
export const FEASIBILITY_COLUMNS = [
  'fg', 'assembly', 'cpn', 'description', 'manufacturer', 'mpn', 'commodity', 'quantity', 'unit_of_measure', 'part_status',
  'ce_remarks', 'drawing_reference', 'designators', 'part_type', 'ltb_date', 'inventory_stock',
] as const;
export const FEASIBILITY_OPERATORS = ['contains', 'not_contains', 'equals', 'not_equals', 'gt', 'gte', 'lt', 'lte', 'empty', 'not_empty'] as const;
export const FEASIBILITY_EFFECTS = ['cannot_build', 'high', 'medium'] as const;

export interface MachineRule {
  name: string;
  column: string;
  operator: string;
  value: string;
  effect: string;
}

export interface FeasibilitySettings {
  lead_time_limit_weeks: number;
  cannot_build_statuses: string[];
  medium_statuses: string[];
  no_price_cannot_build: boolean;
  no_lead_time_high: boolean;
  ltb_high: boolean;
  ncnr_medium: boolean;
  expired_validity_medium: boolean;
  constraints: MachineRule[];
}

export const FEASIBILITY_DEFAULTS: FeasibilitySettings = {
  lead_time_limit_weeks: 20,
  cannot_build_statuses: ['EOL', 'DISCONTINUED'],
  medium_statuses: ['NRFND'],
  no_price_cannot_build: true,
  no_lead_time_high: true,
  ltb_high: true,
  ncnr_medium: true,
  expired_validity_medium: true,
  constraints: [],
};

const text = (v: unknown): string => (typeof v === 'string' ? v.trim() : typeof v === 'number' ? String(v) : '');

/** Checked settings from a request body. Throws an Error naming the first rule that cannot work (the panel shows the message). */
export function validateFeasibilitySettings(raw: unknown): FeasibilitySettings {
  if (!raw || typeof raw !== 'object') { throw new Error('settings must be an object'); }
  const r = raw as Record<string, unknown>;
  const limit = Number(r.lead_time_limit_weeks);
  if (!Number.isFinite(limit) || limit <= 0 || limit > 520) { throw new Error('The lead-time limit must be between 0 and 520 weeks'); }
  const statuses = (v: unknown, field: string): string[] => {
    if (!Array.isArray(v)) { throw new Error(`${field} must be a list`); }
    return [...new Set(v.map(text).filter(Boolean).map((x) => x.toUpperCase().replace(/-/g, ' ')))];
  };
  const constraints = Array.isArray(r.constraints) ? r.constraints : [];
  const rules = constraints.map((c, i): MachineRule => {
    const rule = (c ?? {}) as Record<string, unknown>;
    const out = { name: text(rule.name), column: text(rule.column), operator: text(rule.operator), value: text(rule.value), effect: text(rule.effect) };
    if (!out.name) { throw new Error(`Machine rule ${i + 1} needs a name`); }
    if (!(FEASIBILITY_COLUMNS as readonly string[]).includes(out.column)) { throw new Error(`Machine rule "${out.name}": unknown column "${out.column}"`); }
    if (!(FEASIBILITY_OPERATORS as readonly string[]).includes(out.operator)) { throw new Error(`Machine rule "${out.name}": unknown operator`); }
    if (!(FEASIBILITY_EFFECTS as readonly string[]).includes(out.effect)) { throw new Error(`Machine rule "${out.name}": unknown effect`); }
    const needsValue = out.operator !== 'empty' && out.operator !== 'not_empty';
    if (needsValue && !out.value) { throw new Error(`Machine rule "${out.name}" needs a value`); }
    if (['gt', 'gte', 'lt', 'lte'].includes(out.operator) && !Number.isFinite(Number(out.value))) { throw new Error(`Machine rule "${out.name}": "${out.value}" is not a number`); }
    return out;
  });
  return {
    lead_time_limit_weeks: limit,
    cannot_build_statuses: statuses(r.cannot_build_statuses, 'Cannot-build statuses'),
    medium_statuses: statuses(r.medium_statuses, 'Medium-risk statuses'),
    no_price_cannot_build: r.no_price_cannot_build === true,
    no_lead_time_high: r.no_lead_time_high === true,
    ltb_high: r.ltb_high === true,
    ncnr_medium: r.ncnr_medium === true,
    expired_validity_medium: r.expired_validity_medium === true,
    constraints: rules,
  };
}

/** The stored row as the panel reads it: `saved` false when nothing was saved yet (the defaults are shown). */
export function feasibilityFromRow(settings: unknown): { settings: FeasibilitySettings; saved: boolean } {
  const isEmpty = !settings || (typeof settings === 'object' && Object.keys(settings as object).length === 0);
  if (isEmpty) { return { settings: FEASIBILITY_DEFAULTS, saved: false }; }
  return { settings: { ...FEASIBILITY_DEFAULTS, ...(settings as Partial<FeasibilitySettings>) }, saved: true };
}
