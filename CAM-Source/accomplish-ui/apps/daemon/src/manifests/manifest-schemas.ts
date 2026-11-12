/**
 * SPEC-020: JSON Schema (draft-07) per manifest kind, written from the real files in manifests/{agent,skills,reporting,repo-approved}.
 * Served to Monaco (live validation + completion) and used by the save route, so the editor and the daemon never disagree.
 * Strict where the files agree (required keys, statuses, version and id shapes); permissive on free text (the files
 * carry prose, "[cite: 7]" markers and placeholder values), so most strings only get `examples`, not an `enum`.
 */
export type SchemaKind = 'agent' | 'skill' | 'reporting' | 'approved';
type Obj = Record<string, unknown>;

const str = (description: string, extra: Obj = {}): Obj => ({ type: 'string', description, ...extra });
const int = (description: string): Obj => ({ type: 'integer', minimum: 0, description });
const bool = (description: string): Obj => ({ type: 'boolean', description });
const list = (description: string, items: Obj = { type: 'string' }, extra: Obj = {}): Obj => ({ type: 'array', description, items, ...extra });
const obj = (description: string, properties: Obj, required: string[] = []): Obj => ({ type: 'object', description, properties, required });

const STATUS = ['DRAFT', 'APPROVED', 'APPROVED_INACTIVE'];
const status = (what: string): Obj => ({ type: 'string', enum: STATUS, description: `${what}. DRAFT = design input; APPROVED = built as described; APPROVED_INACTIVE = built but not currently exposed.` });
const version = (what: string): Obj => str(`${what}. Semver x.y.z with an optional suffix such as -draft. The daemon bumps the patch on every save and keeps the suffix.`, { pattern: '^\\d+\\.\\d+\\.\\d+(-[0-9A-Za-z.-]+)?$', examples: ['1.5.0-draft', '1.4.0'] });
const stamp = (what: string): Obj => str(`${what}. ISO date or date-time. The daemon rewrites it on save.`, { pattern: '^\\d{4}-\\d{2}-\\d{2}(T[0-9:.]+(Z|[+-]\\d{2}:\\d{2})?)?$' });

const governance = obj('Integrity and lifecycle. deterministic_hash and versioning.patch are rewritten by the daemon on every save.', {
  deterministic_hash: str('sha256 of the canonical JSON (sorted keys, 2-space indent) computed with this field set to "sha256:COMPUTED_ON_SAVE". Placeholders are accepted until the first save.', { pattern: '^sha256:([0-9a-f]{64}|[A-Z][A-Z_]*)$', examples: ['sha256:COMPUTED_ON_SAVE'] }),
  lifecycle: obj('Approval state of this manifest.', { state: status('Lifecycle state'), approval_required_for_change: bool('A change needs an approval step'), immutable_after_approval: bool('Approved content must not be edited in place') }, ['state']),
  versioning: obj('Semver parts; patch is bumped on save.', { major: int('Major'), minor: int('Minor'), patch: int('Patch') }, ['major', 'minor', 'patch']),
  note: str('Free-text governance note'),
}, ['deterministic_hash', 'versioning']); // the agent file has no lifecycle block

const skillMetadata = obj('Identity and version of this skill (or tool) manifest.', {
  macro_category: str('Pipeline stage group', { examples: ['Manufacturing_RFQ_Pipeline', 'intake'] }),
  skill_id: str('Stable id', { minLength: 1, examples: ['SKILL_01', 'M03.1_ScrubBOMStandardize'] }),
  skill_name: str('Display name', { minLength: 1 }),
  office_analogy: str('Plain-language analogy, e.g. "The Mail Room"'),
  skill_type: str('Execution style', { examples: ['Deterministic_Loopy_MCP', 'Deterministic_FastMCP', 'Deterministic_Manifest'] }),
  reusable: bool('Can be reused by other flows'),
  version: version('Manifest version'),
  status: status('Manifest status'),
  owner: str('Owning team or person'),
  created_at: stamp('Creation time'),
  updated_at: stamp('Last update time'),
  supersedes: str('What this replaces'),
  enabled: bool('false switches this skill off in the left pane (its stage greys out and locks). Missing means on.'),
  architecture_note: str('Design note'),
}, ['skill_id', 'skill_name', 'version', 'status']);

