import { EventEmitter } from 'node:events';
import { tmpdir, homedir } from 'node:os';
import {
  createTaskManager,
  createTaskId,
  createMessageId,
  getModelDisplayName,
  type TaskManagerAPI,
  type TaskCallbacks,
  type TaskConfig,
  type Task,
  type TaskMessage,
  type TaskStatus,
  type StorageAPI,
  type PermissionResponse,
  type TaskSource,
  type FileAttachmentInfo,
} from '@accomplish_ai/agent-core';
import {
  type TaskConfigBuilderOptions,
  isCliAvailable,
  onBeforeStart,
  createOnBeforeTaskStart,
  createTaskCallbacks,
} from './task-config-builder.js';
import { OpenCodeServerManager } from './opencode/server-manager.js';
import { log } from './logger.js';
import { chatReply } from './rfq-chat/rfq-chat-service.js';
import { makeChatDeps } from './rfq-chat/rfq-chat-deps.js';

import { type TaskServiceEvents, type TaskServiceOptions } from './task-service-events.js';

export type { TaskServiceEvents, TaskServiceOptions };


export class TaskService extends EventEmitter {
  private taskManager: TaskManagerAPI;
  private storage: StorageAPI;
  private opts: TaskConfigBuilderOptions;
  private rpcConnectivityProbe: { hasConnectedClients(): boolean };
  private serverManager: OpenCodeServerManager;

  /**
   * Per-task origin map. Populated at task start, read by the source-based
   * no-UI auto-deny policy in `task-callbacks.ts` (Phase 2 of the SDK cutover
   * port) and cleared when the task is removed from activeTasks. Not intended
   * for RPC exposure; strictly internal to the daemon.
   */
  private taskSources = new Map<string, TaskSource>();

  constructor(storage: StorageAPI, options: TaskServiceOptions) {
    super();
    this.storage = storage;
    this.opts = {
      ...options,
      isPackaged: options.isPackaged ?? false,
      resourcesPath: options.resourcesPath ?? '',
      appPath: options.appPath ?? '',
      accomplishRuntime: options.accomplishRuntime,
    };
    // Default probe: treat UI as always connected. Tests + tooling that
    // construct TaskService without an RPC server get this default — the
    // no-UI auto-deny path is never triggered, which keeps unit tests
    // deterministic. The real daemon wires `rpc.hasConnectedClients`.
    this.rpcConnectivityProbe = options.rpcConnectivityProbe ?? {
      hasConnectedClients: () => true,
    };

    // Drop the per-task source entry when the task finishes, whether via
    // success, error, or cancel. Listening to our own emitter (task-callbacks
    // emits into `this`) keeps the bookkeeping local without exposing the map.
    this.on('complete', (data: { taskId: string }) => {
      this.taskSources.delete(data.taskId);
      this.serverManager.scheduleTaskRuntimeCleanup(data.taskId);
    });
    this.on('error', (data: { taskId: string }) => {
      this.taskSources.delete(data.taskId);
      this.serverManager.scheduleTaskRuntimeCleanup(data.taskId);
    });
    // The cancel path originally had no terminal callback — `TaskManager.
    // cancelTask()` just aborts the adapter without emitting `complete` or
    // `error`, so the internal `taskSources` entry and the per-task
    // `opencode serve` runtime both leaked every time a user cancelled a
    // task. `stopTask` now emits `'statusChange'` with `status: 'cancelled'`
    // after it asks the TaskManager to abort, and this listener runs the
    // same cleanup the other two terminal paths run.
    this.on('statusChange', (data: { taskId: string; status: string }) => {
      if (data.status === 'cancelled') {
        this.taskSources.delete(data.taskId);
        this.serverManager.scheduleTaskRuntimeCleanup(data.taskId);
      }
    });

    // Per-task `opencode serve` manager. Spawns one serve process per task,
    // cleans up on idle. The `getServerUrl` closure below is handed to the
    // SDK adapter so it can connect its `createOpencodeClient` to the right
    // runtime.
    this.serverManager = new OpenCodeServerManager({
      storage,
      userDataPath: this.opts.userDataPath,
      mcpToolsPath: this.opts.mcpToolsPath,
      isPackaged: this.opts.isPackaged,
      resourcesPath: this.opts.resourcesPath,
      appPath: this.opts.appPath,
      accomplishRuntime: this.opts.accomplishRuntime,
    });

    this.taskManager = createTaskManager({
      adapterOptions: {
        platform: process.platform,
        isPackaged: this.opts.isPackaged,
        tempPath: tmpdir(),
        // The SDK adapter no longer spawns a CLI per task — `opencode serve`
        // is started by `OpenCodeServerManager` (one per task) and the SDK
        // talks HTTP. `onBeforeStart` still runs to write the per-task
        // `opencode.json`, sync API keys to `auth.json`, and surface
        // `OPENCODE_CONFIG[_DIR]` so the spawned `opencode serve` picks them up.
        //
        // The adapter passes a per-task `ctx` with `taskId` + `workspaceId`;
        // we forward it unchanged. `resolveTaskConfig` inside `onBeforeStart`
        // consumes `ctx.workspaceId` for knowledge-note injection and uses
        // `ctx.taskId` to compute a per-task config filename.
        onBeforeStart: async (ctx) => {
          const result = await onBeforeStart(this.storage, this.opts, ctx);
          // Return the rich `OnBeforeStartResult` shape so the adapter
          // can inject `workspaceInstructions` as a compact `system`
          // block on every `session.prompt` call. Agent-level prompts
          // alone lose to provider-native instruction channels; see
          // `OpenCodeAdapter.buildWorkspaceInstructionRuntimeBlock`.
          return {
            env: result.env,
            ...(result.workspaceInstructions
              ? { workspaceInstructions: result.workspaceInstructions }
              : {}),
          };
        },
        // SDK-based adapter resolves its `opencode serve` URL here. The
        // optional `ctx` carries the same per-task context into the
        // server-manager's own `onBeforeStart` call so the spawned
        // `opencode serve` sees the workspace-scoped config.
        getServerUrl: async (taskId, ctx) => {
          await this.serverManager.ensureTaskRuntime(taskId, ctx);
          return this.serverManager.waitForServerUrl(taskId);
        },
        getModelDisplayName,
        // Optional proxy tagger — the adapter calls this on task start
        // (with taskId) and teardown (with undefined). Wired by the daemon
        // when the optional runtime package is present; undefined for
        // pure OSS builds (no-op).
        setProxyTaskId: options.setProxyTaskId,
      },
      defaultWorkingDirectory: homedir(),
      maxConcurrentTasks: 10,
      isCliAvailable: () => isCliAvailable(this.opts),
      onBeforeTaskStart: createOnBeforeTaskStart(this.opts),
    });
  }

