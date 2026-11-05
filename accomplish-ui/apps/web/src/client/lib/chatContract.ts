/**
 * SPEC-019 chat contract, mirrored for the web. SOURCE OF TRUTH (frozen, add fields only):
 * apps/daemon/src/rfq-chat/rfq-chat-contract.ts. The web cannot import the daemon, so keep this file in step with it.
 * Also holds the few pure helpers and the one confirm call the assistant UI needs.
 */
import type { MessageCitation } from '@accomplish_ai/agent-core';
import { backendUrl } from '@/config/endpoints';
import { clearSession, getSessionToken } from '@/lib/session';

/** What the conversation is about. 'none' = no RFQ chosen yet (normal chat). */
export type ChatScope = { mode: 'none' } | { mode: 'rfqs'; rfqIds: string[] } | { mode: 'all' };

export interface RfqOption {
  rfqId: string;
  customer: string | null;
  project: string | null;
  /** Pipeline steps finished; null before the pipeline started. */
  stage: number | null;
  reviewPending: boolean;
  /** An exported workbook exists, so questions about numbers can be answered. */
  hasExport: boolean;
}

export interface DisambiguateOption {
  id: string;
  label: string;
  detail?: string;
}

export type UiDirective =
  | { type: 'pick_rfq'; reason: string; options: RfqOption[]; allowAll: true; allowMultiple: true }
  | { type: 'disambiguate'; prompt: string; options: DisambiguateOption[] }
  | {
      type: 'confirm_action';
      action: 'create_rfq' | 'start_pipeline' | 'edit_value';
      summary: string;
      /** Exactly what will be done: customer, project, files, flow profile. start_pipeline: { rfqId, stage, customer, project }. edit_value: { rfqId, bomItemId, label, field, fieldLabel, before, after }. */
      params: Record<string, unknown>;
      confirmToken: string;
      expiresAt: string;
    }
  | { type: 'ask_upload'; accept: string[]; purpose: string }
  /** Buttons only: the user presses them, the UI never acts alone. open_rfq selects the RFQ like the left list does. */
  | { type: 'open_rfq'; rfqId: string }
  | { type: 'open_export'; rfqId: string }
  | { type: 'open_settings'; section: 'providers' }
  /** SPEC-020: opens the manifest editor at #/manifests?path=<path> (path relative to manifests/). */
  | { type: 'open_manifest'; path: string; label: string };

export interface ChatResponse {
  message: string;
  citations: MessageCitation[];
  model: string | null;
  rfq_id: string | null;
  scope?: ChatScope;
  ui?: UiDirective;
}

/** The model switch in the assistant: auto = OpenRouter when a key is saved, else local; the others force one. */
export type ChatProviderMode = 'auto' | 'local' | 'openrouter';

/** GET /api/chat/providers: what the switch can offer right now (never the key itself). */
export interface ChatProvidersInfo {
  local: { model: string };
  openrouter: { hasKey: boolean; model: string };
  defaultMode: ChatProviderMode;
}

/** A released attachment the question may refer to ("create an RFQ from this file"); rfqId = where it was scanned. */
export interface FileRef {
  attachmentId: string;
  name: string;
  rfqId?: string;
}

/**
 * Where files are scanned and kept before any RFQ exists: one scratch scope per browser tab. The bridge accepts any
 * id of letters, digits, `_` and `-`; the daemon only ever reads a file back after the bridge says both engines released it.
 */
export function chatStagingId(): string {
  try {
    const kept = sessionStorage.getItem('cam-chat-staging');
    if (kept) return kept;
  } catch { /* storage blocked: a fresh id per page load is fine */ }
  const id = `CHAT-${(globalThis.crypto?.randomUUID?.() ?? `${Date.now()}${Math.random()}`).replace(/[^A-Za-z0-9]/g, '').slice(0, 20)}`;
  try { sessionStorage.setItem('cam-chat-staging', id); } catch { /* see above */ }
  return id;
}

export interface ActionConfirmRequest {
  confirmToken: string;
  decision: 'confirm' | 'cancel';
}

export interface ActionStep {
  step: string;
  status: 'done' | 'failed' | 'skipped';
  detail?: string;
}

