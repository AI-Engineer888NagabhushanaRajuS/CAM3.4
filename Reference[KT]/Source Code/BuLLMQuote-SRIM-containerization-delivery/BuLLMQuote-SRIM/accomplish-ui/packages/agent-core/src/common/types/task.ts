import type { OAuthProviderId } from './connector.js';

export type TaskStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'waiting_permission'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted';

/**
 * Originating surface for a task. Drives the no-UI auto-deny safeguard for
 * file-permission and question prompts:
 *   - `'ui'` (default): prompt the UI if connected; auto-deny if no UI client is attached.
 *   - `'whatsapp'`: route through the WhatsApp task-bridge, which auto-denies all prompts.
 *   - `'scheduler'`: scheduled/headless task; prompt UI only when connected, otherwise auto-deny.
 */
export type TaskSource = 'ui' | 'whatsapp' | 'scheduler';

export interface TaskConfig {
  prompt: string;
  taskId?: string;
  workingDirectory?: string;
  allowedTools?: string[];
  systemPromptAppend?: string;
  outputSchema?: object;
  sessionId?: string;
  /** Model ID for display name or CLI override */
  modelId?: string;
  /** Provider ID for CLI override */
  provider?: string;
  /**
   * User-attached files (drag-and-drop or file picker). Ephemeral — paths reference
   * the host filesystem at submission time and are not persisted with the task.
   */
  files?: FileAttachmentInfo[];
  /**
   * Originating surface. Callers (UI RPC, WhatsApp bridge, scheduler) set this so the
   * daemon can apply the right permission-prompt policy. Defaults to `'ui'` when omitted.
   */
  source?: TaskSource;
  /**
   * Workspace this task belongs to. Threaded into the daemon's `onBeforeStart`
   * so `resolveTaskConfig` can load per-workspace knowledge notes. Optional —
   * scheduler/WhatsApp tasks may run without a workspace context.
   */
  workspaceId?: string;
  /**
   * RFQ this chat is scoped to (BuLLMQuote-SRIM RFQ chat feature). Set from
   * the middle pane's own RfqContext when a task is created while an RFQ is
   * active in the left-pane search/accordion. Undefined for generic,
   * non-RFQ tasks — preserves default chat behavior unchanged. Never
   * trusted for authorization on its own; the daemon mints a fresh
   * RFQ-scoped JWT and treats that verified token, not this field, as the
   * source of truth before calling any RFQ-scoped backend endpoint.
   */
  rfqId?: string;
}

/** Metadata for a user-attached file in a task. */
export interface FileAttachmentInfo {
  /** Unique identifier for this attachment */
  id: string;
  /** Original filename */
  name: string;
  /** Absolute or working-directory-relative file path */
  path: string;
  /** Categorized file type based on extension */
  type: 'image' | 'text' | 'code' | 'pdf' | 'other';
  /** File size in bytes */
  size: number;
  /** Pre-read file content for text/code files (populated by IPC handler in Electron) */
  content?: string;
}

export interface Task {
  id: string;
  prompt: string;
  summary?: string;
  status: TaskStatus;
  sessionId?: string;
  messages: TaskMessage[];
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  result?: TaskResult;
  workspaceId?: string;
  /** RFQ this task is scoped to — see TaskConfig.rfqId. Stamped once at
   * task creation and persisted; `resumeSession` resolves it from here on
   * follow-up turns (same fallback pattern already used for workspaceId),
   * so the frontend does not need to re-send it on every message. */
  rfqId?: string;
}

export interface TaskAttachment {
  type: 'screenshot' | 'json';
  data: string;
  label?: string;
}