const agentMetadata = obj('Identity and version of the agent.', {
  agent_id: str('Stable id', { minLength: 1 }),
  agent_name: str('Display name', { minLength: 1 }),
  macro_category: str('Pipeline group'),
  version: version('Agent manifest version'),
  status: status('Agent manifest status'),
  owner: str('Owning team'),
  created_at: stamp('Creation time'),
  updated_at: stamp('Last update time'),
  total_skills: int('Number of skills in skill_sequence'),
  total_sub_skills: int('Number of sub-skills across all skills'),
}, ['agent_id', 'agent_name', 'version', 'status']);

const notifyLists = { ui_updates: list('What the UI shows'), database_updates: list('Tables written'), alerts: list('Alerts raised') };

/** I-S-A-T-V-O-N. N is `n_next` in the skill files and `n_notification` in the reporting and as-built files. */
function isatvon(kind: SchemaKind): Obj {
  const required = ['i_instructions', 's_source', 'a_automation', 't_tech_stack', 'o_outcome', kind === 'skill' ? 'n_next' : 'n_notification'];
  if (kind !== 'reporting') {
    required.push('v_variables'); // reporting hoists V to the top level
  }
  return obj('ISATVON definition: Instructions, Source, Automation, Tech stack, Variables, Outcome, Next/Notification.', {
    i_instructions: str('I: trigger, action, check and bound, in prose', { minLength: 1 }),
    s_source: obj('S: what the run reads', { required_inputs: list('Inputs the run needs'), fresh_state_parameters: list('State fetched fresh each run'), per_project_file_register: str('Where per-project files are registered') }, ['required_inputs']),
    a_automation: obj('A: how it runs and how success is checked', { orchestration_layer: str('Orchestrator'), trigger: str('What starts it'), action_step: str('The action'), acceptance_check: str('Programmatic pass condition') }, ['action_step', 'acceptance_check']),
    t_tech_stack: obj('T: tools used', { execution_layer: str('Engine'), action_tool: str('Tool that acts'), fixed_check_tool: str('Tool that checks'), gateway: str('Gateway'), telemetry_observer: str('Telemetry'), supporting_services: list('Other services') }, ['action_tool']),
    v_variables: obj('V: the knobs (bounds and gates)', { max_iterations: { type: ['integer', 'string'], description: 'Retry bound' }, success_gate: str('Success expression'), no_op_condition: str('When to do nothing'), escalation_condition: str('When to hand to a human'), budget_limit: str('Time or cost budget, e.g. "60000ms"') }),
    o_outcome: obj('O: what the run produces', { output_format: str('Output format'), json_schema: { type: ['string', 'object'], description: 'Name of, or inline, output schema' }, state_handoff_file: str('Where state is handed to the next step') }),
    n_next: obj('N (skill files): what happens next', { ...notifyLists, next_step: str('The hand-off to the next skill') }),
    n_notification: obj('N (reporting and as-built files): notifications', notifyLists),
  }, required);
}

const part = (description: string, properties: Obj): Obj => obj(description, properties);
const runtimeDef = obj('Runtime wiring declared by the design (not executed from here).', {
  orchestration: part('Router and trigger', { router: str('Router'), trigger: str('Trigger') }),
  execution: part('Engine', { engine: str('Engine') }),
  gateway: part('Gateway', { route_via: str('Gateway name') }),
  persistence: part('State store', { database: str('Database'), table: str('Table'), tables: list('Tables'), action: str('Action') }),
  audit: part('Audit', { telemetry: str('Telemetry sink') }),
  ui: part('UI target', { target: str('Target'), method: str('Method') }),
});

const contractSide = (what: string): Obj => obj(what, { type: str('Always "object"', { enum: ['object'] }), properties: { type: 'object', description: 'Field name to JSON Schema of that field (placeholders like "int" are tolerated)' }, required: list('Required field names') }, ['type', 'properties']);
const contracts = obj('Input and output contracts (JSON Schema objects).', { input_schema: contractSide('What the tool takes'), output_schema: contractSide('What the tool returns') }, ['input_schema', 'output_schema']);

