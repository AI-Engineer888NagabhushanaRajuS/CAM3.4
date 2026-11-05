/**
 * BrowserApiServer — HTTP+SSE server on 127.0.0.1:9234 built into the daemon.
 * Lets a browser tab at localhost:5173 call daemon services directly without
 * Electron, enabling `pnpm dev:web` to work with the real backend.
 */
import http from 'node:http';
import { createTaskId, BROWSER_API_PORT, WEB_DEV_ORIGIN } from '@accomplish_ai/agent-core';
import type { StorageAPI, AccomplishRuntime, StorageDeps } from '@accomplish_ai/agent-core';
import type { TaskService } from './task-service.js';
import type { SettingsService } from './settings-service.js';
import type { WorkspaceService } from './workspace-service.js';
import type { SecretsService } from './secrets-service.js';
import type { ConnectorService } from './connector-service.js';
import type { SchedulerService } from './scheduler-service.js';
import type { WhatsAppDaemonService } from './whatsapp-service.js';
import type { SkillsService } from './skills-service.js';
import { log } from './logger.js';
import { matchTestLogin } from './test-login.js';
import type { OpenAiOauthManager } from './opencode/auth-openai.js';
import { chatReply } from './rfq-chat/rfq-chat-service.js';
import { parseScope } from './rfq-chat/rfq-chat-scope.js';
import type { ActionConfirmRequest, ChatRequest, ChatScope } from './rfq-chat/rfq-chat-contract.js';
import { makeChatDeps } from './rfq-chat/rfq-chat-deps.js';
import { describeChatProviders, parseProviderMode, type ChatProviderMode } from './rfq-chat/rfq-chat-models.js';
// import { getBomItemsByRfq } from './auth/bom-duckdb-logic.js';
import { fileMetadataPool, pgPool } from './db.js';

// Address comes from the central registry (agent-core/common/constants), with
// env overrides so a port/domain change needs no code edits.
const PORT = Number(process.env.ACCOMPLISH_BACKEND_PORT) || BROWSER_API_PORT;
const ORIGIN = process.env.ACCOMPLISH_WEB_ORIGIN || WEB_DEV_ORIGIN;

// NetBird management API base URL — override for self-hosted deployments.
// e.g. ACCOMPLISH_NETBIRD_API_URL=https://netbird.yourcompany.com
const NETBIRD_API_BASE = (
  process.env.ACCOMPLISH_NETBIRD_API_URL ?? 'https://api.netbird.io'
).replace(/\/$/, '');

// Allowed CORS origins — ACCOMPLISH_WEB_ORIGIN is the primary, with optional
// comma-separated extras in ACCOMPLISH_EXTRA_ORIGINS (e.g. http://100.121.25.134:5173).
const _ALLOWED_ORIGINS: Set<string> = new Set(
  [ORIGIN, ...(process.env.ACCOMPLISH_EXTRA_ORIGINS ?? '').split(',')]
    .map((o) => o.trim())
    .filter(Boolean),
);

/**
 * Trim whitespace and strip one layer of matching surrounding quotes from a
 * user-entered API key (e.g. a key pasted as `"sk-..."` or `'nvapi-...'`).
 * Stray quotes otherwise become part of the `Authorization: Bearer` header and
 * every provider call fails auth.
 */
function sanitizeApiKey(raw: string): string {
  let k = (raw ?? '').trim();
  if (
    k.length >= 2 &&
    ((k.startsWith('"') && k.endsWith('"')) || (k.startsWith("'") && k.endsWith("'")))
  ) {
    k = k.slice(1, -1).trim();
  }
  return k;
}

export interface BrowserApiServices {
  taskService: TaskService;
  settingsService: SettingsService;
  workspaceService: WorkspaceService;
  secretsService: SecretsService;
  connectorService: ConnectorService;
  schedulerService: SchedulerService;
  storage: StorageAPI;
  skillsService: SkillsService;
  whatsappService: WhatsAppDaemonService;
  accomplishRuntime: AccomplishRuntime;
  openAiOauthManager: OpenAiOauthManager;
}

interface SessionData {
  userId: string;
  name: string;
  email: string;
  role: 'admin' | 'user' | 'fde';
  createdAt: number;
}

export class BrowserApiServer {
  private sseClients = new Set<http.ServerResponse>();
  // RFQ-scoped subset of sseClients, used ONLY for HITL broadcasts
  // (hitl:request / hitl:clear) -- see sendToRfq() below. Every OTHER event
  // type (task:progress, workspace:changed, etc.) still goes through the
  // generic send()/sseClients above unchanged: those are legitimately
  // per-daemon-instance broadcasts (this daemon is meant to run one
  // instance per user, per the production-readiness decision -- see
  // MULTI_USER_PRODUCTION_READINESS.md's Q2 -- so all of ONE user's own
  // tabs receiving their own task/workspace events is correct, not a bug).
  // HITL is different: the rfqId in a trigger-hitl payload identifies a
  // SPECIFIC RFQ a tab may or may not currently be looking at, even within
  // one user's own multiple tabs -- that's what needs scoping.
  //
  // Registered via /events?rfqId=... at connect time (see that handler
  // below) -- best-effort: reflects whichever rfqId the tab had active when
  // it opened its SSE connection, not necessarily updated live if the user
  // later types a different RFQ ID into the same tab without reloading.
  // App.tsx's own handleGlobalInterceptStream has an ADDITIONAL, always-
  // current-value rfqId check before actually showing/clearing a popup --
  // that client-side check is what's authoritative for correctness; this
  // server-side scoping is a genuine but best-effort defense-in-depth
  // improvement (reduces what's sent over the wire at all), not a perfect
  // live-tracking mechanism -- see that file's own comments for why a
  // fully live-updated subscription isn't implemented here (the SSE
  // connection is deliberately opened once per tab, not reopened per
  // keystroke as the user types an RFQ ID).
  private sseClientsByRfq = new Map<string, Set<http.ServerResponse>>();
  private server: http.Server | null = null;
  /** In-memory session store: sessionToken → user info */
  private sessions = new Map<string, SessionData>();

  /** True when at least one browser tab has an open SSE connection. */
  hasConnectedClients(): boolean {
    return this.sseClients.size > 0;
  }

  private validateSession(req: http.IncomingMessage): boolean {
    if (this.getSession(req)) return true;
    // Developer integration API key — lets external workflows (Dify/FastMCP) call
    // the local API. OPT-IN: only honored when the daemon operator explicitly sets
    // ACCOMPLISH_ENABLE_INTEGRATION_API=1. The daemon already binds to 127.0.0.1
    // only, so reachability is local-host; this flag is the second gate. This path
    // has no real SessionData/role, so it's treated as "authenticated but never
    // admin" — it can never pass requireAdminSession.
    const auth = req.headers['authorization'];
    const bearer = auth?.startsWith('Bearer ') ? auth.slice(7) : undefined;
    if (bearer && process.env.ACCOMPLISH_ENABLE_INTEGRATION_API === '1') {
      const devKey = this.svc.secretsService.getApiKey('__dev_api_key__');
      if (devKey && bearer === devKey) return true;
    }
    return false;
  }

  /** Resolves the caller's session (Authorization header or ?token= query param). */
  private getSession(req: http.IncomingMessage): SessionData | null {
    const auth = req.headers['authorization'];
    const bearer = auth?.startsWith('Bearer ') ? auth.slice(7) : undefined;
    if (bearer) {
      const session = this.sessions.get(bearer);
      if (session) return session;
    }
    // Check query param (for EventSource which can't set headers)
    const qp = new URL(req.url ?? '/', 'http://localhost').searchParams.get('token');
    if (qp) {
      const session = this.sessions.get(qp);
      if (session) return session;
    }
    return null;
  }

  /** Throws if the caller does not have an admin-role session. */
  private requireAdminSession(req: http.IncomingMessage): void {
    const session = this.getSession(req);
    if (!session || session.role !== 'admin') {
      throw new Error('Forbidden: admin role required');
    }
  }

  constructor(private readonly svc: BrowserApiServices) {
    const s = (ch: string, d: unknown) => this.send(ch, d);
    const { taskService, workspaceService } = svc;
    taskService.on('progress', (d) => s('task:progress', d));
    taskService.on('message', (d) => s('task:update:batch', d));
    taskService.on('complete', (d: { taskId: string; result: unknown }) =>
      s('task:update', { taskId: d.taskId, type: 'complete', result: d.result }),
    );
    taskService.on('error', (d: { taskId: string; error?: unknown }) =>
      s('task:update', { taskId: d.taskId, type: 'error', error: d.error }),
    );
    taskService.on('statusChange', (d) => s('task:status-change', d));
    taskService.on('summary', (d) => s('task:summary', d));
    taskService.on('permission', (d) => s('permission:request', d));
    taskService.on('todo:update', (d) => s('todo:update', d));
    taskService.on('auth:error', (d) => s('auth:error', d));
    workspaceService.on('workspace.changed', (d) => s('workspace:changed', d));
    svc.whatsappService.on('qr', (qr: string) => s('integrations:whatsapp:qr', qr));
    svc.whatsappService.on('status', (status: string) => s('integrations:whatsapp:status', status));
    svc.skillsService.on('skills.changed', (d: unknown) => s('skills:changed', d));
    svc.accomplishRuntime.onUsageUpdate((usage) => s('accomplish-ai:usage-updated', usage));
  }

  private send(ch: string, data: unknown): void {
    if (!this.sseClients.size) return;
    const msg = `event: ${ch}\ndata: ${JSON.stringify(data)}\n\n`;
    for (const r of this.sseClients) {
      try {
        r.write(msg);
      } catch {
        this.sseClients.delete(r);
      }
    }
  }

  /**
   * Writes a raw (unnamed 'message' event) SSE frame to only the tabs
   * registered for this specific rfqId -- see sseClientsByRfq's own comment
   * above for why HITL specifically needs this instead of the generic
   * send()/sseClients broadcast. `raw` should be the exact
   * `data: ${JSON.stringify(payload)}\n\n` string, matching the format the
   * existing raw client.write() call sites already use (App.tsx's listener
   * expects unnamed 'message' events for hitl:request/hitl:clear, not a
   * named SSE event -- see emit-skill-progress's own comment nearby for why
   * that one uses send() instead).
   */
  private sendToRfq(rfqId: string, raw: string): void {
    const clients = this.sseClientsByRfq.get(rfqId);
    if (!clients || !clients.size) return;
    for (const r of clients) {
      try {
        r.write(raw);
      } catch {
        clients.delete(r);
        this.sseClients.delete(r);
      }
    }
  }

  // Project Tracking: Customer/Project master data + RFQ creation, layered in
  // front of the existing pipeline (rfq_process_tracking/rfq_file_telemetry
  // are untouched). Idempotent, mirrors reporting_module/final_selection.py's
  // ensure_conflicts_table() pattern -- safe to run on every daemon start.
  private async ensureProjectTrackingSchema(): Promise<void> {
    await fileMetadataPool.query(`
      CREATE TABLE IF NOT EXISTS customers (
        customer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_name VARCHAR NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now()
      )
    `);
    await fileMetadataPool.query(`
      CREATE TABLE IF NOT EXISTS projects (
        project_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID NOT NULL REFERENCES customers(customer_id) ON DELETE RESTRICT,
        project_name VARCHAR NOT NULL,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        UNIQUE (customer_id, project_name)
      )
    `);
    await fileMetadataPool.query(`CREATE INDEX IF NOT EXISTS idx_projects_customer ON projects(customer_id)`);
    await fileMetadataPool.query(`
      CREATE TABLE IF NOT EXISTS rfq_project_tracking (
        id BIGSERIAL PRIMARY KEY,
        rfq_id VARCHAR NOT NULL UNIQUE,
        customer_name VARCHAR NOT NULL,
        project_name VARCHAR NOT NULL,
        customer_id UUID REFERENCES customers(customer_id) ON DELETE SET NULL,
        project_id UUID REFERENCES projects(project_id) ON DELETE SET NULL,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now()
      )
    `);
    await fileMetadataPool.query(`CREATE INDEX IF NOT EXISTS idx_rfq_project_tracking_rfq_id ON rfq_project_tracking(rfq_id)`);
    await fileMetadataPool.query(`CREATE INDEX IF NOT EXISTS idx_rfq_project_tracking_customer_name ON rfq_project_tracking(customer_name)`);
    await fileMetadataPool.query(`CREATE INDEX IF NOT EXISTS idx_rfq_project_tracking_project_name ON rfq_project_tracking(project_name)`);
  }

