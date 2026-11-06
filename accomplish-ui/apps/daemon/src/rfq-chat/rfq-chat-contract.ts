/**
 * SPEC-019 contract between the daemon (rfq-chat/*), the HTTP routes and the web assistant. FROZEN while the build agents
 * work in parallel: add fields only (never rename or remove), and note every addition in SPECS/SPEC-019-... section A.
 * The web app cannot import this file; it mirrors these types in apps/web/src/client/lib/chatContract.ts.
 */
import type { MessageCitation } from '@accomplish_ai/agent-core';

/** What the conversation is about. 'none' = no RFQ chosen yet (normal chat). */
export type ChatScope = { mode: 'none' } | { mode: 'rfqs'; rfqIds: string[] } | { mode: 'all' };

export interface RfqOption {
  rfqId: string;
  customer: string | null;
  project: string | null;
  /** Pipeline steps finished (rfq_process_tracking.rfq_process_stage); null before the pipeline started. */
  stage: number | null;
  reviewPending: boolean;
  /** An exported workbook exists, so questions about numbers can be answered. */
  hasExport: boolean;
}

/** An instruction to the UI, sent next to the message text. The UI shows it; it never acts without the user. */
export type UiDirective =
  | { type: 'pick_rfq'; reason: string; options: RfqOption[]; allowAll: true; allowMultiple: true }
  | { type: 'disambiguate'; prompt: string; options: Array<{ id: string; label: string; detail?: string }> }
  | {
      type: 'confirm_action';
      action: 'create_rfq' | 'start_pipeline' | 'edit_value';
      summary: string;
      /** Exactly what will be done: customer, project, files, flow profile. Shown to the user before Confirm. */
      params: Record<string, unknown>;
      /** Single use, bound to the session and to `params`, valid 5 minutes. */
      confirmToken: string;
      expiresAt: string;
    }
  | { type: 'ask_upload'; accept: string[]; purpose: string }
  // Buttons the user presses in the bubble (assistant controls the app, 2026-11-05): the UI never navigates by itself.
  | { type: 'open_rfq'; rfqId: string }
  | { type: 'open_export'; rfqId: string }
  | { type: 'open_settings'; section: 'providers' }
  // SPEC-020: a button that opens the manifest editor (hash route #/manifests?path=<path>); path is relative to manifests/.
  | { type: 'open_manifest'; path: string; label: string };

export interface ChatRequest {
  messages: Array<{ role: string; content: string }>;
  scope?: ChatScope;
  /** Added by the routing agent: scanned files the user attached to this turn, for the create-RFQ intent (passed to proposeCreateRfq). */
  fileRefs?: Array<{ attachmentId: string; name: string; rfqId?: string }>;
}

export interface ChatResponse {
  message: string;
  citations: MessageCitation[];
  /** Which model phrased it; null when none was needed (a list, a refusal, a guide answer built from rows). */
  model: string | null;
  /** Legacy single-RFQ field: the RFQ the answer is about, when exactly one. */
  rfq_id: string | null;
  /** The scope the answer used; the UI shows it as chips and sends it back with the next question. */
  scope?: ChatScope;
  ui?: UiDirective;
}

/** POST /api/chat/actions/confirm */
export interface ActionConfirmRequest {
  confirmToken: string;
  decision: 'confirm' | 'cancel';
}

export interface ActionConfirmResponse {
  ok: boolean;
  message: string;
  rfqId?: string;
  /** SPEC-020: set to { type: 'open_export', rfqId } when an edit regenerated the reports, so the UI can offer the new version. */
  ui?: UiDirective;
  /** One entry per step actually attempted, in order, so a failure says where it stopped. */
  steps: Array<{ step: string; status: 'done' | 'failed' | 'skipped'; detail?: string }>;
}

/** The daemon-side action service (rfq-chat-actions.ts) as the conversation service sees it. */
export interface ChatActionDeps {
  /** Validates what the user asked for and returns the confirmation directive, or a message saying what is missing. */
  proposeCreateRfq(p: {
    sessionKey: string;
    request: string;
    fileRefs: Array<{ attachmentId: string; name: string }>;
  }): Promise<{ message: string; ui?: UiDirective }>;
  /**
   * Resume / start the pipeline of an existing RFQ (same GET /api/dify/start the UI uses). Refuses with a plain message
   * when the RFQ is unknown, not started, finished or waiting for a human review; otherwise returns a confirm_action card
   * (action 'start_pipeline', params { rfqId, stage, customer, project }).
   */
  proposeStartPipeline(p: { sessionKey: string; rfqId: string }): Promise<{ message: string; ui?: UiDirective }>;
  /**
   * SPEC-020: change one final_* value of one costed-BOM row and regenerate the reports. Refuses with a plain message when the
   * RFQ, row or field is unknown or not editable, or the value does not fit; otherwise returns a confirm_action card
   * (action 'edit_value', params { rfqId, bomItemId, label, field, fieldLabel, before, after }).
   */
  proposeEditValue(p: { sessionKey: string; rfqId: string; target: string; fieldText: string; value: string; volume?: number }): Promise<{ message: string; ui?: UiDirective }>;
  confirm(p: { sessionKey: string; req: ActionConfirmRequest; actor?: { name: string; email: string } }): Promise<ActionConfirmResponse>;
}