const step = obj('One step', { step_id: str('Id like "1.1.1"', { pattern: '^\\d+\\.\\d+\\.\\d+$' }), action: str('What happens', { minLength: 1 }), mode: str('Who does it', { enum: ['Auto', 'Human'] }) }, ['step_id', 'action', 'mode']);
const subSkill = obj('One sub-skill', {
  sub_skill_id: str('Id like "1.1"', { pattern: '^\\d+\\.\\d+$' }),
  sub_skill_name: str('Name', { minLength: 1 }),
  enabled: bool('false greys this sub-skill out in the left pane. Missing means on.'),
  type: str('Kind of sub-skill', { examples: ['Ingestion & CRM Sync', 'Automated Processing', 'Ingestion / Query', 'Human Review Checkpoint', 'Human Final Action'] }),
  steps: list('Steps in order', step, { minItems: 1 }),
}, ['sub_skill_id', 'sub_skill_name', 'steps']);

const variableDef = obj('One named edge-case variable.', { description: str('What it controls'), refs: list('Source references'), default: { description: 'Default value (any JSON)' }, status: str('Confirmation state, free text', { examples: ['confirmed', 'unconfirmed'] }), applies_to: list('Report ids it affects') }, ['description', 'default']);
const reportVariables = { ...obj('V hoisted to the top level: every edge case as a named variable.', { _comment: str('Note') }), additionalProperties: variableDef };
const report = obj('One report', { report_id: str('Id like R01', { pattern: '^R\\d{2}$' }), tab_no: { type: 'integer', minimum: 1, description: 'Tab position in the workbook' }, sheet_name: str('Sheet name', { minLength: 1 }), requestor: str('Who asked'), output_format: str('Layout'), current_script: str('Current implementation'), inputs: list('Inputs'), edge_case_variables: list('Variables that affect it'), acceptance_checks: list('Checks') }, ['report_id', 'tab_no', 'sheet_name']);

/** What a left-pane button does: createRfq opens the intake dialog, scan and ingest are the intake steps, jump goes to the stage, info is a plain line. */
export const UI_ACTIONS = ['createRfq', 'scan', 'ingest', 'jump', 'info'];
const uiAction = obj('One button of the left pane', { label: str('Button text', { minLength: 1 }), action: str('What pressing it does', { enum: UI_ACTIONS }) }, ['label', 'action']);

const skillEntry = obj('One skill entry', { sequence: { type: 'integer', minimum: 1, description: 'Position' }, skill_id: str('Skill id'), manifest_file: str('Relative file, e.g. skills/skill_01_input_standardization.json', { pattern: '^skills/[A-Za-z0-9._-]+\\.json$' }), name: str('Skill name'), enabled: bool('false switches this skill off in the left pane. Missing means on.') }, ['sequence', 'skill_id', 'manifest_file']);

export function manifestSchema(kind: SchemaKind): Obj {
  const toolProps: Obj = { skill_metadata: skillMetadata, isatvon_definition: isatvon(kind), contracts, governance };
  let properties: Obj = toolProps;
  let required = ['skill_metadata', 'isatvon_definition', 'contracts', 'governance'];
  if (kind === 'agent') {
    properties = {
      agent_metadata: agentMetadata,
      runtime_routing: { type: 'object', description: 'Orchestration, gateway, persistence and UI choices (strings).' },
      skill_sequence: list('Skills in execution order; manifest_file is resolved under manifests/.', skillEntry),
      governance,
    };
    required = ['agent_metadata', 'skill_sequence', 'governance'];
  }
  if (kind === 'skill') {
    Object.assign(properties, { sub_skills: list('Sub-skills in order; each has steps.', subSkill, { minItems: 1 }), sri_runtime_definition: runtimeDef, ui_actions: list('SPEC-025: the buttons the left pane shows under this skill\'s stage, in order. Missing = the pane\'s built-in buttons; [] = no buttons.', uiAction) });
    required.push('sub_skills', 'sri_runtime_definition');
  }
  if (kind === 'reporting' || kind === 'approved') {
    properties.srim_runtime_definition = runtimeDef;
    required.push('srim_runtime_definition');
  }
  if (kind === 'reporting') {
    Object.assign(properties, { v_variables: reportVariables, reports: list('The reports this manifest describes, in tab order.', report, { minItems: 1 }) });
    required.push('v_variables', 'reports');
  }
  return { $schema: 'http://json-schema.org/draft-07/schema#', title: `CAM ${kind} manifest (ISATVON)`, type: 'object', properties, required };
}