  // Currency conversion rates + the single "default quote currency" setting,
  // driving both the Settings -> Currencies admin UI and the centum intake
  // Python pipeline's CBOM workbook generation (reporting_module/currency.py
  // reads this same table via db.py::get_logic_connection() -- same logic_db,
  // same pgPool this class already uses). Deliberately on pgPool (logic_db),
  // not fileMetadataPool (file_metadata_db) -- this is global system config
  // (same category as quote_routing_profiles/system_skills_registry, already
  // in logic_db), not RFQ/customer/project tracking data.
  private async ensureCurrencySchema(): Promise<void> {
    await pgPool.query(`
      CREATE TABLE IF NOT EXISTS currency_conversion_rates (
        currency_code VARCHAR(3) PRIMARY KEY,
        currency_name VARCHAR NOT NULL,
        conversion_rate NUMERIC(14,6) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now()
      )
    `);
    // Tables created before currency_name existed are skipped by CREATE TABLE IF NOT EXISTS, so add the
    // column here (nullable: the old rows have none) and name the seeded rows below.
    await pgPool.query(`ALTER TABLE currency_conversion_rates ADD COLUMN IF NOT EXISTS currency_name VARCHAR`);
    await pgPool.query(`
      UPDATE currency_conversion_rates SET currency_name = v.name
      FROM (VALUES ('USD', 'US Dollar'), ('INR', 'Indian Rupee'), ('EUR', 'Euro')) AS v(code, name)
      WHERE currency_conversion_rates.currency_code = v.code AND currency_conversion_rates.currency_name IS NULL
    `);
    await pgPool.query(`
      CREATE TABLE IF NOT EXISTS currency_settings (
        id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        default_quote_currency_code VARCHAR(3) NOT NULL REFERENCES currency_conversion_rates(currency_code),
        updated_at TIMESTAMP DEFAULT now()
      )
    `);
    // Seed with today's existing hardcoded rates so behavior is unchanged
    // until an admin edits something via the new Settings tab.
    await pgPool.query(`
      INSERT INTO currency_conversion_rates (currency_code, currency_name, conversion_rate)
      VALUES ('USD', 'US Dollar', 1.0), ('INR', 'Indian Rupee', 83.5), ('EUR', 'Euro', 0.93)
      ON CONFLICT (currency_code) DO NOTHING
    `);
    const existing = await pgPool.query(`SELECT 1 FROM currency_settings WHERE id = 1`);
    if (existing.rowCount === 0) {
      await pgPool.query(
        `INSERT INTO currency_settings (id, default_quote_currency_code) VALUES (1, 'USD')`,
      );
    }
  }

  // system_skills_registry has 10 rows, but only 8 are ever actually run --
  // skills 9/10 (standardize_erp, enrich_erp) are explicitly labeled "not
  // currently exposed" and aren't part of Standard_BOM_Flow, the one real
  // routing profile this pipeline uses. Naively looking up
  // "skill_index = completedSkills + 1" breaks exactly at that boundary: once
  // completedSkills reaches 8 (pipeline fully done), skill_index 9 still
  // EXISTS in the registry, so the lookup silently returns its macro_category
  // (4, "ERP & QuoteWin Data Sync") instead of recognizing the pipeline is
  // actually complete -- every finished RFQ incorrectly looked like it was
  // sitting at the QuoteWin stage. This derives the true max skill_index from
  // the routing profile itself (not a hardcoded "8"), so it stays correct if
  // the profile's skill list ever changes.
  private async getMaxRealSkillIndex(): Promise<number | null> {
    const profileResult = await pgPool.query(
      `SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = 'Standard_BOM_Flow'`,
    );
    const routingSequence = profileResult.rows[0]?.routing_sequence as string[] | undefined;
    const lastRealToolName = routingSequence?.[routingSequence.length - 1];
    if (!lastRealToolName) { return null; }
    const lastSkillResult = await pgPool.query(
      `SELECT skill_index FROM system_skills_registry WHERE mcp_tool_name = $1`,
      [lastRealToolName],
    );
    return typeof lastSkillResult.rows[0]?.skill_index === 'number' ? lastSkillResult.rows[0].skill_index : null;
  }

  private cors(req: http.IncomingMessage, res: http.ServerResponse): void {
    const reqOrigin = req.headers['origin'] ?? '*';
    res.setHeader('Access-Control-Allow-Origin', reqOrigin);
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.setHeader('Access-Control-Allow-Private-Network', 'true');
    res.setHeader('Vary', 'Origin');
  }