  async startTask(params: {
    prompt: string;
    taskId?: string;
    modelId?: string;
    sessionId?: string;
    workingDirectory?: string;
    workspaceId?: string;
    systemPromptAppend?: string;
    /**
     * User-attached files forwarded from the desktop IPC layer. Must flow
     * into `TaskConfig.files` so OpenCode picks them up — the RPC schema
     * at `daemon.ts:86` + `validation.ts:22` already accepts this field,
     * and `validateTaskConfig` passes it through. Dropping it here means
     * every drag-and-drop / attachment a user submits is silently lost.
     */
    attachments?: FileAttachmentInfo[];
    /**
     * Originating surface. Drives the no-UI auto-deny safeguard for
     * permission/question prompts when the task runs headlessly. Defaults
     * to `'ui'` when not provided. WhatsApp bridge and scheduler callers
     * must set this explicitly.
     */
    source?: TaskSource;
    /**
     * Restrict the OpenCode agent to a subset of tool names. Forwarded
     * from the desktop IPC and accepted by both the RPC schema
     * (`TaskStartParams.allowedTools`) and the zod taskConfigSchema.
     * Dropping it here means the "advertised but silently ignored"
     * gap Codex P2 flagged.
     */
    allowedTools?: string[];
    /**
     * Machine-readable output schema the task should produce. Same
     * "daemon advertised but dropped" gap — RPC accepts it, config type
     * accepts it, `validateTaskConfig` passes it through; this builder
     * must forward it into `config.outputSchema`.
     */
    outputSchema?: object;
    /**
     * RFQ this chat is scoped to (BuLLMQuote-SRIM RFQ chat feature). See
     * TaskConfig.rfqId's own docstring in agent-core. Undefined for
     * generic, non-RFQ tasks -- behavior for those is byte-for-byte
     * unchanged (falls straight through to COMING_SOON_MESSAGE below, same
     * as before this feature existed).
     */
    rfqId?: string;
  }): Promise<Task> {
    // Scripted BOM/RFQ demo Q&A fast path -- checked before any LLM/agent work
    // happens. If the prompt matches a known question shape (FG count for an
    // RFQ, price/supplier/lead-time for an MPN), answer directly from a plain
    // HTTP call to the pipeline's own lookup service -- no OpenCode session,
    // no Ollama, no MCP tool-calling involved at all. Fails open (falls
    // through to the normal flow below) if that service is unreachable/slow,
    // so this can never block or break a normal task.
    const scriptedAnswer = await this._tryScriptedBomAnswer(params.prompt);
    if (scriptedAnswer !== null) {
      return this._completeWithScriptedAnswer(params, scriptedAnswer);
    }

    // Everything else is answered from RFQ results too, never from a model's own memory: rfq-chat/rfq-chat-service.ts.
    const grounded = await this._groundedAnswer([{ role: 'user', content: params.prompt }], params.rfqId);
    return this._completeWithRfqChatAnswer(params, grounded.message, grounded.citations);
  }