export interface ActionConfirmResponse {
  ok: boolean;
  message: string;
  rfqId?: string;
  /** SPEC-020: { type: 'open_export', rfqId } when an edit regenerated the reports. */
  ui?: UiDirective;
  steps: ActionStep[];
}

export const NO_SCOPE: ChatScope = { mode: 'none' };

/** Selecting an RFQ in the left list scopes the conversation to it; no selection = normal chat. */
export function defaultScope(rfqId: string | null): ChatScope {
  return rfqId ? { mode: 'rfqs', rfqIds: [rfqId] } : NO_SCOPE;
}

export function scopeFromIds(ids: string[]): ChatScope {
  return ids.length > 0 ? { mode: 'rfqs', rfqIds: ids } : NO_SCOPE;
}

/** The RFQ id when the scope is exactly one RFQ. */
export function singleRfq(scope: ChatScope): string | null {
  return scope.mode === 'rfqs' && scope.rfqIds.length === 1 ? scope.rfqIds[0] : null;
}

/** Anything that is not a well-formed scope (old storage, an older daemon) is dropped. */
export function parseScope(value: unknown): ChatScope | undefined {
  const v = value as { mode?: unknown; rfqIds?: unknown } | null;
  if (v?.mode === 'none' || v?.mode === 'all') return { mode: v.mode };
  if (v?.mode === 'rfqs' && Array.isArray(v.rfqIds)) return scopeFromIds(v.rfqIds.filter((i): i is string => typeof i === 'string'));
  return undefined;
}

/** Keeps a directive only when it has the shape the UI draws; a malformed one is ignored rather than crashing the chat. */
export function parseUi(value: unknown): UiDirective | undefined {
  const ui = value as Partial<Record<string, unknown>> | null;
  switch (ui?.type) {
    case 'pick_rfq':
    case 'disambiguate':
      return Array.isArray(ui.options) ? (ui as unknown as UiDirective) : undefined;
    case 'confirm_action':
      return typeof ui.confirmToken === 'string' && ui.params && typeof ui.params === 'object' ? (ui as unknown as UiDirective) : undefined;
    case 'ask_upload':
      return Array.isArray(ui.accept) ? (ui as unknown as UiDirective) : undefined;
    case 'open_rfq':
    case 'open_export':
      return typeof ui.rfqId === 'string' && ui.rfqId.trim() ? (ui as unknown as UiDirective) : undefined;
    case 'open_settings':
      return ui.section === 'providers' ? (ui as unknown as UiDirective) : undefined;
    case 'open_manifest':
      return typeof ui.path === 'string' && ui.path.trim() && typeof ui.label === 'string' ? (ui as unknown as UiDirective) : undefined;
    default:
      return undefined;
  }
}

/** The hash route of the manifest editor for a manifest path. */
export const manifestHash = (path: string): string => `#/manifests?path=${encodeURIComponent(path)}`;

// Assumption: a disambiguation option whose id looks like an RFQ id (RFQ-00001, RFQ-CENTUM-PROOF-24) carries an RFQ.
const RFQ_ID = /^RFQ-[\w-]+$/i;
export const isRfqId = (id: string) => RFQ_ID.test(id);

/**
 * POST /api/chat/actions/confirm. Uses the signed-in session token like /api/chat does: the daemon's protected routes
 * check that token (the bridge tokens of authFetch are RFQ-bound and would be refused here).
 */
export async function confirmAction(req: ActionConfirmRequest): Promise<ActionConfirmResponse> {
  const token = getSessionToken();
  const res = await fetch(backendUrl('/api/chat/actions/confirm'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(req),
  });
  if (res.status === 401) {
    clearSession();
    window.location.hash = '#/login';
    throw new Error('Your session has expired. Please sign in again.');
  }
  const data = (await res.json().catch(() => ({}))) as Partial<ActionConfirmResponse> & { error?: string };
  if (typeof data.ok === 'boolean' && Array.isArray(data.steps)) return data as ActionConfirmResponse;
  throw new Error(data.error ?? `The assistant service answered HTTP ${res.status}.`);
}