export interface TaskMessage {
  id: string;
  type: 'assistant' | 'user' | 'tool' | 'system';
  content: string;
  toolName?: string;
  /**
   * Tool-execution state for `type: 'tool'` messages. Populated by the SDK adapter from
   * `message.part.updated` events so the UI can render live state transitions:
   *   - `'running'`: tool invocation in progress (spinner)
   *   - `'completed'`: tool finished successfully (checkmark)
   *   - `'error'`: tool failed (red)
   *
   * Consumers should merge tool messages by stable `id` and preserve the latest `toolStatus`
   * rather than appending a new row per state transition.
   */
  toolStatus?: 'running' | 'completed' | 'error';
  toolInput?: unknown;
  timestamp: string;
  attachments?: TaskAttachment[];
  /** Model ID that produced this message (populated by the SDK adapter). */
  modelId?: string;
  /** Provider ID that produced this message (populated by the SDK adapter). */
  providerId?: string;
  /**
   * Source references for RFQ-chat answers (BuLLMQuote-SRIM RFQ chat
   * feature). Present only on assistant messages produced by the RFQ-chat
   * path; absent for scripted-QA and non-RFQ messages. Always populated
   * verbatim from the backend's own retrieval response — the LLM used for
   * answer synthesis is never given the ability to author this field
   * itself, so every citation traces back to a real source record.
   */
  citations?: MessageCitation[];
}

/**
 * A single source reference attached to an RFQ-chat assistant message.
 * Backend-authored (mcp-tools/rfq-memory), never LLM-generated — an
 * uncited claim in an answer is expected and safe; a fabricated citation
 * is not, so this type is only ever populated by copying the backend's own
 * `chunks[].citation` value, never constructed from free-text model output.
 */
export interface MessageCitation {
  sourceType: 'cbom_row' | 'bom_row' | 'gerber_checklist' | 'excel_export' | 'file_telemetry' | 'cognee_memory';
  /** Real, resolvable identifier fields specific to sourceType — e.g. for
   * 'cbom_row': { rfqId, cbomItemId, volumeNo, fg, cpn }; for
   * 'file_telemetry': { rfqId, version, fileRole, filePath }. */
  identifier: Record<string, string | number>;
  /** Short human-readable label rendered in the UI, e.g. "CBOM row — CPN
   * ABC123, Volume 2". Backend-provided, not derived client-side. */
  label: string;
}

export type TaskPauseAction =
  | {
      type: 'oauth-connect';
      providerId: OAuthProviderId;
      label: string;
      pendingLabel?: string;
      successText?: string;
    }
  | {
      type: 'google-file-picker';
      label: string;
      pendingLabel?: string;
      /** Pre-filled search query for the file picker UI */
      query?: string;
      /** Label of the Google account to open the picker for */
      accountLabel?: string;
      /** Email of the Google account to open the picker for */
      accountEmail?: string;
    };

export type TaskResult =
  | {
      status: 'success' | 'error' | 'interrupted';
      sessionId?: string;
      durationMs?: number;
      error?: string;
      pauseReason: 'oauth';
      pauseAction: Extract<TaskPauseAction, { type: 'oauth-connect' }>;
    }
  | {
      status: 'success' | 'error' | 'interrupted';
      sessionId?: string;
      durationMs?: number;
      error?: string;
      pauseReason: 'file-picker';
      pauseAction: Extract<TaskPauseAction, { type: 'google-file-picker' }>;
    }
  | {
      status: 'success' | 'error' | 'interrupted';
      sessionId?: string;
      durationMs?: number;
      error?: string;
    };

export type StartupStage =
  | 'starting'
  | 'browser'
  | 'environment'
  | 'loading'
  | 'connecting'
  | 'waiting';

/**
 * Array of all valid startup stage values.
 * Order reflects the typical startup progression.
 * Typed as readonly string[] for easy use with .includes() on string values.
 */
export const STARTUP_STAGES: readonly string[] = [
  'starting',
  'browser',
  'environment',
  'loading',
  'connecting',
  'waiting',
] as const satisfies readonly StartupStage[];

export interface TaskProgress {
  taskId: string;
  stage: 'init' | 'thinking' | 'tool-use' | 'waiting' | 'complete' | 'setup' | StartupStage;
  toolName?: string;
  toolInput?: unknown;
  percentage?: number;
  message?: string;
  modelName?: string;
  isFirstTask?: boolean;
}

export interface TaskUpdateEvent {
  taskId: string;
  type: 'message' | 'progress' | 'complete' | 'error';
  message?: TaskMessage;
  progress?: TaskProgress;
  result?: TaskResult;
  error?: string;
}