  /** The one way a chat question is answered: from the RFQ's results (or the RFQ list), verified, never a bare model. */
  private async _groundedAnswer(
    messages: Array<{ role: string; content: string }>,
    rfqId?: string,
  ): Promise<{ message: string; citations: import('@accomplish_ai/agent-core').MessageCitation[] }> {
    try {
      return await chatReply(
        { rfqId: rfqId ?? null, messages },
        makeChatDeps(
          { getApiKey: (p) => this.storage.getApiKey(p), getSelectedModel: () => this.storage.getSelectedModel() },
          'task',
        ),
      );
    } catch (err) {
      log.warn(`[RfqChat] grounded answer failed: ${err}`);
      return { message: "I couldn't answer that right now. Nothing was guessed; please try again in a moment.", citations: [] };
    }
  }

  /**
   * Checks the scripted BOM/RFQ Q&A lookup service (bom_qa_lookup_server.py,
   * a plain HTTP endpoint -- not MCP, not LLM-facing) for a known-question-shape
   * answer. Returns null on no match, an unreachable service, or a timeout --
   * any of those should silently fall through to the normal agent flow, never
   * surface as an error to the user.
   */
  private async _tryScriptedBomAnswer(prompt: string): Promise<string | null> {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);
      let res: Response;
      try {
        const BOM_QA_LOOKUP_URL = (process.env.BOM_QA_LOOKUP_URL ?? 'http://100.121.36.255:8006').replace(/\/$/, '');
        res = await fetch(`${BOM_QA_LOOKUP_URL}/ask`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: prompt }),
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeout);
      }
      if (!res.ok) {
        log.warn(`[ScriptedBomQA] lookup service returned HTTP ${res.status} for prompt: ${prompt}`);
        return null;
      }
      const data = (await res.json()) as { matched?: boolean; answer?: string };
      log.info(`[ScriptedBomQA] prompt=${JSON.stringify(prompt)} matched=${!!data.matched}`);
      return data.matched && data.answer ? data.answer : null;
    } catch (err) {
      log.warn(`[ScriptedBomQA] lookup call failed, falling through to normal flow: ${err}`);
      return null;
    }
  }

  /**
   * Builds and persists a synthetic completed Task carrying a scripted answer.
   *
   * The RETURNED task's `messages` array includes both the user question and
   * the answer directly -- unlike a real OpenCode task (which returns while
   * still 'running' and streams the answer later via a live `message` event),
   * this one is already fully answered by the time `startTask` resolves, so
   * there's no reason to split it across "initial return value" + "later
   * event". The frontend (`task-execution-actions.ts`) puts the RPC-returned
   * task straight into `currentTask` state and renders from its `messages`,
   * so leaving the assistant reply out of that array (as an earlier version
   * of this code did, copying the real flow's pattern) meant the answer only
   * ever existed as a live SSE event -- which arrives near-instantly here,
   * likely before the UI has even navigated to the execution page and started
   * listening, so it was silently missed and nothing displayed.
   *
   * Still emits `message`/`complete` too, for the case where the chat is
   * already open and watching this exact task (e.g. a follow-up message).
   */
  private _completeWithScriptedAnswer(
    params: { prompt: string; taskId?: string; workspaceId?: string; rfqId?: string },
    answer: string,
    citations?: import('@accomplish_ai/agent-core').MessageCitation[],
  ): Task {
    const taskId = params.taskId || createTaskId();
    const now = new Date().toISOString();
    const userMessage: TaskMessage = {
      id: createMessageId(),
      type: 'user',
      content: params.prompt,
      timestamp: now,
    };
    const assistantMessage: TaskMessage = {
      id: createMessageId(),
      type: 'assistant',
      content: answer,
      timestamp: now,
      ...(citations && citations.length > 0 ? { citations } : {}),
    };
    const task: Task = {
      id: taskId,
      prompt: params.prompt,
      status: 'completed',
      messages: [userMessage, assistantMessage],
      createdAt: now,
      startedAt: now,
      completedAt: now,
      result: { status: 'success' },
      workspaceId: params.workspaceId,
      rfqId: params.rfqId,
    };
    this.storage.saveTask(task, params.workspaceId);
    this.emit('message', { taskId, messages: [assistantMessage] });
    this.emit('complete', { taskId, result: task.result });
    return task;
  }

  /** RFQ-chat variant of _completeWithScriptedAnswer -- same persistence/
   * event-emission shape, with citations attached to the assistant message
   * (plan §0.D: always the backend-sourced array, never LLM free text). */
  private _completeWithRfqChatAnswer(
    params: { prompt: string; taskId?: string; workspaceId?: string; rfqId?: string },
    answer: string,
    citations: import('@accomplish_ai/agent-core').MessageCitation[],
  ): Task {
    return this._completeWithScriptedAnswer(params, answer, citations);
  }

  /** Appends a scripted/RFQ-chat answer to an EXISTING task's message
   * list (follow-up turns) -- unlike _completeWithScriptedAnswer, which
   * constructs a brand-new Task record, this uses the same
   * addTaskMessage/updateTaskStatus pattern resumeSession's own
   * user-message append already uses just above, so a follow-up answer
   * doesn't clobber the task's existing history. */
  private _completeFollowUp(
    existingTaskId: string,
    answer: string,
    citations?: import('@accomplish_ai/agent-core').MessageCitation[],
  ): Task {
    const assistantMessage: TaskMessage = {
      id: createMessageId(),
      type: 'assistant',
      content: answer,
      timestamp: new Date().toISOString(),
      ...(citations && citations.length > 0 ? { citations } : {}),
    };
    this.storage.addTaskMessage(existingTaskId, assistantMessage);
    const completedAt = new Date().toISOString();
    this.storage.updateTaskStatus(existingTaskId, 'completed', completedAt);
    this.emit('message', { taskId: existingTaskId, messages: [assistantMessage] });
    this.emit('complete', { taskId: existingTaskId, result: { status: 'success' } });
    const task = this.storage.getTask(existingTaskId) as Task;
    return task;
  }

  async stopTask(params: { taskId: string }): Promise<void> {
    const { taskId } = params;
    const completedAt = new Date().toISOString();
    // Emit `statusChange` with `'cancelled'` in BOTH branches so every
    // terminal listener runs the same cleanup chain that success/error
    // already trigger:
    //   - task-event-forwarding refreshes the health service active-task
    //     count and notifies desktop via `task.statusChange` RPC;
    //   - this class's own listener (registered in the constructor)
    //     deletes the `taskSources` entry and schedules the per-task
    //     `opencode serve` runtime for idle cleanup.
    // Before this change `stopTask` only touched storage, so cancelled
    // tasks leaked their runtime and their source entry until the daemon
    // was restarted.
    if (this.taskManager.isTaskQueued(taskId)) {
      this.taskManager.cancelQueuedTask(taskId);
      this.storage.updateTaskStatus(taskId, 'cancelled', completedAt);
      this.emit('statusChange', { taskId, status: 'cancelled', completedAt });
      return;
    }
    if (this.taskManager.hasActiveTask(taskId)) {
      await this.taskManager.cancelTask(taskId);
      this.storage.updateTaskStatus(taskId, 'cancelled', completedAt);
      this.emit('statusChange', { taskId, status: 'cancelled', completedAt });
    }
  }

  async interruptTask(params: { taskId: string }): Promise<void> {
    const { taskId } = params;
    if (this.taskManager.hasActiveTask(taskId)) {
      await this.taskManager.interruptTask(taskId);
    }
  }

  async resumeSession(params: {
    sessionId: string;
    prompt: string;
    existingTaskId?: string;
    /** Same rationale as `startTask.attachments` — follow-up turns also
     * carry user-attached files and must forward them into TaskConfig.files. */
    attachments?: FileAttachmentInfo[];
    /**
     * Caller-supplied workspace for the resumed turn. When the caller
     * omits this but `existingTaskId` is present, we fall back to the
     * workspace the original task was saved under so workspace knowledge
     * notes keep flowing across resume turns.
     */
    workspaceId?: string;
  }): Promise<Task> {
    const { sessionId, prompt, existingTaskId, attachments } = params;
    const taskId = existingTaskId || createTaskId();

    if (existingTaskId) {
      const userMessage: TaskMessage = {
        id: createMessageId(),
        type: 'user',
        content: prompt,
        timestamp: new Date().toISOString(),
      };
      this.storage.addTaskMessage(existingTaskId, userMessage);
    }

    // RFQ-chat resolution order (mirrors workspaceId's own fallback just
    // below): explicit param, else the rfqId the original task was
    // stamped with at creation -- the frontend does not need to re-send
    // rfqId on every follow-up keystroke.
    let rfqId: string | undefined;
    if (existingTaskId) {
      rfqId = this.storage.getTask(existingTaskId)?.rfqId;
    }

    // Same scripted-QA / RFQ-chat short-circuit startTask applies, checked
    // here too since follow-up turns go through this method, not
    // startTask. Only reachable when there's an existing task to append
    // to (the follow-up case this feature targets) -- a resumeSession
    // call with no existingTaskId falls through to _runTask unchanged.
    if (existingTaskId) {
      const scriptedAnswer = await this._tryScriptedBomAnswer(prompt);
      if (scriptedAnswer !== null) {
        return this._completeFollowUp(existingTaskId, scriptedAnswer);
      }
      const prior = (this.storage.getTask(existingTaskId)?.messages ?? [])
        .filter((m) => m.type === 'user' || m.type === 'assistant')
        .map((m) => ({ role: m.type as string, content: m.content }));
      const grounded = await this._groundedAnswer(prior.length ? prior : [{ role: 'user', content: prompt }], rfqId);
      return this._completeFollowUp(existingTaskId, grounded.message, grounded.citations);
    }

    const activeModel = this.storage.getActiveProviderModel();
    const selectedModel = activeModel || this.storage.getSelectedModel();
    // Workspace resolution order:
    //   1. explicit `params.workspaceId` (caller knows best)
    //   2. the workspace the existing task was saved under (resume case)
    //   3. undefined (fresh session with no workspace context)
    let workspaceId = params.workspaceId;
    if (!workspaceId && existingTaskId) {
      workspaceId = this.storage.getTask(existingTaskId)?.workspaceId;
    }
    const task = await this._runTask(taskId, {
      prompt,
      sessionId,
      taskId,
      modelId: selectedModel?.model,
      files: attachments,
      workspaceId,
    });

    if (existingTaskId) {
      this.storage.updateTaskStatus(existingTaskId, task.status, new Date().toISOString());
    }
    return task;
  }

  private async _runTask(taskId: string, config: TaskConfig): Promise<Task> {
    const callbacks: TaskCallbacks = createTaskCallbacks(
      taskId,
      this,
      this.storage,
      this.taskManager,
      {
        rpc: this.rpcConnectivityProbe,
        getTaskSource: (id) => this.getTaskSource(id),
        // Bind sendResponse for the auto-deny path. Callback-in-object form
        // sidesteps the circular "TaskService constructs callbacks that call
        // back into TaskService" problem — no `this` capture at setup time.
        sendPermissionResponse: async (id, response) => {
          await this.sendResponse(id, response);
        },
      },
    );
    return this.taskManager.startTask(taskId, config, callbacks);
  }

  listTasks(workspaceId?: string, includeUnassigned = false): Task[] {
    return this.storage.getTasks(workspaceId, includeUnassigned) as Task[];
  }

  getTaskStatus(params: {
    taskId: string;
  }): { taskId: string; status: TaskStatus; prompt: string; createdAt: string } | null {
    const task = this.storage.getTask(params.taskId);
    if (!task) {
      return null;
    }
    return { taskId: task.id, status: task.status, prompt: task.prompt, createdAt: task.createdAt };
  }

  getActiveTaskId(): string | null {
    return this.taskManager.getActiveTaskId();
  }
  hasActiveTask(taskId: string): boolean {
    return this.taskManager.hasActiveTask(taskId);
  }
  getActiveTaskCount(): number {
    return this.taskManager.getActiveTaskCount();
  }

  async sendResponse(taskId: string, response: PermissionResponse): Promise<void> {
    await this.taskManager.sendResponse(taskId, response);
  }

  /**
   * Task origin lookup — used by `task-callbacks.ts` `onPermissionRequest` to
   * decide whether to emit a UI prompt, route through the WhatsApp bridge,
   * or immediately auto-deny when no UI client is connected and the task
   * was not started by WhatsApp or another auto-denying caller.
   */
  getTaskSource(taskId: string): TaskSource {
    return this.taskSources.get(taskId) ?? 'ui';
  }

  dispose(): void {
    this.serverManager.dispose();
    this.taskManager.dispose();
  }
}
