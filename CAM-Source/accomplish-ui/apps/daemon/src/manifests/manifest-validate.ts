/** SPEC-020: validate manifest text against its kind's schema (ajv, draft-07) and read the few fields the tree and save need. */
import Ajv, { type ValidateFunction } from 'ajv';
import { manifestSchema, type SchemaKind } from './manifest-schemas.js';
import type { ManifestKind } from './manifest-paths.js';

export interface ValidationError {
  path: string;
  message: string;
}
export interface Validation {
  ok: boolean;
  errors: ValidationError[];
}
export type Doc = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- manifests are untrusted JSON; every read below is guarded by the schema or a typeof check

// strict:false because the schema carries `examples`/descriptions the strict-mode keyword list would otherwise reject.
const ajv = new Ajv({ allErrors: true, strict: false });
const compiled = new Map<SchemaKind, ValidateFunction>();

function validator(kind: SchemaKind): ValidateFunction {
  let v = compiled.get(kind);
  if (!v) {
    v = ajv.compile(manifestSchema(kind));
    compiled.set(kind, v);
  }
  return v;
}

/** Parse + validate. `doc` is null when the text is not a JSON object. Runtime manifests are parse-only (scripts/validate_manifests.py owns their rules). */
export function validateManifest(kind: ManifestKind, text: string): { doc: Doc | null; validation: Validation } {
  let doc: unknown;
  try {
    doc = JSON.parse(text);
  } catch (e) {
    return { doc: null, validation: { ok: false, errors: [{ path: '/', message: `Invalid JSON: ${e instanceof Error ? e.message : String(e)}` }] } };
  }
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
    return { doc: null, validation: { ok: false, errors: [{ path: '/', message: 'A manifest must be a JSON object' }] } };
  }
  if (kind === 'runtime') {
    return { doc: doc as Doc, validation: { ok: true, errors: [] } };
  }
  const v = validator(kind);
  if (v(doc)) {
    return { doc: doc as Doc, validation: { ok: true, errors: [] } };
  }
  const errors = (v.errors ?? []).slice(0, 50).map((e) => {
    const allowed = Array.isArray(e.params?.allowedValues) ? `: ${e.params.allowedValues.join(', ')}` : '';
    return { path: e.instancePath || '/', message: `${e.message ?? 'invalid'}${allowed}` };
  });
  return { doc: doc as Doc, validation: { ok: false, errors } };
}

const text = (v: unknown): string | null => (typeof v === 'string' ? v : null);

/** id, name, version, status from whichever metadata block the file has (agent, skill, or the runtime manifests' top level). */
export function metaOf(doc: Doc | null): { id: string | null; name: string | null; version: string | null; status: string | null } {
  const a = doc?.agent_metadata;
  const s = doc?.skill_metadata;
  if (a && typeof a === 'object') {
    return { id: text(a.agent_id), name: text(a.agent_name), version: text(a.version), status: text(a.status) };
  }
  if (s && typeof s === 'object') {
    return { id: text(s.skill_id), name: text(s.skill_name), version: text(s.version), status: text(s.status) };
  }
  return { id: text(doc?.id), name: text(doc?.name), version: text(doc?.version), status: null };
}