  private async dispatch(
    channel: string,
    args: unknown[],
    req: http.IncomingMessage,
  ): Promise<unknown> {
    const {
      taskService,
      settingsService,
      workspaceService,
      secretsService,
      connectorService,
      schedulerService,
      storage,
    } = this.svc;
    const s = (v: unknown) => v as string;
    const b = (v: unknown) => v as boolean;
    const sm = (v: unknown) => v as string | undefined;
    switch (channel) {
      case 'task:start': {
        const cfg = args[0] as Record<string, unknown>;
        return taskService.startTask({ ...cfg, taskId: createTaskId() } as Parameters<
          typeof taskService.startTask
        >[0]);
      }
      case 'task:list': {
        const ws = workspaceService.getActive();
        return taskService.listTasks(ws?.id, !!ws?.isDefault);
      }
      case 'task:get':
        return storage.getTask(s(args[0])) || null;
      case 'task:cancel':
        return taskService.stopTask({ taskId: s(args[0]) });
      case 'task:interrupt':
        return taskService.interruptTask({ taskId: s(args[0]) });
      case 'task:delete': {
        const id = s(args[0]);
        if (taskService.hasActiveTask(id)) await taskService.stopTask({ taskId: id });
        storage.deleteTask(id);
        return null;
      }
      case 'task:clear-history':
        storage.clearHistory();
        return null;
      case 'task:get-todos':
        return storage.getTodosForTask(s(args[0]));
      case 'session:resume': {
        // Browser sends positional args: [sessionId, prompt, existingTaskId?, attachments?]
        return taskService.resumeSession({
          sessionId: s(args[0]),
          prompt: s(args[1]),
          existingTaskId: sm(args[2]),
          attachments: args[3] as Parameters<typeof taskService.resumeSession>[0]['attachments'],
          workspaceId: workspaceService.getActive()?.id,
        });
      }
      case 'permission:respond': {
        const r = args[0] as Record<string, unknown>;
        const tid = s(r.taskId);
        if (!taskService.hasActiveTask(tid)) throw new Error(`No active task: ${tid}`);
        await taskService.sendResponse(
          tid,
          r as unknown as Parameters<typeof taskService.sendResponse>[1],
        );
        return null;
      }
      case 'workspace:list':
        return workspaceService.list();
      case 'workspace:get-active':
        return workspaceService.getActive()?.id ?? null;
      case 'workspace:switch':
        return workspaceService.setActive(s(args[0]));
      case 'workspace:create':
        return workspaceService.create(args[0] as Parameters<typeof workspaceService.create>[0]);
      case 'workspace:update':
        return workspaceService.update(
          s(args[0]),
          args[1] as Parameters<typeof workspaceService.update>[1],
        );
      case 'workspace:delete':
        return workspaceService.delete(s(args[0])).deleted;
      case 'knowledge-notes:list':
        return workspaceService.listKnowledgeNotes(s(args[0]));
      case 'knowledge-notes:create':
        return workspaceService.createKnowledgeNote(
          args[0] as Parameters<typeof workspaceService.createKnowledgeNote>[0],
        );
      case 'knowledge-notes:update':
        return workspaceService.updateKnowledgeNote(
          s(args[0]),
          s(args[1]),
          args[2] as Parameters<typeof workspaceService.updateKnowledgeNote>[2],
        );
      case 'knowledge-notes:delete':
        workspaceService.deleteKnowledgeNote(s(args[0]), s(args[1]));
        return null;
      case 'settings:theme':
        return settingsService.getAll().app.theme;
      case 'settings:set-theme':
        settingsService.setTheme(s(args[0]) as Parameters<typeof settingsService.setTheme>[0]);
        return null;
      case 'settings:language':
        return settingsService.getAll().app.language;
      case 'settings:set-language':
        settingsService.setLanguage(
          s(args[0]) as Parameters<typeof settingsService.setLanguage>[0],
        );
        return null;
      case 'settings:debug-mode':
        return settingsService.getAll().app.debugMode;
      case 'settings:set-debug-mode':
        settingsService.setDebugMode(b(args[0]));
        return null;
      case 'settings:notifications-enabled':
        return settingsService.getNotificationsEnabled();
      case 'settings:set-notifications-enabled':
        settingsService.setNotificationsEnabled(b(args[0]));
        return null;
      case 'settings:app-settings':
        return settingsService.getAll().app;
      case 'daemon:get-close-behavior':
        return settingsService.getCloseBehavior();
      case 'daemon:set-close-behavior':
        settingsService.setCloseBehavior(
          s(args[0]) as Parameters<typeof settingsService.setCloseBehavior>[0],
        );
        return null;
      case 'settings:api-keys': {
        const keys = await secretsService.getAllApiKeys();
        return Object.entries(keys)
          .filter(([, v]) => v != null)
          .map(([p, k]) => ({
            id: `local-${p}`,
            provider: p,
            label: 'Local API Key',
            keyPrefix: k ? `${k.substring(0, 8)}...` : '',
            isActive: true,
            createdAt: new Date().toISOString(),
          }));
      }
      case 'settings:add-api-key': {
        const p = s(args[0]);
        const k = sanitizeApiKey(s(args[1]));
        secretsService.storeApiKey(p, k);
        return {
          id: `local-${p}`,
          provider: p,
          label: 'Local API Key',
          keyPrefix: `${k.substring(0, 8)}...`,
          isActive: true,
          createdAt: new Date().toISOString(),
        };
      }
      case 'settings:remove-api-key':
        secretsService.deleteApiKey(s(args[0]).replace('local-', ''));
        return null;
      case 'provider-settings:get':
        return settingsService.getProviderSettings();
      case 'provider-settings:set-active':
        settingsService.setActiveProvider(
          args[0] as Parameters<typeof settingsService.setActiveProvider>[0],
        );
        return null;
      case 'provider-settings:get-connected':
        return (
          (settingsService.getProviderSettings().connectedProviders as Record<string, unknown>)[
            s(args[0])
          ] ?? null
        );
      case 'provider-settings:set-connected':
        settingsService.setConnectedProvider(
          args[0] as Parameters<typeof settingsService.setConnectedProvider>[0],
          args[1] as Parameters<typeof settingsService.setConnectedProvider>[1],
        );
        return null;
      case 'provider-settings:remove-connected':
        settingsService.removeConnectedProvider(
          args[0] as Parameters<typeof settingsService.removeConnectedProvider>[0],
        );
        return null;
      case 'provider-settings:update-model':
        settingsService.updateProviderModel(
          args[0] as Parameters<typeof settingsService.updateProviderModel>[0],
          sm(args[1]) ?? null,
        );
        return null;
      case 'provider-settings:set-debug':
        settingsService.setProviderDebugMode(b(args[0]));
        return null;
      case 'provider-settings:get-debug':
        return settingsService.getProviderDebugMode();
      case 'model:get':
        return settingsService.getSelectedModel();
      case 'model:set':
        settingsService.setSelectedModel(
          args[0] as Parameters<typeof settingsService.setSelectedModel>[0],
        );
        return null;
      case 'ollama:get-config':
        return settingsService.getOllamaConfig();
      case 'ollama:set-config':
        settingsService.setOllamaConfig(
          args[0] as Parameters<typeof settingsService.setOllamaConfig>[0],
        );
        return null;
      case 'litellm:get-config':
        return settingsService.getLiteLLMConfig();
      case 'litellm:set-config':
        settingsService.setLiteLLMConfig(
          args[0] as Parameters<typeof settingsService.setLiteLLMConfig>[0],
        );
        return null;
      case 'connectors:list':
        return connectorService.list();
      // OAuth connector flows — return stub values (need Electron shell.openExternal for full flow)
      case 'connectors:get-built-in-auth-status':
        return [];
      case 'connectors:built-in-login':
        return { ok: false, error: 'OAuth requires desktop app' };
      case 'connectors:built-in-logout':
        return null;
      case 'connectors:slack-oauth-status':
        return { connected: false, pendingAuthorization: false };
      case 'connectors:start-oauth':
        return { state: '', authUrl: '' };
      case 'connectors:complete-oauth':
        return null;
      case 'connectors:add': {
        const id = `mcp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
        const now = new Date().toISOString();
        const c = {
          id,
          name: s(args[0]),
          url: s(args[1]),
          status: 'disconnected' as const,
          isEnabled: true,
          createdAt: now,
          updatedAt: now,
        };
        connectorService.upsert(c);
        return c;
      }
      case 'connectors:delete':
        connectorService.deleteTokens(s(args[0]));
        connectorService.delete(s(args[0]));
        return null;
      case 'connectors:set-enabled':
        connectorService.setEnabled(s(args[0]), b(args[1]));
        return null;
      case 'favorites:list':
        return storage.getFavorites();
      case 'favorites:add': {
        const t = storage.getTask(s(args[0]));
        if (!t) throw new Error(`Task not found: ${s(args[0])}`);
        storage.addFavorite(t.id, t.prompt, t.summary);
        return null;
      }
      case 'favorites:remove':
        storage.removeFavorite(s(args[0]));
        return null;
      case 'favorites:has':
        return storage.isFavorite(s(args[0]));
      case 'scheduler:list':
        return schedulerService.listSchedules(sm(args[0]));
      case 'scheduler:create':
        return schedulerService.createSchedule(s(args[0]), s(args[1]), sm(args[2]));
      case 'scheduler:delete':
        schedulerService.deleteSchedule(s(args[0]));
        return null;
      case 'scheduler:set-enabled':
        schedulerService.setEnabled(s(args[0]), b(args[1]));
        return null;
      case 'accomplish-ai:get-status':
        return {
          connected:
            settingsService.getProviderSettings().connectedProviders['accomplish-ai']
              ?.connectionStatus === 'connected',
        };
      case 'daemon:ping':
        return { status: 'ok', uptime: process.uptime() };

      // ── Accomplish AI Free Tier ─────────────────────────────────────────────
      case 'accomplish-ai:connect':
      case 'accomplish-ai:ensure-ready': {
        const storageDeps: StorageDeps = {
          readKey: (key) => this.svc.storage.get(key),
          writeKey: (key, value) => this.svc.storage.set(key, value),
          readGaClientId: () => null,
        };
        return this.svc.accomplishRuntime.connect(storageDeps);
      }
      case 'accomplish-ai:disconnect':
        this.svc.accomplishRuntime.disconnect();
        return null;
      case 'accomplish-ai:get-usage':
        return this.svc.accomplishRuntime.getUsage();

      // ── Skills ──────────────────────────────────────────────────────────────
      case 'skills:list':
        return this.svc.skillsService.list();
      case 'skills:list-enabled':
        return this.svc.skillsService.listEnabled();
      case 'skills:set-enabled':
        this.svc.skillsService.setEnabled(s(args[0]), b(args[1]));
        return null;
      case 'skills:get-content':
        return this.svc.skillsService.getContent(s(args[0]));
      case 'skills:get-user-path':
        return this.svc.skillsService.getUserSkillsPath();
      case 'skills:add-from-github':
        return this.svc.skillsService.addFromPath(s(args[0]));
      case 'skills:delete':
        this.svc.skillsService.delete(s(args[0]));
        return null;
      case 'skills:resync':
        return this.svc.skillsService.resync();

      // ── WhatsApp ────────────────────────────────────────────────────────────
      case 'whatsapp:get-config':
        return this.svc.whatsappService.getConfig();
      case 'whatsapp:connect':
        await this.svc.whatsappService.connect();
        return null;
      case 'whatsapp:disconnect':
        await this.svc.whatsappService.disconnect();
        return null;
      case 'whatsapp:set-enabled':
        this.svc.whatsappService.setEnabled(b(args[0]));
        return null;

      // ── Sandbox config ──────────────────────────────────────────────────────
      case 'sandbox:get-config':
        return settingsService.getSandboxConfig();
      case 'sandbox:set-config':
        settingsService.setSandboxConfig(
          args[0] as Parameters<typeof settingsService.setSandboxConfig>[0],
        );
        return null;

      // Provider connection tests — run in daemon so Node.js SDKs are available
      case 'ollama:test-connection': {
        const { testOllamaConnection } = await import('@accomplish_ai/agent-core');
        return testOllamaConnection(s(args[0]));
      }
      case 'litellm:test-connection': {
        const { testLiteLLMConnection } = await import('@accomplish_ai/agent-core');
        return testLiteLLMConnection(s(args[0]), sm(args[1]));
      }
      case 'lmstudio:test-connection': {
        const { testLMStudioConnection } = await import('@accomplish_ai/agent-core');
        return testLMStudioConnection({ url: s(args[0]) });
      }
      case 'azure-foundry:test-connection': {
        const { testAzureFoundryConnection } = await import('@accomplish_ai/agent-core');
        return testAzureFoundryConnection(
          args[0] as Parameters<typeof testAzureFoundryConnection>[0],
        );
      }
      case 'bedrock:validate-credentials': {
        const { validateBedrockCredentials } = await import('@accomplish_ai/agent-core');
        return validateBedrockCredentials(
          args[0] as Parameters<typeof validateBedrockCredentials>[0],
        );
      }
      case 'bedrock:fetch-models': {
        const { fetchBedrockModels } = await import('@accomplish_ai/agent-core');
        return fetchBedrockModels(args[0] as Parameters<typeof fetchBedrockModels>[0]);
      }
      case 'bedrock:save-credentials': {
        secretsService.storeBedrockCredentials(JSON.stringify(args[0]));
        return null;
      }
      case 'bedrock:get-credentials': {
        return secretsService.getBedrockCredentials();
      }

      // ── Parity wiring (bucket A) — delegate to existing services / agent-core ──
      case 'settings:get-openai-base-url':
        return settingsService.getOpenAiBaseUrl();
      case 'settings:set-openai-base-url':
        settingsService.setOpenAiBaseUrl(
          args[0] as Parameters<typeof settingsService.setOpenAiBaseUrl>[0],
        );
        return null;
      case 'settings:get-cloud-browser':
        return settingsService.getCloudBrowserConfig();
      case 'settings:set-cloud-browser':
        settingsService.setCloudBrowserConfig(
          args[0] as Parameters<typeof settingsService.setCloudBrowserConfig>[0],
        );
        return null;
      case 'azure-foundry:get-config':
        return settingsService.getAzureFoundryConfig();
      case 'azure-foundry:set-config':
        settingsService.setAzureFoundryConfig(
          args[0] as Parameters<typeof settingsService.setAzureFoundryConfig>[0],
        );
        return null;
      case 'lmstudio:get-config':
        return settingsService.getLMStudioConfig();
      case 'lmstudio:set-config':
        settingsService.setLMStudioConfig(
          args[0] as Parameters<typeof settingsService.setLMStudioConfig>[0],
        );
        return null;
      case 'huggingface-local:get-config':
        return settingsService.getHuggingFaceLocalConfig();
      case 'huggingface-local:set-config':
        settingsService.setHuggingFaceLocalConfig(
          args[0] as Parameters<typeof settingsService.setHuggingFaceLocalConfig>[0],
        );
        return null;
      case 'secrets:has-api-key':
        return (await secretsService.getApiKey(s(args[0]))) != null;
      case 'secrets:has-any-api-key':
        return secretsService.hasAnyApiKey();
      case 'secrets:get-all-api-keys':
        return secretsService.getAllApiKeys();
      case 'provider:validate-api-key': {
        const { validateApiKey } = await import('@accomplish_ai/agent-core');
        return validateApiKey(...(args as Parameters<typeof validateApiKey>));
      }
      // The UI's standard provider forms (OpenAI, Anthropic, Zai, OpenRouter, ...)
      // call validateApiKeyForProvider(provider, key, options) and read `.valid`.
      // Normalize the options object, then delegate to agent-core validateApiKey.
      case 'provider:validate-api-key-for-provider': {
        const provider = s(args[0]);
        const key = s(args[1]);
        const raw = (args[2] ?? {}) as Record<string, unknown>;
        const options: Record<string, unknown> = {};
        if (typeof raw.baseUrl === 'string') {
          options.baseUrl = raw.baseUrl;
        }
        const region = raw.zaiRegion ?? raw.region;
        if (typeof region === 'string') {
          options.zaiRegion = region;
        }
        const { validateApiKey } = await import('@accomplish_ai/agent-core');
        return validateApiKey(
          provider as Parameters<typeof validateApiKey>[0],
          key,
          options as Parameters<typeof validateApiKey>[2],
        );
      }
      case 'vertex:validate-credentials': {
        const { validateVertexCredentials } = await import('@accomplish_ai/agent-core');
        return validateVertexCredentials(...(args as Parameters<typeof validateVertexCredentials>));
      }
      case 'vertex:fetch-models': {
        const { fetchVertexModels } = await import('@accomplish_ai/agent-core');
        return fetchVertexModels(...(args as Parameters<typeof fetchVertexModels>));
      }
      // UI calls fetchProviderModels(providerId, { baseUrl?, zaiRegion? }). Mirror the
      // Electron model-discovery handler: resolve the provider's models endpoint,
      // pull the stored key, build any urlOverride, then call the low-level fetcher.
      case 'models:fetch-provider': {
        const providerId = s(args[0]);
        const opts = (args[1] ?? {}) as { baseUrl?: string; zaiRegion?: string };
        const { DEFAULT_PROVIDERS, ZAI_ENDPOINTS, fetchProviderModels } =
          await import('@accomplish_ai/agent-core');
        const providerConfig = DEFAULT_PROVIDERS.find((p) => p.id === providerId);
        if (!providerConfig?.modelsEndpoint) {
          return { success: false, error: 'No models endpoint configured for this provider' };
        }
        const apiKey = secretsService.getApiKey(providerId);
        if (!apiKey) {
          return { success: false, error: 'No API key found for this provider' };
        }
        let urlOverride: string | undefined;
        let endpointConfig = providerConfig.modelsEndpoint;
        if (providerId === 'openai' && typeof opts.baseUrl === 'string' && opts.baseUrl) {
          urlOverride = `${opts.baseUrl.replace(/\/+$/, '')}/models`;
          endpointConfig = { ...endpointConfig, modelFilter: undefined };
        }
        if (providerId === 'zai' && opts.zaiRegion) {
          const region = opts.zaiRegion as keyof typeof ZAI_ENDPOINTS;
          urlOverride = `${ZAI_ENDPOINTS[region]}/models`;
        }
        return fetchProviderModels({ endpointConfig, apiKey, urlOverride, timeout: 10000 });
      }
      case 'models:fetch-openrouter': {
        const { fetchOpenRouterModels } = await import('@accomplish_ai/agent-core');
        const apiKey = secretsService.getApiKey('openrouter');
        return fetchOpenRouterModels(apiKey || '', 10000);
      }
      case 'models:fetch-litellm': {
        const { fetchLiteLLMModels } = await import('@accomplish_ai/agent-core');
        return fetchLiteLLMModels(...(args as Parameters<typeof fetchLiteLLMModels>));
      }
      case 'models:fetch-lmstudio': {
        const { fetchLMStudioModels } = await import('@accomplish_ai/agent-core');
        return fetchLMStudioModels(...(args as Parameters<typeof fetchLMStudioModels>));
      }
      case 'models:fetch-nim': {
        const { fetchNimModels } = await import('@accomplish_ai/agent-core');
        return fetchNimModels(...(args as Parameters<typeof fetchNimModels>));
      }
      case 'nim:test-connection': {
        const { testNimConnection } = await import('@accomplish_ai/agent-core');
        return testNimConnection(...(args as Parameters<typeof testNimConnection>));
      }
      case 'custom:test-connection': {
        const { testCustomConnection } = await import('@accomplish_ai/agent-core');
        return testCustomConnection(...(args as Parameters<typeof testCustomConnection>));
      }

      // ── Batch 2 (bucket B): Vertex credentials — stored in the secret store,
      // mirroring the bedrock helper. credentials arrive as a JSON string.
      case 'vertex:save-credentials': {
        const creds = sanitizeApiKey(s(args[0]));
        secretsService.storeApiKey('vertex', creds);
        return {
          id: 'local-vertex',
          provider: 'vertex',
          label: 'Vertex Credentials',
          keyPrefix: '••••',
          isActive: true,
          createdAt: new Date().toISOString(),
        };
      }
      case 'vertex:get-credentials': {
        const raw = secretsService.getApiKey('vertex');
        if (!raw) {
          return null;
        }
        try {
          return JSON.parse(raw);
        } catch {
          return null;
        }
      }

      // ── Batch 2 (bucket B): Speech (ElevenLabs) — runs in the daemon (HTTP).
      case 'speech:is-configured': {
        const { createSpeechService } = await import('@accomplish_ai/agent-core');
        return createSpeechService({ storage }).isElevenLabsConfigured();
      }
      case 'speech:get-config': {
        const { createSpeechService } = await import('@accomplish_ai/agent-core');
        const key = createSpeechService({ storage }).getElevenLabsApiKey();
        return {
          enabled: key != null,
          hasApiKey: key != null,
          ...(key ? { apiKeyPrefix: `${key.substring(0, 4)}…` } : {}),
        };
      }
      case 'speech:validate': {
        const { createSpeechService } = await import('@accomplish_ai/agent-core');
        return createSpeechService({ storage }).validateElevenLabsApiKey(sm(args[0]));
      }
      case 'speech:transcribe': {
        // audio arrives base64-encoded (ArrayBuffer can't cross the JSON bridge).
        const { createSpeechService } = await import('@accomplish_ai/agent-core');
        const audio = Buffer.from(s(args[0]), 'base64');
        return createSpeechService({ storage }).transcribeAudio(audio, sm(args[1]) ?? 'audio/webm');
      }

      // ── Batch 2 (bucket B): OpenAI "Sign in with ChatGPT" OAuth. The manager
      // (transient opencode runtime) handles the loopback callback + token
      // exchange; login returns the authorize URL for the browser to open, then
      // the UI polls status until connected.
      case 'openai-oauth:status':
        return this.svc.openAiOauthManager.status();
      case 'openai-oauth:login': {
        const { authorizeUrl } = await this.svc.openAiOauthManager.startLogin();
        return { ok: true, openedUrl: authorizeUrl };
      }

      // ── Provenance / authorship — openly queryable so the app can SHOW who
      // built this SRIM/DigiBull build. Attribution, not a tamper trap: removing
      // it loses the credit, it does not break anything.
      case 'system:about': {
        return {
          app: 'CAM 3.4',
          brand: 'DigiBull.ai',
          author: 'Nagabhushana Raju S',
          location: 'Mysore, Karnataka, India',
          build: 'CAM 3.4 (Centum), built on the open-source Accomplish base',
        };
      }

      // ── Developer integration API key. Generating/showing the key is safe;
      // it only grants access when the daemon operator explicitly enables it via
      // ACCOMPLISH_ENABLE_INTEGRATION_API=1 (see validateSession). Off by default.
      case 'dev:get-api-key': {
        let k = secretsService.getApiKey('__dev_api_key__');
        if (!k) {
          k = `srim_${crypto.randomUUID().replace(/-/g, '')}`;
          secretsService.storeApiKey('__dev_api_key__', k);
        }
        return { apiKey: k, enabled: process.env.ACCOMPLISH_ENABLE_INTEGRATION_API === '1' };
      }
      case 'dev:regenerate-api-key': {
        const k = `srim_${crypto.randomUUID().replace(/-/g, '')}`;
        secretsService.storeApiKey('__dev_api_key__', k);
        return { apiKey: k, enabled: process.env.ACCOMPLISH_ENABLE_INTEGRATION_API === '1' };
      }

      // ── LOCAL LLM advisor: real machine specs (CPU/RAM) from Node `os`. The
      // browser adds GPU (WebGL) + network client-side. Used to recommend which
      // local models the machine can realistically run.
      case 'system:get-specs': {
        const os = await import('node:os');
        const cpus = os.cpus();
        return {
          platform: process.platform,
          arch: process.arch,
          cpuModel: cpus[0]?.model?.trim() ?? 'unknown',
          cpuCores: cpus.length,
          totalRamGB: Math.round((os.totalmem() / 1024 ** 3) * 10) / 10,
          freeRamGB: Math.round((os.freemem() / 1024 ** 3) * 10) / 10,
        };
      }
      
  // Location: src/daemon/browser-api-server.ts -> inside dispatch() method switch block

// ─── FETCH REQUISITE ROWS FROM DUCKDB TO POPULATE AG GRID PREVIEW ───
      case 'bom:get-preview-data': {
        const rfqId = args[0] as string;
        if (!rfqId) throw new Error('Missing target RFQ ID context');

        // Fetch straight from your local Python bridge API
        const PYTHON_SERVICE = (process.env.PYTHON_SERVICE_URL ?? 'http://100.121.36.255:3010').replace(/\/$/, '');
        // duck_db_api.py's /api/bom/preview/{rfq_id} now requires
        // Authorization: Bearer <rfq-scoped JWT> -- mint one first via the
        // same POST /auth/token endpoint the web frontend uses (auth.py).
        const tokenResponse = await fetch(`${PYTHON_SERVICE}/auth/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rfq_id: rfqId }),
        });
        if (!tokenResponse.ok) throw new Error('Failed to mint auth token for Python bridge call');
        const { token } = (await tokenResponse.json()) as { token: string };
        const response = await fetch(`${PYTHON_SERVICE}/api/bom/preview/${rfqId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) throw new Error('Python bridge failed to fetch BOM data');
        
        return await response.json(); // Returns clean array directly to AG Grid
      }

// ─── COMMIT HUMAN OVERRIDE STATE & CALLBACK TO ORCHESTRATOR ───
      case 'hitl:submit-decision': {
        const rfqId = args[0] as string;
        const approved = args[1] as boolean;

        if (!rfqId) throw new Error('Missing target RFQ reference frame context');

        // ====================================================================
        // STEP 1: Clear the HITL flag in the real table/pool (file_metadata_db.
        // rfq_process_tracking, via fileMetadataPool — matches rfq.checkExists /
        // rfq.getProcessStage). hitl_required is the actual live column (there is
        // no hitl_cleared column). rfq_process_stage is intentionally left
        // untouched: the Python orchestrator owns stage advancement, not this
        // endpoint.
        // ====================================================================
        await fileMetadataPool.query(
          `UPDATE rfq_process_tracking
           SET hitl_required = false
           WHERE rfq_id = $1`,
          [rfqId]
        );
        log.info(`[HITL State] Set hitl_required=false (approved=${approved}) for RFQ: ${rfqId}`);


        // ====================================================================
        // STEP 2: Clear UI Overlay state via SSE Stream — raw client.write(),
        // not this.send(), because the frontend's ad-hoc HITL listener
        // (App.tsx handleGlobalInterceptStream) only catches unnamed 'message'
        // events and parses payload.event itself, matching the /trigger-hitl
        // route's hitl:request broadcast below. this.send() writes a NAMED SSE
        // event type instead, which that listener never receives.
        //
        // sendToRfq(), not a raw broadcast to every sseClients connection --
        // only tabs registered for THIS rfqId (see sseClientsByRfq's own
        // comment) receive it. App.tsx's handler also independently checks
        // payload.rfqId against its own live current value before acting,
        // so this is defense-in-depth, not the only thing preventing a
        // cross-RFQ clear -- see that file's comment for why both layers
        // exist.
        // ====================================================================
        this.sendToRfq(rfqId, `data: ${JSON.stringify({ event: 'hitl:clear', rfqId })}\n\n`);


        // ====================================================================
        // STEP 3: Signal the HITL router (hitl_router.py :5102) so it can
        // advance the rfq_process_stage and send the Temporal human_decision
        // signal. Route: POST /api/rfq/{rfq_id}/hitl/decision
        // ====================================================================
        const HITL_ROUTER_BASE = (process.env.CAM_HITL_ROUTER_URL ?? 'http://127.0.0.1:5102').replace(/\/$/, '');
        const HITL_DECISION_URL = `${HITL_ROUTER_BASE}/api/rfq/${encodeURIComponent(rfqId)}/hitl/decision`;
        log.info(`[HITL Callback] Signalling hitl_router at: ${HITL_DECISION_URL}`);

        fetch(HITL_DECISION_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approved, stage: 'Intake' })
        }).catch((err) => {
          log.error(`[HITL Callback Fault] hitl_router unreachable: ${err.message}`);
        });

        return { success: true };
      }

      case 'rfq.checkExists': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const rfqId = payload?.rfqId as string | undefined;
        if (!rfqId || rfqId.trim() === '') {
          throw new Error('rfqId is required');
        }
        // Checks both the legacy free-text pipeline table AND the new
        // Project Tracking table, so this one existing live-validation RPC
        // (already wired to the RFQ-ID textbox) covers both uniformly.
        const result = await fileMetadataPool.query(
          `SELECT 1 FROM rfq_process_tracking WHERE rfq_id = $1
           UNION ALL
           SELECT 1 FROM rfq_project_tracking WHERE rfq_id = $1
           LIMIT 1`,
          [rfqId.trim()],
        );
        return { exists: (result.rowCount ?? 0) > 0 };
      }

      // ─── PROJECT TRACKING: Customer/Project master data + RFQ creation ───
      case 'projectTracking.listCustomers': {
        const result = await fileMetadataPool.query(
          `SELECT customer_id, customer_name, created_at, updated_at FROM customers ORDER BY customer_name`,
        );
        return { customers: result.rows };
      }

      case 'projectTracking.createCustomer': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const customerName = (payload?.customerName as string | undefined)?.trim();
        if (!customerName) { throw new Error('customerName is required'); }
        try {
          const result = await fileMetadataPool.query(
            `INSERT INTO customers (customer_name) VALUES ($1) RETURNING customer_id, customer_name, created_at, updated_at`,
            [customerName],
          );
          return { customer: result.rows[0] };
        } catch (e) {
          if ((e as { code?: string }).code === '23505') {
            throw new Error(`A customer named "${customerName}" already exists`);
          }
          throw e;
        }
      }

      case 'projectTracking.updateCustomer': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const customerId = payload?.customerId as string | undefined;
        const customerName = (payload?.customerName as string | undefined)?.trim();
        if (!customerId || !customerName) { throw new Error('customerId and customerName are required'); }
        try {
          const result = await fileMetadataPool.query(
            `UPDATE customers SET customer_name = $1, updated_at = now() WHERE customer_id = $2
             RETURNING customer_id, customer_name, created_at, updated_at`,
            [customerName, customerId],
          );
          if (result.rowCount === 0) { throw new Error('Customer not found'); }
          return { customer: result.rows[0] };
        } catch (e) {
          if ((e as { code?: string }).code === '23505') {
            throw new Error(`A customer named "${customerName}" already exists`);
          }
          throw e;
        }
      }

      case 'projectTracking.deleteCustomer': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const customerId = payload?.customerId as string | undefined;
        if (!customerId) { throw new Error('customerId is required'); }
        const projectCount = await fileMetadataPool.query(
          `SELECT COUNT(*)::int AS count FROM projects WHERE customer_id = $1`,
          [customerId],
        );
        const count = projectCount.rows[0]?.count ?? 0;
        if (count > 0) {
          throw new Error(`Cannot delete this customer -- it still has ${count} project(s). Delete those first.`);
        }
        await fileMetadataPool.query(`DELETE FROM customers WHERE customer_id = $1`, [customerId]);
        return { success: true };
      }

      case 'projectTracking.listProjects': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const customerId = payload?.customerId as string | undefined;
        const result = customerId
          ? await fileMetadataPool.query(
              `SELECT project_id, customer_id, project_name, created_at, updated_at FROM projects
               WHERE customer_id = $1 ORDER BY project_name`,
              [customerId],
            )
          : await fileMetadataPool.query(
              `SELECT project_id, customer_id, project_name, created_at, updated_at FROM projects ORDER BY project_name`,
            );
        return { projects: result.rows };
      }

      case 'projectTracking.createProject': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const customerId = payload?.customerId as string | undefined;
        const projectName = (payload?.projectName as string | undefined)?.trim();
        if (!customerId || !projectName) { throw new Error('customerId and projectName are required'); }
        try {
          const result = await fileMetadataPool.query(
            `INSERT INTO projects (customer_id, project_name) VALUES ($1, $2)
             RETURNING project_id, customer_id, project_name, created_at, updated_at`,
            [customerId, projectName],
          );
          return { project: result.rows[0] };
        } catch (e) {
          if ((e as { code?: string }).code === '23505') {
            throw new Error(`This customer already has a project named "${projectName}"`);
          }
          if ((e as { code?: string }).code === '23503') {
            throw new Error('Selected customer does not exist');
          }
          throw e;
        }
      }

      case 'projectTracking.updateProject': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const projectId = payload?.projectId as string | undefined;
        const projectName = (payload?.projectName as string | undefined)?.trim();
        const customerId = payload?.customerId as string | undefined;
        if (!projectId || !projectName) { throw new Error('projectId and projectName are required'); }
        try {
          const result = customerId
            ? await fileMetadataPool.query(
                `UPDATE projects SET project_name = $1, customer_id = $2, updated_at = now() WHERE project_id = $3
                 RETURNING project_id, customer_id, project_name, created_at, updated_at`,
                [projectName, customerId, projectId],
              )
            : await fileMetadataPool.query(
                `UPDATE projects SET project_name = $1, updated_at = now() WHERE project_id = $2
                 RETURNING project_id, customer_id, project_name, created_at, updated_at`,
                [projectName, projectId],
              );
          if (result.rowCount === 0) { throw new Error('Project not found'); }
          return { project: result.rows[0] };
        } catch (e) {
          if ((e as { code?: string }).code === '23505') {
            throw new Error(`This customer already has a project named "${projectName}"`);
          }
          throw e;
        }
      }

      case 'projectTracking.deleteProject': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const projectId = payload?.projectId as string | undefined;
        if (!projectId) { throw new Error('projectId is required'); }
        const rfqCount = await fileMetadataPool.query(
          `SELECT COUNT(*)::int AS count FROM rfq_project_tracking WHERE project_id = $1`,
          [projectId],
        );
        const count = rfqCount.rows[0]?.count ?? 0;
        if (count > 0) {
          throw new Error(`Cannot delete this project -- it still has ${count} RFQ(s) tracked against it.`);
        }
        await fileMetadataPool.query(`DELETE FROM projects WHERE project_id = $1`, [projectId]);
        return { success: true };
      }

      case 'projectTracking.getNextRfqId': {
        // Smallest unused RFQ-XXXXXX number, not a persistent sequence --
        // a sequence's nextval() is consumed just by opening the Create RFQ
        // form (before the user ever submits), so it kept incrementing and
        // burning numbers on every open, leaving permanent gaps. This is a
        // plain SELECT with no side effect: opening the form repeatedly
        // without submitting shows the same suggested ID every time, and it
        // naturally fills in any existing gap instead of always growing.
        // Legacy free-text IDs (CE-005570, ABC-001, etc.) are never consulted;
        // this is a brand-new numbering scheme starting at RFQ-000001.
        const result = await fileMetadataPool.query(`
          WITH used_ids AS (
            SELECT CAST(SUBSTRING(rfq_id FROM 5) AS INTEGER) AS n
            FROM rfq_process_tracking WHERE rfq_id ~ '^RFQ-[0-9]{6}$'
            UNION
            SELECT CAST(SUBSTRING(rfq_id FROM 5) AS INTEGER) AS n
            FROM rfq_project_tracking WHERE rfq_id ~ '^RFQ-[0-9]{6}$'
          )
          SELECT COALESCE(MIN(candidate), 1) AS n
          FROM generate_series(1, (SELECT COALESCE(MAX(n), 0) FROM used_ids) + 1) AS candidate
          WHERE candidate NOT IN (SELECT n FROM used_ids)
        `);
        const n = Number(result.rows[0].n);
        return { rfqId: `RFQ-${String(n).padStart(6, '0')}` };
      }

      case 'projectTracking.createRfq': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const rfqId = (payload?.rfqId as string | undefined)?.trim();
        const customerId = payload?.customerId as string | undefined;
        const projectId = payload?.projectId as string | undefined;
        if (!rfqId || !customerId || !projectId) {
          throw new Error('rfqId, customerId and projectId are required');
        }
        const existing = await fileMetadataPool.query(
          `SELECT 1 FROM rfq_process_tracking WHERE rfq_id = $1
           UNION ALL
           SELECT 1 FROM rfq_project_tracking WHERE rfq_id = $1
           LIMIT 1`,
          [rfqId],
        );
        if ((existing.rowCount ?? 0) > 0) {
          throw new Error(`RFQ ID "${rfqId}" already exists -- choose a different one`);
        }
        const project = await fileMetadataPool.query(
          `SELECT p.project_name, c.customer_name
           FROM projects p JOIN customers c ON c.customer_id = p.customer_id
           WHERE p.project_id = $1 AND p.customer_id = $2`,
          [projectId, customerId],
        );
        if (project.rowCount === 0) {
          throw new Error('Selected project does not belong to the selected customer');
        }
        const { project_name: projectName, customer_name: customerName } = project.rows[0];
        const result = await fileMetadataPool.query(
          `INSERT INTO rfq_project_tracking (rfq_id, customer_name, project_name, customer_id, project_id)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING rfq_id, customer_name, project_name, customer_id, project_id, created_at`,
          [rfqId, customerName, projectName, customerId, projectId],
        );
        return { rfq: result.rows[0] };
      }

      case 'projectTracking.searchRfqs': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const query = (payload?.query as string | undefined)?.trim() ?? '';
        if (!query) { return { rfqs: [] }; }
        const result = await fileMetadataPool.query(
          `SELECT rfq_id, customer_name, project_name, created_at
           FROM rfq_project_tracking
           WHERE rfq_id ILIKE $1 OR customer_name ILIKE $1 OR project_name ILIKE $1
           ORDER BY created_at DESC LIMIT 50`,
          [`%${query}%`],
        );
        return { rfqs: result.rows };
      }

      case 'rfq.getProcessStage': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const rfqId = payload?.rfqId as string | undefined;
        if (!rfqId || rfqId.trim() === '') {
          throw new Error('rfqId is required');
        }
        const result = await fileMetadataPool.query(
          `SELECT rfq_process_stage FROM rfq_process_tracking WHERE rfq_id = $1 AND is_active LIMIT 1`,
          [rfqId.trim()],
        );
        const completedSkills = result.rows[0]?.rfq_process_stage;
        if (typeof completedSkills !== 'number') {
          return { stage: null };
        }

        // RFQ_Flow requires a mandatory VOLUME file at upload (see
        // RfqIntakeUploadModal.tsx); Standard_BOM_Flow's upload never writes
        // a file_role='VOLUME' row. No profile-per-rfq_id is stored anywhere
        // in Postgres, so this is the least-fragile real signal available to
        // tell the two profiles' rfq_ids apart without new schema.
        const volumeCheck = await fileMetadataPool.query(
          `SELECT 1 FROM rfq_file_telemetry WHERE rfq_id = $1 AND file_role = 'VOLUME' LIMIT 1`,
          [rfqId.trim()],
        );
        if (volumeCheck.rows.length > 0) {
          // RFQ_Flow's skills sit at skill_index 11-16 in system_skills_registry,
          // not 1-onward -- looking up "skill_index = completedSkills + 1" (the
          // Standard_BOM_Flow logic below) would resolve a totally unrelated
          // registry row for every RFQ_Flow rfq_id past its first skill. Index
          // directly into RFQ_Flow's own routing_sequence instead.
          const rfqFlowResult = await pgPool.query(
            `SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = 'RFQ_Flow'`,
          );
          const rfqFlowSequence = rfqFlowResult.rows[0]?.routing_sequence as string[] | undefined;
          if (rfqFlowSequence && rfqFlowSequence.length > 0) {
            const toolIndex = Math.min(completedSkills, rfqFlowSequence.length - 1);
            const toolName = rfqFlowSequence[toolIndex];
            const skillResult = await pgPool.query(
              `SELECT macro_category FROM system_skills_registry WHERE mcp_tool_name = $1`,
              [toolName],
            );
            const macroCategory = skillResult.rows[0]?.macro_category;
            return { stage: typeof macroCategory === 'number' ? macroCategory : null };
          }
        }

        // rfq_process_stage (file_metadata_db) counts COMPLETED skills against
        // system_skills_registry's 1-indexed skill_index -- it is NOT the same
        // number as macro_category, even though both range roughly 0-9 and the
        // frontend's MACRO_CATEGORY_TO_STAGE (App.tsx) expects a macro_category.
        // The skill that just halted (or is next to run) is completedSkills + 1;
        // its macro_category is what actually resolves the right stage/HITL mode.
        // Reusing the raw completedSkills count "worked" for the intake stage by
        // coincidence (skill 1's macro_category is 1) but silently resolved the
        // wrong stage for anything past skill 2.
        const maxRealSkillIndex = await this.getMaxRealSkillIndex();
        let macroCategory: number | null | undefined;

        if (typeof maxRealSkillIndex === 'number' && completedSkills >= maxRealSkillIndex) {
          // Pipeline is fully done (or past the last real skill) -- use the
          // last real skill's macro_category directly instead of looking one
          // ahead, since completedSkills + 1 would land on an unexposed
          // registry entry (standardize_erp/enrich_erp) that never actually runs.
          const lastSkillResult = await pgPool.query(
            `SELECT macro_category FROM system_skills_registry WHERE skill_index = $1`,
            [maxRealSkillIndex],
          );
          macroCategory = lastSkillResult.rows[0]?.macro_category;
        } else {
          const skillResult = await pgPool.query(
            `SELECT macro_category FROM system_skills_registry WHERE skill_index = $1`,
            [completedSkills + 1],
          );
          macroCategory = skillResult.rows[0]?.macro_category;
        }

        if (typeof macroCategory !== 'number') {
          // Past the last registered skill entirely (shouldn't normally
          // happen given the check above, but kept as a final safety net) --
          // fall back to the highest skill's macro_category so the UI still
          // lands somewhere sensible instead of null.
          const lastSkillResult = await pgPool.query(
            `SELECT macro_category FROM system_skills_registry ORDER BY skill_index DESC LIMIT 1`,
          );
          macroCategory = lastSkillResult.rows[0]?.macro_category ?? null;
        }

        return { stage: typeof macroCategory === 'number' ? macroCategory : null };
      }

      // Reconstructs the right panel's progress log from DB alone (no reliance
      // on live SSE history) -- used both when resuming/selecting an RFQ and on
      // a hard page refresh, where any in-memory SSE-appended log is lost but
      // the DB still knows exactly how far this RFQ got. Only ever returns
      // skills that have actually run or are currently running (skill_index <=
      // completedSkills + 1) -- nothing ahead of that, on purpose.
      case 'rfq.getSkillHistory': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const rfqId = payload?.rfqId as string | undefined;
        if (!rfqId || rfqId.trim() === '') { throw new Error('rfqId is required'); }
        const result = await fileMetadataPool.query(
          `SELECT rfq_process_stage FROM rfq_process_tracking WHERE rfq_id = $1 AND is_active LIMIT 1`,
          [rfqId.trim()],
        );
        const completedSkills = result.rows[0]?.rfq_process_stage;
        if (typeof completedSkills !== 'number') { return { history: [] }; }

        // Same RFQ_Flow-vs-Standard_BOM_Flow detection as rfq.getProcessStage
        // above -- without it, this always queried skill_index <= a small
        // number (RFQ_Flow's own completedSkills range), which only ever
        // matches Standard_BOM_Flow's early rows (1, 2, 3...) and NEVER
        // RFQ_Flow's real skills (11-16), so the progress log showed
        // completely wrong skill names/stages for every RFQ_Flow rfq_id.
        const volumeCheckHistory = await fileMetadataPool.query(
          `SELECT 1 FROM rfq_file_telemetry WHERE rfq_id = $1 AND file_role = 'VOLUME' LIMIT 1`,
          [rfqId.trim()],
        );
        if (volumeCheckHistory.rows.length > 0) {
          const rfqFlowResult = await pgPool.query(
            `SELECT routing_sequence FROM quote_routing_profiles WHERE profile_name = 'RFQ_Flow'`,
          );
          const rfqFlowSequence = rfqFlowResult.rows[0]?.routing_sequence as string[] | undefined;
          if (rfqFlowSequence && rfqFlowSequence.length > 0) {
            const upperIdx = Math.min(completedSkills, rfqFlowSequence.length - 1);
            const toolNames = rfqFlowSequence.slice(0, upperIdx + 1);
            const skillsResult = await pgPool.query(
              `SELECT skill_index, skill_name, macro_category, mcp_tool_name
               FROM system_skills_registry
               WHERE mcp_tool_name = ANY($1)
               ORDER BY skill_index`,
              [toolNames],
            );
            const history = skillsResult.rows.map((row) => ({
              skillCode: row.mcp_tool_name as string,
              skillName: row.skill_name as string,
              macroCategory: row.macro_category as number,
              stepStatus: toolNames.indexOf(row.mcp_tool_name as string) < completedSkills ? 'completed' : 'running',
            }));
            return { history };
          }
        }

        // Cap at the last real skill (see getMaxRealSkillIndex) so a fully
        // completed RFQ doesn't grow a fake "running" row for
        // standardize_erp/enrich_erp, which never actually run.
        const maxRealSkillIndex = await this.getMaxRealSkillIndex();
        const upperBound = typeof maxRealSkillIndex === 'number'
          ? Math.min(completedSkills + 1, maxRealSkillIndex)
          : completedSkills + 1;

        const skills = await pgPool.query(
          `SELECT skill_index, skill_name, macro_category, mcp_tool_name
           FROM system_skills_registry
           WHERE skill_index <= $1
           ORDER BY skill_index`,
          [upperBound],
        );
        const history = skills.rows.map((row) => ({
          skillCode: row.mcp_tool_name as string,
          skillName: row.skill_name as string,
          macroCategory: row.macro_category as number,
          stepStatus: (row.skill_index as number) <= completedSkills ? 'completed' : 'running',
        }));
        return { history };
      }

      // Real per-version query, replacing the old fragile BOM/VOLUME
      // array-index pairing (which silently mismatched versions whenever
      // uploads didn't happen in strict pairs). Joins rfq_process_tracking
      // (per-version execution state) with rfq_file_telemetry (per-version
      // file rows, keyed by the real `version` column added by the
      // versioning migration) -- both now share that column.
      case 'rfq.getFileVersions': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const rfqId = payload?.rfqId as string | undefined;
        if (!rfqId || rfqId.trim() === '') { throw new Error('rfqId is required'); }

        const trackingResult = await fileMetadataPool.query(
          `SELECT version, is_active, rfq_process_stage, hitl_required, updated_at
           FROM rfq_process_tracking
           WHERE rfq_id = $1
           ORDER BY version ASC`,
          [rfqId.trim()],
        );

        const filesResult = await fileMetadataPool.query(
          `SELECT file_id, file_path, file_role, version, is_active
           FROM rfq_file_telemetry
           WHERE rfq_id = $1
           ORDER BY version ASC, processed_at ASC`,
          [rfqId.trim()],
        );

        const toName = (p: unknown) => String(p).split(/[/\\]/).pop() ?? String(p);
        const fileFor = (version: number, role: string) =>
          filesResult.rows.find(
            (r: Record<string, unknown>) => r.version === version && r.file_role === role && r.is_active,
          );

        const versions = trackingResult.rows.map((t: Record<string, unknown>) => {
          const version = t.version as number;
          const bom = fileFor(version, 'BOM');
          // file_role is 'QUOTEWIN' at insert time (upload_server.py) -- was
          // previously mismatched here as 'VOLUME', which meant this lookup
          // could never actually find a QuoteWin file at all.
          const quoteWin = fileFor(version, 'QUOTEWIN');
          const costingSheet = fileFor(version, 'COSTING_SHEET');
          return {
            version,
            isActive: t.is_active as boolean,
            processStage: t.rfq_process_stage as number,
            hitlRequired: t.hitl_required as boolean,
            updatedAt: t.updated_at instanceof Date ? (t.updated_at as Date).toISOString() : String(t.updated_at),
            bom: bom ? { id: String(bom.file_id), fileName: toName(bom.file_path) } : null,
            quoteWin: quoteWin ? { id: String(quoteWin.file_id), fileName: toName(quoteWin.file_path) } : null,
            costingSheet: costingSheet ? { id: String(costingSheet.file_id), fileName: toName(costingSheet.file_path) } : null,
          };
        });
        return { versions };
      }

      // Takes {rfqId, version} rather than {rfqId, bomId, volumeId} -- flips
      // is_active on the (rfq_id, version) tracking row (execution state)
      // and mirrors the flip on rfq_file_telemetry. No DuckDB re-ingestion
      // needed: each version's DuckDB rows are permanently written under a
      // distinct key that a later version's ingestion never touches, so
      // "activating" is pure Postgres bookkeeping -- every subsequent read
      // (BOM preview, HITL conflict list, next /tool/execute call) naturally
      // resolves to the newly-active version's data.
      case 'rfq.activateVersion': {
        const payload = args[0] as Record<string, unknown> | undefined;
        const rfqId   = payload?.rfqId   as string | undefined;
        const version = payload?.version as number | undefined;
        if (!rfqId || typeof version !== 'number') {
          throw new Error('rfqId and version are required');
        }
        await fileMetadataPool.query(
          'UPDATE rfq_process_tracking SET is_active = FALSE WHERE rfq_id = $1',
          [rfqId],
        );
        await fileMetadataPool.query(
          'UPDATE rfq_process_tracking SET is_active = TRUE WHERE rfq_id = $1 AND version = $2',
          [rfqId, version],
        );
        await fileMetadataPool.query(
          'UPDATE rfq_file_telemetry SET is_active = FALSE WHERE rfq_id = $1',
          [rfqId],
        );
        await fileMetadataPool.query(
          'UPDATE rfq_file_telemetry SET is_active = TRUE WHERE rfq_id = $1 AND version = $2',
          [rfqId, version],
        );
        return { success: true };
      }

      // Routing-profile skill toggles (Standard_BOM_Flow) -- the 8 real
      // backend skills that gate pipeline execution. Distinct from
      // 'skills:list'/'skills:set-enabled' elsewhere in this file, which
      // serve the unrelated bundled-skills (Accomplish-platform) concept via
      // SkillsService. Always queries live -- no caching -- so a toggle from
      // one browser tab is immediately visible to any other tab that
      // re-opens Settings.
      case 'rfq.getRoutingProfileSkills': {
        const registryResult = await pgPool.query(
          `SELECT skill_index, mcp_tool_name, skill_name, macro_category, macro_category_name
           FROM system_skills_registry
           WHERE is_active = true
           ORDER BY skill_index`,
        );
        // Union of EVERY profile's routing_sequence, not just Standard_BOM_Flow --
        // hardcoding one profile name here meant every RFQ_Flow skill (never a
        // member of Standard_BOM_Flow's sequence) always reported isEnabled=false,
        // which App.tsx's isSkippedByToggle then read as "fully disabled," locking
        // the whole RFQ_Flow half of the sidebar regardless of the real toggle
        // state. Same fix shape as db.py's get_all_live_tool_names().
        const profileResult = await pgPool.query(
          `SELECT DISTINCT tool
           FROM quote_routing_profiles, jsonb_array_elements_text(routing_sequence) AS tool`,
        );
        const enabledSet = new Set(profileResult.rows.map((row) => row.tool as string));
        const skills = registryResult.rows.map((row) => ({
          skillCode: row.mcp_tool_name as string,
          skillName: row.skill_name as string,
          skillIndex: row.skill_index as number,
          macroCategory: row.macro_category as number,
          macroCategoryName: row.macro_category_name as string,
          isEnabled: enabledSet.has(row.mcp_tool_name as string),
        }));
        return { skills };
      }

      case 'rfq.setRoutingProfileSkillEnabled': {
        const payload = args[0] as { skillCode?: string; enabled?: boolean } | undefined;
        const skillCode = payload?.skillCode;
        const enabled = payload?.enabled;
        if (!skillCode || typeof enabled !== 'boolean') {
          throw new Error('skillCode (string) and enabled (boolean) are required');
        }
        const PROFILE_NAME = 'Standard_BOM_Flow';
        // Recomputes the whole array from system_skills_registry's canonical
        // skill_index order every time, instead of a raw jsonb ||/- append --
        // an append-to-end (or removal) on an existing array silently
        // reorders the sequence relative to its intended execution order.
        // Confirmed in production: toggling quote_win/costing_sheet off then
        // back on pushed them past resolve_final_selection (which halts
        // unconditionally for human review), permanently preventing them
        // from ever running again for any RFQ. Recomputing from skill_index
        // every time makes the array's order a pure function of "which
        // skills are enabled", so it can never drift out of canonical order.
        const setOp = enabled ? 'UNION' : 'EXCEPT';
        await pgPool.query(
          `WITH current_set AS (
             SELECT jsonb_array_elements_text(routing_sequence) AS tool_name
             FROM quote_routing_profiles WHERE profile_name = $2
           ),
           new_set AS (
             SELECT tool_name FROM current_set
             ${setOp}
             SELECT $1::text
           ),
           ordered AS (
             SELECT ssr.mcp_tool_name
             FROM system_skills_registry ssr
             JOIN new_set ns ON ns.tool_name = ssr.mcp_tool_name
             WHERE ssr.is_active = true
             ORDER BY ssr.skill_index
           )
           UPDATE quote_routing_profiles
           SET routing_sequence = (SELECT COALESCE(jsonb_agg(mcp_tool_name), '[]'::jsonb) FROM ordered),
               updated_at = NOW()
           WHERE profile_name = $2`,
          [skillCode, PROFILE_NAME],
        );
        return { success: true };
      }

      // ── Admin-only user management ────────────────────────────────────────
      // `users`/`password_resets` live in the `srim` database, reached via
      // pg-auth.ts's getPool() -- NOT pgPool/fileMetadataPool (which point at
      // logic_db/file_metadata_db). Every case here requires an admin session
      // as its first line, and never returns password_hash.
      case 'admin.listUsers': {
        this.requireAdminSession(req);
        const { getPool } = await import('./auth/pg-auth.js');
        const result = await getPool().query<{
          id: number;
          uid: string;
          full_name: string | null;
          email: string;
          role: string;
          is_active: boolean;
          created_at: Date;
        }>(
          `SELECT id, uid, full_name, email, role, is_active, created_at
           FROM users ORDER BY created_at DESC`,
        );
        return {
          users: result.rows.map((r) => ({
            id: String(r.id),
            uid: r.uid,
            fullName: r.full_name ?? '',
            email: r.email,
            role: r.role === 'admin' ? 'admin' : r.role === 'fde' ? 'fde' : 'user',
            isActive: r.is_active,
            createdAt: r.created_at instanceof Date ? r.created_at.toISOString() : String(r.created_at),
          })),
        };
      }

      case 'admin.createUser': {
        this.requireAdminSession(req);
        const payload = args[0] as
          | { uid?: string; fullName?: string; email?: string; password?: string; role?: string }
          | undefined;
        const uid = payload?.uid?.trim();
        const fullName = payload?.fullName?.trim();
        const email = payload?.email?.trim().toLowerCase();
        const password = payload?.password;
        const role = payload?.role;
        if (!uid || !fullName || !email || !password) {
          throw new Error('uid, fullName, email and password are required');
        }
        if (role !== 'admin' && role !== 'user' && role !== 'fde') {
          throw new Error("role must be 'admin', 'user', or 'fde'");
        }
        const { createUserAsAdmin } = await import('./auth/pg-auth.js');
        const user = await createUserAsAdmin(uid, fullName, email, password, role);
        return {
          user: {
            id: user.id,
            uid,
            fullName,
            email: user.email,
            role: user.role,
            isActive: true,
            createdAt: new Date().toISOString(),
          },
        };
      }

      case 'admin.updateUser': {
        this.requireAdminSession(req);
        const payload = args[0] as
          | {
              userId?: string;
              fullName?: string;
              email?: string;
              role?: string;
              isActive?: boolean;
            }
          | undefined;
        const userId = payload?.userId;
        if (!userId) { throw new Error('userId is required'); }
        if (payload?.role !== undefined && payload.role !== 'admin' && payload.role !== 'user' && payload.role !== 'fde') {
          throw new Error("role must be 'admin', 'user', or 'fde'");
        }
        const { getPool } = await import('./auth/pg-auth.js');
        const pool = getPool();

        const isDemotingOrDeactivatingAdmin =
          (payload?.role === 'user' || payload?.isActive === false);
        if (isDemotingOrDeactivatingAdmin) {
          const session = this.getSession(req)!;
          if (String(session.userId) === String(userId)) {
            throw new Error('You cannot deactivate or demote your own account');
          }
          const targetResult = await pool.query<{ role: string; is_active: boolean }>(
            'SELECT role, is_active FROM users WHERE id = $1',
            [userId],
          );
          const target = targetResult.rows[0];
          if (target?.role === 'admin' && target.is_active) {
            const adminCountResult = await pool.query<{ count: string }>(
              "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = true",
            );
            if (Number(adminCountResult.rows[0]?.count ?? '0') <= 1) {
              throw new Error('Cannot remove the last active admin');
            }
          }
        }

        const sets: string[] = [];
        const values: unknown[] = [];
        let i = 1;
        if (payload?.fullName !== undefined) { sets.push(`full_name = $${i++}`); values.push(payload.fullName); }
        if (payload?.email !== undefined) { sets.push(`email = $${i++}`); values.push(payload.email.toLowerCase()); }
        if (payload?.role !== undefined) { sets.push(`role = $${i++}`); values.push(payload.role); }
        if (payload?.isActive !== undefined) { sets.push(`is_active = $${i++}`); values.push(payload.isActive); }
        if (sets.length === 0) { throw new Error('No fields to update'); }
        sets.push('updated_at = NOW()');
        values.push(userId);

        const result = await pool.query<{
          id: number;
          uid: string;
          full_name: string | null;
          email: string;
          role: string;
          is_active: boolean;
          created_at: Date;
        }>(
          `UPDATE users SET ${sets.join(', ')} WHERE id = $${i}
           RETURNING id, uid, full_name, email, role, is_active, created_at`,
          values,
        );
        const row = result.rows[0];
        if (!row) { throw new Error('User not found'); }
        return {
          user: {
            id: String(row.id),
            uid: row.uid,
            fullName: row.full_name ?? '',
            email: row.email,
            role: row.role === 'admin' ? 'admin' : row.role === 'fde' ? 'fde' : 'user',
            isActive: row.is_active,
            createdAt: row.created_at instanceof Date ? row.created_at.toISOString() : String(row.created_at),
          },
        };
      }

      case 'admin.resetUserPassword': {
        this.requireAdminSession(req);
        const payload = args[0] as { userId?: string; newPassword?: string } | undefined;
        const userId = payload?.userId;
        const newPassword = payload?.newPassword;
        if (!userId || !newPassword) { throw new Error('userId and newPassword are required'); }
        if (newPassword.length < 6) { throw new Error('Password must be at least 6 characters'); }
        const bcrypt = (await import('bcryptjs')).default;
        const { getPool } = await import('./auth/pg-auth.js');
        const hash = await bcrypt.hash(newPassword, 10);
        const result = await getPool().query(
          'UPDATE users SET password_hash = $1, updated_at = NOW() WHERE id = $2 RETURNING id',
          [hash, userId],
        );
        if (result.rowCount === 0) { throw new Error('User not found'); }
        return { success: true };
      }

      case 'admin.deleteUser': {
        this.requireAdminSession(req);
        const payload = args[0] as { userId?: string } | undefined;
        const userId = payload?.userId;
        if (!userId) { throw new Error('userId is required'); }
        const { getPool } = await import('./auth/pg-auth.js');
        const pool = getPool();

        const session = this.getSession(req)!;
        if (String(session.userId) === String(userId)) {
          throw new Error('You cannot delete your own account');
        }
        const targetResult = await pool.query<{ role: string; is_active: boolean }>(
          'SELECT role, is_active FROM users WHERE id = $1',
          [userId],
        );
        const target = targetResult.rows[0];
        if (target?.role === 'admin' && target.is_active) {
          const adminCountResult = await pool.query<{ count: string }>(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = true",
          );
          if (Number(adminCountResult.rows[0]?.count ?? '0') <= 1) {
            throw new Error('Cannot delete the last active admin');
          }
        }

        const result = await pool.query('DELETE FROM users WHERE id = $1 RETURNING id', [userId]);
        if (result.rowCount === 0) { throw new Error('User not found'); }
        return { success: true };
      }

      // ── Currency conversion rates + default quote currency (Settings ->
      // Currencies tab) -- drives both this UI and centum intake's CBOM
      // workbook generation (reporting_module/currency.py reads the same
      // logic_db.currency_conversion_rates/currency_settings tables). See
      // ensureCurrencySchema() above for the schema.
      case 'currency.listCurrencies': {
        this.requireAdminSession(req);
        const result = await pgPool.query<{
          currency_code: string;
          currency_name: string;
          conversion_rate: string;
          is_active: boolean;
          created_at: Date;
          updated_at: Date;
        }>(
          `SELECT currency_code, currency_name, conversion_rate, is_active, created_at, updated_at
           FROM currency_conversion_rates ORDER BY currency_code`,
        );
        return {
          currencies: result.rows.map((r) => ({
            currencyCode: r.currency_code,
            currencyName: r.currency_name,
            conversionRate: Number(r.conversion_rate),
            isActive: r.is_active,
            createdAt: r.created_at instanceof Date ? r.created_at.toISOString() : String(r.created_at),
            updatedAt: r.updated_at instanceof Date ? r.updated_at.toISOString() : String(r.updated_at),
          })),
        };
      }

      case 'currency.createCurrency': {
        this.requireAdminSession(req);
        const payload = args[0] as
          | { currencyCode?: string; currencyName?: string; conversionRate?: number }
          | undefined;
        const currencyCode = payload?.currencyCode?.trim().toUpperCase();
        const currencyName = payload?.currencyName?.trim();
        const conversionRate = payload?.conversionRate;
        if (!currencyCode || !currencyName || conversionRate === undefined) {
          throw new Error('currencyCode, currencyName and conversionRate are required');
        }
        if (!/^[A-Z]{3}$/.test(currencyCode)) {
          throw new Error('currencyCode must be exactly 3 letters (ISO 4217, e.g. USD)');
        }
        if (!(conversionRate > 0)) {
          throw new Error('conversionRate must be a positive number');
        }
        try {
          const result = await pgPool.query<{
            currency_code: string;
            currency_name: string;
            conversion_rate: string;
            is_active: boolean;
            created_at: Date;
            updated_at: Date;
          }>(
            `INSERT INTO currency_conversion_rates (currency_code, currency_name, conversion_rate)
             VALUES ($1, $2, $3)
             RETURNING currency_code, currency_name, conversion_rate, is_active, created_at, updated_at`,
            [currencyCode, currencyName, conversionRate],
          );
          const row = result.rows[0];
          return {
            currency: {
              currencyCode: row.currency_code,
              currencyName: row.currency_name,
              conversionRate: Number(row.conversion_rate),
              isActive: row.is_active,
              createdAt: row.created_at.toISOString(),
              updatedAt: row.updated_at.toISOString(),
            },
          };
        } catch (e) {
          if ((e as { code?: string }).code === '23505') {
            throw new Error(`Currency code "${currencyCode}" already exists`);
          }
          throw e;
        }
      }

      case 'currency.updateCurrency': {
        this.requireAdminSession(req);
        const payload = args[0] as
          | { currencyCode?: string; currencyName?: string; conversionRate?: number; isActive?: boolean }
          | undefined;
        const currencyCode = payload?.currencyCode?.trim().toUpperCase();
        if (!currencyCode) { throw new Error('currencyCode is required'); }
        if (payload?.conversionRate !== undefined && !(payload.conversionRate > 0)) {
          throw new Error('conversionRate must be a positive number');
        }

        const sets: string[] = [];
        const values: unknown[] = [];
        let i = 1;
        if (payload?.currencyName !== undefined) { sets.push(`currency_name = $${i++}`); values.push(payload.currencyName); }
        if (payload?.conversionRate !== undefined) { sets.push(`conversion_rate = $${i++}`); values.push(payload.conversionRate); }
        if (payload?.isActive !== undefined) { sets.push(`is_active = $${i++}`); values.push(payload.isActive); }
        if (sets.length === 0) { throw new Error('No fields to update'); }
        sets.push('updated_at = NOW()');
        values.push(currencyCode);

        const result = await pgPool.query<{
          currency_code: string;
          currency_name: string;
          conversion_rate: string;
          is_active: boolean;
          created_at: Date;
          updated_at: Date;
        }>(
          `UPDATE currency_conversion_rates SET ${sets.join(', ')} WHERE currency_code = $${i}
           RETURNING currency_code, currency_name, conversion_rate, is_active, created_at, updated_at`,
          values,
        );
        const row = result.rows[0];
        if (!row) { throw new Error('Currency not found'); }
        return {
          currency: {
            currencyCode: row.currency_code,
            currencyName: row.currency_name,
            conversionRate: Number(row.conversion_rate),
            isActive: row.is_active,
            createdAt: row.created_at.toISOString(),
            updatedAt: row.updated_at.toISOString(),
          },
        };
      }

      case 'currency.deleteCurrency': {
        this.requireAdminSession(req);
        const payload = args[0] as { currencyCode?: string } | undefined;
        const currencyCode = payload?.currencyCode?.trim().toUpperCase();
        if (!currencyCode) { throw new Error('currencyCode is required'); }

        const defaultResult = await pgPool.query<{ default_quote_currency_code: string }>(
          `SELECT default_quote_currency_code FROM currency_settings WHERE id = 1`,
        );
        if (defaultResult.rows[0]?.default_quote_currency_code === currencyCode) {
          throw new Error(
            `"${currencyCode}" is the current default quote currency -- set a different default before deleting it`,
          );
        }

        const result = await pgPool.query(
          `DELETE FROM currency_conversion_rates WHERE currency_code = $1`,
          [currencyCode],
        );
        if (result.rowCount === 0) { throw new Error('Currency not found'); }
        return { success: true };
      }

      // Read-only -- unlike the CUD cases above, any authenticated session needs
      // this (it affects what currency they see throughout the app), not just admins.
      case 'currency.getDefaultQuoteCurrency': {
        const result = await pgPool.query<{ default_quote_currency_code: string }>(
          `SELECT default_quote_currency_code FROM currency_settings WHERE id = 1`,
        );
        return { currencyCode: result.rows[0]?.default_quote_currency_code ?? 'USD' };
      }

      case 'currency.setDefaultQuoteCurrency': {
        this.requireAdminSession(req);
        const payload = args[0] as { currencyCode?: string } | undefined;
        const currencyCode = payload?.currencyCode?.trim().toUpperCase();
        if (!currencyCode) { throw new Error('currencyCode is required'); }

        const exists = await pgPool.query(
          `SELECT 1 FROM currency_conversion_rates WHERE currency_code = $1 AND is_active = true`,
          [currencyCode],
        );
        if (exists.rowCount === 0) {
          throw new Error(`"${currencyCode}" is not a known, active currency`);
        }

        await pgPool.query(
          `UPDATE currency_settings SET default_quote_currency_code = $1, updated_at = NOW() WHERE id = 1`,
          [currencyCode],
        );
        return { success: true };
      }

      // ── Embedded Superset dashboard (stage 9, Reports & Analytics) ────────
      // No admin gate -- this is a regular reporting view any authenticated session
      // may open, not an account-management action. Superset admin credentials never
      // leave the daemon; see superset-client.ts.
      case 'superset.getGuestToken': {
        const payload = args[0] as { dashboardUuid?: string; rfqId?: string } | undefined;
        const dashboardUuid = payload?.dashboardUuid ?? '427cde1b-b788-4ff8-b247-1aa3345ec1f0';
        const { getSupersetGuestToken, getSupersetDomain } = await import('./superset-client.js');
        const guestToken = await getSupersetGuestToken(dashboardUuid, payload?.rfqId);
        // getSupersetDomain() is a fixed value (SUPERSET_URL, loopback-safe for
        // the daemon's OWN server-side calls to Superset) -- but supersetDomain
        // here is handed to the BROWSER for its iframe src, so it must reflect
        // whatever host the browser actually used to reach the daemon (LAN IP,
        // NetBird IP, ...), not a fixed loopback/LAN value unreachable from
        // wherever the client actually is. Mirrors endpoints.ts's own
        // window.location.hostname-based resolution on the frontend side.
        // Superset itself listens on 0.0.0.0:8088 (see manage_backend.py), so
        // it's reachable on every interface the daemon is.
        const requestHost = req.headers.host?.split(':')[0];
        const supersetDomain = requestHost ? `http://${requestHost}:8088` : getSupersetDomain();
        return { guestToken, supersetDomain };
      }

    default:
        throw new Error(`Unknown channel: ${channel}`);

  }
}

  async start(): Promise<void> {
    await this.ensureProjectTrackingSchema();
    await this.ensureCurrencySchema();
    return new Promise((resolve, reject) => {
      this.server = http.createServer((req, res) => {
        const { method, url } = req;
        if (method === 'OPTIONS') {
          this.cors(req, res);
          res.writeHead(204);
          res.end();
          return;
        }
        this.cors(req, res);
        if (method === 'GET' && url === '/health') {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end('{"ok":true}');
          return;
        }

        // ── Auth endpoints (no session required) ──────────────────────────────
        if (method === 'POST' && url === '/auth/login') {
          let body = '';
          req.on('data', (c: Buffer) => {
            body += c;
          });
          req.on('end', () => {
            void (async () => {
              try {
                const {
                  token: pat,
                  username,
                  email,
                  password,
                } = JSON.parse(body) as {
                  token?: string;
                  username?: string;
                  email?: string;
                  password?: string;
                };
                // DEV/TESTING bypass: accept the configured test token or
                // username/password without contacting NetBird. No-op in
                // production builds (see test-login.ts).
                const testUser = matchTestLogin({ token: pat, username, password });
                if (testUser) {
                  const sessionToken = crypto.randomUUID();
                  // The dev bypass has no real role concept of its own -- hardcode
                  // admin so local dev/testing can still exercise admin-only UI.
                  this.sessions.set(sessionToken, {
                    userId: testUser.id,
                    name: testUser.name,
                    email: testUser.email,
                    role: 'admin',
                    createdAt: Date.now(),
                  });
                  log.info(`[Auth] Test login: ${testUser.email}`);
                  res.writeHead(200, { 'Content-Type': 'application/json' });
                  res.end(
                    JSON.stringify({
                      sessionToken,
                      user: { name: testUser.name, email: testUser.email, role: 'admin' },
                    }),
                  );
                  return;
                }
                // PostgreSQL auth: username/email + password (no PAT)
                if ((username || email) && password && !pat) {
                  const identifier = username ?? email ?? '';
                  const { pgLogin } = await import('./auth/pg-auth.js');
                  try {
                    const pgUser = await pgLogin(identifier, password);
                    if (pgUser) {
                      const sessionToken = crypto.randomUUID();
                      this.sessions.set(sessionToken, {
                        userId: pgUser.id,
                        name: pgUser.name,
                        email: pgUser.email,
                        role: pgUser.role,
                        createdAt: Date.now(),
                      });
                      log.info(`[Auth] PostgreSQL login: ${pgUser.email}`);
                      res.writeHead(200, { 'Content-Type': 'application/json' });
                      res.end(
                        JSON.stringify({
                          sessionToken,
                          user: { name: pgUser.name, email: pgUser.email, role: pgUser.role },
                        }),
                      );
                      return;
                    }
                    res.writeHead(401, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: 'Invalid credentials' }));
                    return;
                  } catch (authErr) {
                    const msg = authErr instanceof Error ? authErr.message : 'Login failed';
                    const isInactive = /inactive|disabled/i.test(msg);
                    res.writeHead(isInactive ? 403 : 401, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: msg }));
                    return;
                  }
                }
                if (!pat) {
                  res.writeHead(400, { 'Content-Type': 'application/json' });
                  res.end(JSON.stringify({ error: 'Token required' }));
                  return;
                }
                // Validate PAT against NetBird API — /api/users returns the list of
                // users the token has access to; the calling user appears first.
                const nbRes = await fetch(`${NETBIRD_API_BASE}/api/users`, {
                  headers: { Authorization: `Bearer ${pat}` },
                });
                if (!nbRes.ok) {
                  const errText = await nbRes.text().catch(() => '');
                  log.warn(`[Auth] NetBird API rejected token: HTTP ${nbRes.status} — ${errText}`);
                  res.writeHead(401, { 'Content-Type': 'application/json' });
                  res.end(
                    JSON.stringify({ error: `Invalid NetBird token (HTTP ${nbRes.status})` }),
                  );
                  return;
                }
                const users = (await nbRes.json()) as Array<{
                  id: string;
                  name: string;
                  email: string;
                }>;
                const user = users.find((u) => u.email) ?? users[0];
                if (!user) {
                  res.writeHead(401, { 'Content-Type': 'application/json' });
                  res.end(JSON.stringify({ error: 'Could not identify user from token' }));
                  return;
                }
                const sessionToken = crypto.randomUUID();
                // NetBird is a separate legacy identity path with no concept of this
                // app's admin/user roles -- never implicitly grant admin here.
                this.sessions.set(sessionToken, {
                  userId: user.id,
                  name: user.name ?? 'NetBird User',
                  email: user.email ?? '',
                  role: 'user',
                  createdAt: Date.now(),
                });
                log.info(`[Auth] User logged in: ${user.email}`);
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(
                  JSON.stringify({
                    sessionToken,
                    user: { name: user.name, email: user.email, role: 'user' },
                  }),
                );
              } catch (e) {
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: e instanceof Error ? e.message : 'Login failed' }));
              }
            })();
          });
          return;
        }

        if (method === 'POST' && url === '/auth/logout') {
          const auth = req.headers['authorization'];
          if (auth?.startsWith('Bearer ')) this.sessions.delete(auth.slice(7));
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end('{"ok":true}');
          return;
        }

        if (method === 'POST' && url === '/api/internal/trigger-hitl') {
          let body = '';
          req.on('data', (chunk: Buffer) => { body += chunk; });
          req.on('end', () => {
            void (async () => {
              try {
                const parsed = JSON.parse(body) as {
                  rfqId: string;
                  stage: string;
                  hitlType: 'preview' | 'approval';
                };

                if (!parsed.rfqId || !parsed.stage || !parsed.hitlType) {
                  res.writeHead(400, { 'Content-Type': 'application/json' });
                  res.end(JSON.stringify({ error: 'Missing rfqId, stage, or hitlType' }));
                  return;
                }

                log.info(`[HITL Webhook] Orchestrator halted for RFQ: ${parsed.rfqId}. Broadcasting lightweight review-needed signal...`);

                // Deliberately NOT fetching row data here (previously called a
                // Python DuckDB bridge and broadcast every row via SSE in one
                // shot) -- an RFQ's pending conflicts/BOM rows can number in the
                // thousands, and bundling them all into one SSE frame is the
                // same "everything in one payload" problem the review-data
                // pipeline (hitl_router.py, port 5002) was redesigned to avoid
                // at the MCP/FastAPI layer. This broadcast is now just a
                // "review needed" signal -- the frontend fetches the actual
                // conflict/preview rows itself via hitl_router.py's paginated
                // endpoints (GET /api/rfq/{rfqId}/final-selection/pending,
                // cursor-based) once it receives this event.
                const ssePayload = {
                  event: 'hitl:request',
                  rfqId: parsed.rfqId,
                  stage: parsed.stage,
                  type: parsed.hitlType,
                };

                // sendToRfq(), NOT a broadcast to every sseClients connection.
                // THIS was the root cause of "User 1's HITL popup appears for
                // all users": this used to iterate this.sseClients directly
                // (every connected browser tab, any user, any RFQ) with no
                // rfqId filtering at all. Only tabs registered for THIS
                // specific rfqId (via /events?rfqId=..., see that handler's
                // own comment) now receive it. App.tsx's handler also
                // independently re-checks payload.rfqId against its own live
                // current value before showing anything -- see that file's
                // comment for why both layers exist (this one is best-effort/
                // connect-time-scoped; that one is always-correct).
                this.sendToRfq(parsed.rfqId, `data: ${JSON.stringify(ssePayload)}\n\n`);

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ success: true }));
              } catch (e) {
                log.error(`[HITL Webhook Error] Process failed: ${e instanceof Error ? e.message : String(e)}`);
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({
                  error: 'Failed to process hitl pipeline sequence',
                  details: e instanceof Error ? e.message : String(e)
                }));
              }
            })();
          });
          return;
        }

        // Internal webhook — the Python execution engine calls this once per skill
        // step so the daemon can broadcast live progress to connected browser tabs.
        // Not session-authenticated, same posture as /api/internal/trigger-hitl above
        // (protected by network placement, not app-level auth).
        if (method === 'POST' && url === '/api/internal/emit-skill-progress') {
          let body = '';
          req.on('data', (chunk: Buffer) => { body += chunk; });
          req.on('end', () => {
            try {
              const parsed = JSON.parse(body) as {
                rfqId?: string;
                skillCode?: string;
                skillName?: string;
                macroCategory?: number;
                macroCategoryName?: string;
                stepStatus?: string;
                updatedAt?: string;
              };
              if (!parsed.rfqId || !parsed.skillCode || typeof parsed.macroCategory !== 'number') {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: 'rfqId, skillCode, and macroCategory (number) are required' }));
                return;
              }
              // sendToRfq (raw/unnamed frame), NOT accomplish-backend.ts's
              // named-channel EventSource -- that connection is a separate,
              // module-level singleton that never carries ?rfqId= and is
              // therefore never in sseClientsByRfq, so a NAMED delivery
              // targeted at this rfqId's bucket would silently reach nobody
              // (confirmed: this was the actual regression that broke the
              // right pane's live Workflow Status updates). App.tsx's OWN
              // SSE connection (reopened with the live rfqId whenever the
              // user switches RFQs -- see its activeRfqId effect dependency)
              // IS correctly registered in sseClientsByRfq, and already
              // listens for exactly this raw-frame + payload.event convention
              // for hitl:request/hitl:clear -- reusing that here, with
              // payload.event: 'rfq:skill-progress', keeps this on the one
              // connection that's actually RFQ-scoped end-to-end.
              this.sendToRfq(parsed.rfqId, `data: ${JSON.stringify({ event: 'rfq:skill-progress', ...parsed })}\n\n`);
              res.writeHead(200, { 'Content-Type': 'application/json' });
              res.end('{"ok":true}');
            } catch (err) {
              res.writeHead(400, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ error: err instanceof Error ? err.message : 'bad request' }));
            }
          });
          return;
        }

        // Match on pathname, not the full url string — authenticated EventSource
        // connections include a `?token=...` query string, which never strictly
        // equals '/events' and was silently 404ing every authenticated SSE client.
        if (method === 'GET' && new URL(url ?? '/', 'http://localhost').pathname === '/events') {
          res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          });
          res.write(':ok\n\n');
          this.sseClients.add(res);
          // Best-effort RFQ scoping for sendToRfq()'s HITL broadcasts -- see
          // sseClientsByRfq's own comment above for what this does and does
          // NOT guarantee (reflects the tab's rfqId at connect time only).
          // Absent/empty rfqId is valid (a tab not currently viewing any
          // specific RFQ) -- it simply won't be registered for any
          // RFQ-scoped broadcast, which is correct: it has nothing to show
          // a HITL popup for.
          const rfqId = new URL(url ?? '/', 'http://localhost').searchParams.get('rfqId')?.trim();
          if (rfqId) {
            let bucket = this.sseClientsByRfq.get(rfqId);
            if (!bucket) {
              bucket = new Set<http.ServerResponse>();
              this.sseClientsByRfq.set(rfqId, bucket);
            }
            bucket.add(res);
          }
          req.on('close', () => {
            this.sseClients.delete(res);
            if (rfqId) {
              const bucket = this.sseClientsByRfq.get(rfqId);
              if (bucket) {
                bucket.delete(res);
                if (bucket.size === 0) this.sseClientsByRfq.delete(rfqId);
              }
            }
          });
          return;
        }

        // ── Protected routes — require valid session ──────────────────────────
        if (!this.validateSession(req)) {
          res.writeHead(401, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Unauthorized — please log in' }));
          return;
        }
        if (method === 'POST' && url === '/rpc') {
          let body = '';
          req.on('data', (c: Buffer) => {
            body += c;
          });
          req.on('end', () => {
            void (async () => {
              try {
                const { channel, args = [] } = JSON.parse(body) as {
                  channel: string;
                  args?: unknown[];
                };
                const result = await this.dispatch(channel, args, req);
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ result: result ?? null }));
              } catch (e) {
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: e instanceof Error ? e.message : String(e) }));
              }
            })();
          });
          return;
        }
        // GET /api/chat/providers: what the assistant's Local / OpenRouter switch can offer (is a key saved, which models). Never the key.
        if (method === 'GET' && (url ?? '').split('?')[0] === '/api/chat/providers') {
          if (!this.getSession(req)) {
            res.writeHead(401, { 'Content-Type': 'application/json' });
            res.end('{"error":"Not signed in"}');
            return;
          }
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(describeChatProviders({ settingsKey: this.svc.secretsService.getApiKey('openrouter'), selected: this.svc.settingsService.getSelectedModel() })));
          return;
        }
        // ── CAM 3.4: RFQ assistant chat (SPEC-019) ───────────────────────────
        // POST /api/chat is the conversation: { messages, scope?, fileRefs? } -> { message, citations, model, rfq_id, scope?, ui? }.
        // POST /api/rfq/:id/chat is the same route with the RFQ in the URL (alias for the earlier per-RFQ pane).
        // POST /api/chat/actions/confirm runs or cancels a confirmation card issued by the chat (single-use token, same session).
        // Answers come from the guide or from rows and are verified (rfq-chat/*); the only write is a confirmed card.
        const chatMatch = method === 'POST' && (url ?? '').match(/^\/api\/(?:rfq\/([^/?]+)\/)?chat$/);
        const confirmMatch = method === 'POST' && (url ?? '').split('?')[0] === '/api/chat/actions/confirm';
        // A bad percent-escape (".../api/rfq/%/chat") throws URIError here, outside any try: keep the raw text instead,
        // so it just fails the RFQ lookup like any unknown id.
        let rfqInUrl: string | null = null;
        if (chatMatch && chatMatch[1]) {
          try {
            rfqInUrl = decodeURIComponent(chatMatch[1]);
          } catch {
            rfqInUrl = chatMatch[1];
          }
        }
        if (chatMatch || confirmMatch) {
          let body = '';
          req.on('data', (c: Buffer) => { body += c; });
          req.on('end', () => {
            void (async () => {
              const stop = new AbortController();
              res.on('close', () => { if (!res.writableEnded) stop.abort(); }); // the user pressed Stop or left
              try {
                const session = this.getSession(req);
                let provider: ChatProviderMode | undefined;
                try {
                  provider = parseProviderMode((JSON.parse(body) as { provider?: unknown }).provider); // the switch in the assistant; the full parse below reports a bad body
                } catch { /* reported below */ }
                const deps = makeChatDeps(
                  { getApiKey: (p) => this.svc.secretsService.getApiKey(p), getSelectedModel: () => this.svc.settingsService.getSelectedModel() },
                  session?.email ?? 'local',
                  stop.signal,
                  provider,
                );
                if (confirmMatch) {
                  const c = JSON.parse(body) as { confirmToken?: unknown; decision?: unknown; params?: Record<string, unknown> };
                  if (typeof c.confirmToken !== 'string' || (c.decision !== 'confirm' && c.decision !== 'cancel')) {
                    throw new SyntaxError('confirmToken and decision (confirm | cancel) are required');
                  }
                  const result = await deps.actions!.confirm({
                    sessionKey: session?.email ?? 'local',
                    req: { confirmToken: c.confirmToken, decision: c.decision, ...(c.params ? { params: c.params } : {}) } as ActionConfirmRequest,
                  });
                  res.writeHead(200, { 'Content-Type': 'application/json' });
                  res.end(JSON.stringify(result));
                  return;
                }
                const parsed = JSON.parse(body) as { messages?: Array<{ role: string; content: string }>; scope?: ChatScope; fileRefs?: ChatRequest['fileRefs'] };
                const messages = (Array.isArray(parsed.messages) ? parsed.messages : []).filter(
                  (m) => m && typeof m.role === 'string' && typeof m.content === 'string',
                );
                const reply = await chatReply(
                  {
                    rfqId: rfqInUrl,
                    scope: parseScope(parsed.scope),
                    fileRefs: Array.isArray(parsed.fileRefs) ? parsed.fileRefs.filter((f) => f && typeof f.attachmentId === 'string' && typeof f.name === 'string') : undefined,
                    messages,
                  },
                  deps,
                );
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify(reply));
              } catch (e) {
                const badRequest = e instanceof SyntaxError || (e instanceof Error && e.message === 'No user message found');
                if (!badRequest) log.error(`[RFQChat] pipeline error: ${e}`);
                if (res.writableEnded || res.destroyed) return;
                res.writeHead(badRequest ? 400 : 503, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: e instanceof SyntaxError ? `Invalid request: ${e.message}` : badRequest ? 'No user message found' : `Chat backend error: ${e instanceof Error ? e.message : String(e)}` }));
              }
            })();
          });
          return;
        }

        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end('{"error":"Not found"}');
      });
      this.server.listen(PORT, '0.0.0.0', () => {
        log.info(`[BrowserApi] Listening on port ${PORT}`);
        // Keep SSE connections alive so browsers don't time them out
        setInterval(() => this.send(':heartbeat', {}), 30_000);
        resolve();
      });
      this.server.on('error', (e: NodeJS.ErrnoException) => {
        if (e.code === 'EADDRINUSE') {
          log.warn(`[BrowserApi] Port ${PORT} in use`);
          resolve();
        } else {
          reject(e);
        }
      });
    });
  }

  stop(): void {
    this.server?.close();
  }
}
