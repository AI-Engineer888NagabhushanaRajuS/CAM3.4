/**
 * Accomplish API - Interface to the Electron main process
 *
 * This module provides type-safe access to the accomplish API
 * exposed by the preload script via contextBridge.
 */

import type {
  Task,
  TaskConfig,
  TaskUpdateEvent,
  TaskStatus,
  PermissionRequest,
  PermissionResponse,
  TaskProgress,
  ApiKeyConfig,
  TaskMessage,
  BedrockCredentials,
  VertexCredentials,
  ProviderSettings,
  ProviderId,
  ConnectedProvider,
  TodoItem,
  ToolSupportStatus,
  Skill,
  McpConnector,
  FileAttachmentInfo,
  Workspace,
  WorkspaceCreateInput,
  WorkspaceUpdateInput,
  KnowledgeNote,
  KnowledgeNoteCreateInput,
  KnowledgeNoteUpdateInput,
  StoredFavorite,
  BrowserFramePayload,
  BrowserStatusPayload,
  BrowserNavigatePayload,
} from '@accomplish_ai/agent-core';
import type {
  CloudBrowserConfig,
  MessagingConnectionStatus,
  ScheduledTask,
  GoogleAccount,
  GoogleAccountStatus,
  OAuthProviderId,
  ConnectorAuthStatus,
} from '@accomplish_ai/agent-core/common';

// Published by the backend execution engine over SSE as it runs each skill —
// the frontend is a pure consumer, never computes this itself.
export interface RfqSkillProgressEvent {
  rfqId: string;
  skillCode: string;
  skillName: string;
  macroCategory: number;
  macroCategoryName: string;
  stepStatus: string;
  // Present only when stepStatus === 'failed' -- the tool's own reported
  // error message (e.g. "No QuoteWin file uploaded for rfq_id=...").
  error?: string;
  // What the step really did, from the tool's own result ("502 rows, 0 priced"; the reason it was skipped). `warning` = it ran but did nothing useful.
  detail?: string;
  warning?: boolean;
  updatedAt: string;
}

export interface Customer {
  customer_id: string;
  customer_name: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  project_id: string;
  customer_id: string;
  project_name: string;
  created_at: string;
  updated_at: string;
}

// One entry in the right panel's append-only progress log -- either a
// completed skill or the currently-running one. Deliberately a narrower
// shape than RfqSkillProgressEvent (below): the DB-reconstructed history has
// no per-skill timestamp or rfqId to carry, only what's needed to render.
export interface RfqSkillHistoryEntry {
  skillCode: string;
  skillName: string;
  macroCategory: number;
  stepStatus: string;
  // Present only when stepStatus === 'failed'. See RfqSkillProgressEvent.
  error?: string;
  detail?: string;
  warning?: boolean;
}

// One of the 8 real backend routing-profile skills that gate pipeline
// execution (Standard_BOM_Flow, logic_db.quote_routing_profiles). Distinct
// from the unrelated `Skill` type (agent-core/common) -- that one is a
// bundled-skills filesystem concept (source/isVerified/filePath/githubUrl,
// none of which apply here); this is DB-backed
// (system_skills_registry JOIN quote_routing_profiles.routing_sequence).
export interface RoutingProfileSkill {
  skillCode: string;         // system_skills_registry.mcp_tool_name -- also the exact
                             // string stored in routing_sequence's jsonb array
  skillName: string;
  skillIndex: number;        // 1-8, defines display/execution order
  macroCategory: number;     // used by the wizard to compute per-stage "all skills off"
  macroCategoryName: string;
  isEnabled: boolean;        // true iff skillCode is present in routing_sequence
}

export interface AdminUserRow {
  id: string;
  uid: string;
  fullName: string;
  email: string;
  role: 'admin' | 'user' | 'fde';
  isActive: boolean;
  createdAt: string;
}

export interface Currency {
  currencyCode: string;
  currencyName: string;
  conversionRate: number;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface RfqProjectTracking {
  rfq_id: string;
  customer_name: string;
  project_name: string;
  customer_id?: string;
  project_id?: string;
  created_at: string;
}

interface GwsAPI {
  listAccounts(): Promise<GoogleAccount[]>;
  startAuth(label: string): Promise<{ state: string; authUrl: string }>;
  completeAuth(state: string, code: string): Promise<GoogleAccount>;
  removeAccount(id: string): Promise<void>;
  updateLabel(id: string, label: string): Promise<void>;
  cancelAuth(state: string): Promise<void>;
  onStatusChanged(callback: (id: string, status: GoogleAccountStatus) => void): () => void;
  /**
   * Emitted when the background OAuth consumer can't register the account
   * (missing refresh token, storage failure, etc.). Timeout / user-cancel
   * don't fire on this channel. See M5 review finding P2.3.
   */
  onAuthError(callback: (payload: { message: string }) => void): () => void;
}

// Define the API interface
interface AccomplishAPI {
  // App info
  getVersion(): Promise<string>;
  getPlatform(): Promise<string>;

  // Shell
  openExternal(url: string): Promise<void>;

  // RFQ operations
  checkRfqExists(params: { rfqId: string }): Promise<{ exists: boolean }>;
  rfqGetFileVersions(params: { rfqId: string }): Promise<{
    versions: Array<{
      version: number;
      isActive: boolean;
      processStage: number;
      hitlRequired: boolean;
      updatedAt: string;
      bom: { id: string; fileName: string } | null;
      quoteWin: { id: string; fileName: string } | null;
      costingSheet: { id: string; fileName: string } | null;
    }>;
  }>;
  rfqActivateVersion(params: { rfqId: string; version: number }): Promise<{ success: boolean }>;
  rfqGetProcessStage(params: { rfqId: string }): Promise<{ stage: number | null }>;
  rfqGetHitlPending(params: { rfqId: string }): Promise<{ hitlRequired: boolean }>;
  // Reconstructs the progress log from DB alone -- only skills that have
  // actually run or are currently running, nothing ahead of that.
  rfqGetSkillHistory(params: { rfqId: string }): Promise<{ history: RfqSkillHistoryEntry[] }>;

  // Routing-profile skill toggles (Standard_BOM_Flow) -- app-wide, persistent,
  // gates real pipeline execution. Distinct from getSkills/setSkillEnabled,
  // which serve the unrelated bundled-skills/Accomplish-platform concept.
  rfqGetRoutingProfileSkills(): Promise<{ skills: RoutingProfileSkill[] }>;
  rfqSetRoutingProfileSkillEnabled(params: { skillCode: string; enabled: boolean }): Promise<{ success: boolean }>;

  // Admin-only user management (Settings -> Users tab). Gated server-side by
  // requireAdminSession -- a non-admin session gets a thrown Forbidden error.
  adminListUsers(): Promise<{ users: AdminUserRow[] }>;
  adminCreateUser(params: { uid: string; fullName: string; email: string; password: string; role: 'admin' | 'user' | 'fde' }): Promise<{ user: AdminUserRow }>;
  adminUpdateUser(params: { userId: string; fullName?: string; email?: string; role?: 'admin' | 'user' | 'fde'; isActive?: boolean }): Promise<{ user: AdminUserRow }>;
  adminResetUserPassword(params: { userId: string; newPassword: string }): Promise<{ success: boolean }>;
  adminDeleteUser(params: { userId: string }): Promise<{ success: boolean }>;

  // Currency conversion rates + default quote currency (Settings -> Currencies
  // tab). CUD operations are admin-gated server-side (requireAdminSession);
  // getDefaultQuoteCurrency is readable by any authenticated session since it
  // affects what currency they see throughout the app.
  listCurrencies(): Promise<{ currencies: Currency[] }>;
  feasibilityGetSettings(): Promise<FeasibilityReadResult>;
  feasibilitySaveSettings(params: { settings: FeasibilitySettingsInput }): Promise<{ settings: FeasibilitySettingsInput; saved: boolean }>;
  createCurrency(params: { currencyCode: string; currencyName: string; conversionRate: number }): Promise<{ currency: Currency }>;
  updateCurrency(params: { currencyCode: string; currencyName?: string; conversionRate?: number; isActive?: boolean }): Promise<{ currency: Currency }>;
  deleteCurrency(params: { currencyCode: string }): Promise<{ success: boolean }>;
  getDefaultQuoteCurrency(): Promise<{ currencyCode: string }>;
  setDefaultQuoteCurrency(params: { currencyCode: string }): Promise<{ success: boolean }>;

  // Embedded Superset dashboard (stage 9, Reports & Analytics). dashboardUuid defaults
  // server-side to the one configured dashboard if omitted. rfqId, when provided, scopes
  // the embed to just that RFQ's rows via Superset Row Level Security (see superset-client.ts).
  supersetGetGuestToken(params?: { dashboardUuid?: string; rfqId?: string }): Promise<{ guestToken: string; supersetDomain: string }>;

  // Project Tracking — Customer/Project master data + RFQ creation, layered
  // in front of the existing pipeline (see rfq operations above, unchanged).
  listCustomers(): Promise<{ customers: Customer[] }>;
  createCustomer(params: { customerName: string }): Promise<{ customer: Customer }>;
  updateCustomer(params: { customerId: string; customerName: string }): Promise<{ customer: Customer }>;
  deleteCustomer(params: { customerId: string }): Promise<{ success: boolean }>;
  listProjects(params: { customerId?: string }): Promise<{ projects: Project[] }>;
  createProject(params: { customerId: string; projectName: string }): Promise<{ project: Project }>;
  updateProject(params: { projectId: string; projectName: string; customerId?: string }): Promise<{ project: Project }>;
  deleteProject(params: { projectId: string }): Promise<{ success: boolean }>;
  getNextRfqId(): Promise<{ rfqId: string }>;
  createRfq(params: { rfqId: string; customerId: string; projectId: string }): Promise<{ rfq: RfqProjectTracking }>;
  searchRfqs(params: { query: string }): Promise<{ rfqs: RfqProjectTracking[] }>;
  // Positional args (not a params object) — matches the daemon's existing
  // `hitl:submit-decision` dispatch case, which reads args[0]/args[1] directly.
  hitlSubmitDecision(rfqId: string, approved: boolean): Promise<{ success: boolean }>;

  // Task operations
  startTask(config: TaskConfig): Promise<Task>;
  cancelTask(taskId: string): Promise<void>;
  interruptTask(taskId: string): Promise<void>;
  getTask(taskId: string): Promise<Task | null>;
  listTasks(): Promise<Task[]>;
  deleteTask(taskId: string): Promise<void>;
  clearTaskHistory(): Promise<void>;

  // Permission responses
  respondToPermission(response: PermissionResponse): Promise<void>;

  // Session management
  resumeSession(
    sessionId: string,
    prompt: string,
    taskId?: string,
    attachments?: FileAttachmentInfo[],
  ): Promise<Task>;

  // Settings
  getApiKeys(): Promise<ApiKeyConfig[]>;
  addApiKey(
    provider:
      | 'anthropic'
      | 'openai'
      | 'openrouter'
      | 'google'
      | 'xai'
      | 'deepseek'
      | 'moonshot'
      | 'zai'
      | 'azure-foundry'
      | 'custom'
      | 'bedrock'
      | 'litellm'
      | 'lmstudio'
      | 'nebius'
      | 'together'
      | 'fireworks'
      | 'groq'
      | 'elevenlabs'
      | 'nim'
      | 'minimax'
      | 'vertex'
      | 'venice'
      | 'aws-agentcore'
      | 'browserbase'
      | 'steel',
    key: string,
    label?: string,
  ): Promise<ApiKeyConfig>;
  removeApiKey(id: string): Promise<void>;
  getNotificationsEnabled(): Promise<boolean>;
  setNotificationsEnabled(enabled: boolean): Promise<void>;
  getDebugMode(): Promise<boolean>;
  setDebugMode(enabled: boolean): Promise<void>;
  getTheme(): Promise<string>;
  setTheme(theme: string): Promise<void>;
  onThemeChange?(callback: (data: { theme: string; resolved: string }) => void): () => void;
  getLanguage(): Promise<string>;
  setLanguage(language: string): Promise<void>;
  getAppSettings(): Promise<{
    debugMode: boolean;
    onboardingComplete: boolean;
    theme: string;
    language: string;
  }>;
  getCloudBrowserConfig(): Promise<CloudBrowserConfig | null>;
  setCloudBrowserConfig(config: CloudBrowserConfig | null): Promise<void>;

  getWhatsAppConfig(): Promise<{
    providerId: string;
    enabled: boolean;
    status: MessagingConnectionStatus;
    phoneNumber?: string;
    lastConnectedAt?: number;
    qrCode?: string;
    qrIssuedAt?: number;
  } | null>;
  connectWhatsApp(): Promise<void>;
  disconnectWhatsApp(): Promise<void>;
  setWhatsAppEnabled(enabled: boolean): Promise<void>;
  onWhatsAppQR(callback: (qr: string) => void): () => void;
  onWhatsAppStatus(callback: (status: MessagingConnectionStatus) => void): () => void;

  getOpenAiBaseUrl(): Promise<string>;
  setOpenAiBaseUrl(baseUrl: string): Promise<void>;
  getOpenAiOauthStatus(): Promise<{ connected: boolean; expires?: number }>;
  loginOpenAiWithChatGpt(): Promise<{ ok: boolean; openedUrl?: string }>;
  getSlackMcpOauthStatus(): Promise<{ connected: boolean; pendingAuthorization: boolean }>;
  loginSlackMcp(): Promise<{ ok: boolean }>;
  logoutSlackMcp(): Promise<void>;
  getCopilotOAuthStatus(): Promise<{ connected: boolean; username?: string; expiresAt?: number }>;
  loginGithubCopilot(): Promise<{
    ok: boolean;
    userCode?: string;
    verificationUri?: string;
    expiresIn?: number;
  }>;
  logoutGithubCopilot(): Promise<void>;

  // API Key management
  hasApiKey(): Promise<boolean>;
  setApiKey(key: string): Promise<void>;
  getApiKey(): Promise<string | null>;
  validateApiKey(key: string): Promise<{ valid: boolean; error?: string }>;
  validateApiKeyForProvider(
    provider: string,
    key: string,
    options?: Record<string, unknown>,
  ): Promise<{ valid: boolean; error?: string }>;
  clearApiKey(): Promise<void>;

  // Multi-provider API keys
  getAllApiKeys(): Promise<Record<string, { exists: boolean; prefix?: string }>>;
  hasAnyApiKey(): Promise<boolean>;

  // Onboarding
  getOnboardingComplete(): Promise<boolean>;
  setOnboardingComplete(complete: boolean): Promise<void>;

  // OpenCode CLI
  checkOpenCodeCli(): Promise<{
    installed: boolean;
    version: string | null;
    installCommand: string;
  }>;
  getOpenCodeVersion(): Promise<string | null>;

  // Model selection
  getSelectedModel(): Promise<{
    provider: string;
    model: string;
    baseUrl?: string;
    deploymentName?: string;
  } | null>;
  setSelectedModel(model: {
    provider: string;
    model: string;
    baseUrl?: string;
    deploymentName?: string;
  }): Promise<void>;

  // Ollama configuration
  testOllamaConnection(url: string): Promise<{
    success: boolean;
    models?: Array<{
      id: string;
      displayName: string;
      size: number;
      toolSupport?: ToolSupportStatus;
    }>;
    error?: string;
  }>;
  getOllamaConfig(): Promise<{
    baseUrl: string;
    enabled: boolean;
    lastValidated?: number;
    models?: Array<{
      id: string;
      displayName: string;
      size: number;
      toolSupport?: ToolSupportStatus;
    }>;
  } | null>;
  setOllamaConfig(
    config: {
      baseUrl: string;
      enabled: boolean;
      lastValidated?: number;
      models?: Array<{
        id: string;
        displayName: string;
        size: number;
        toolSupport?: ToolSupportStatus;
      }>;
    } | null,
  ): Promise<void>;

  // Azure Foundry configuration
  getAzureFoundryConfig(): Promise<{
    baseUrl: string;
    deploymentName: string;
    authType: 'api-key' | 'entra-id';
    enabled: boolean;
    lastValidated?: number;
  } | null>;
  setAzureFoundryConfig(
    config: {
      baseUrl: string;
      deploymentName: string;
      authType: 'api-key' | 'entra-id';
      enabled: boolean;
      lastValidated?: number;
    } | null,
  ): Promise<void>;
  testAzureFoundryConnection(config: {
    endpoint: string;
    deploymentName: string;
    authType: 'api-key' | 'entra-id';
    apiKey?: string;
  }): Promise<{ success: boolean; error?: string }>;
  saveAzureFoundryConfig(config: {
    endpoint: string;
    deploymentName: string;
    authType: 'api-key' | 'entra-id';
    apiKey?: string;
  }): Promise<void>;

  // Dynamic model fetching (generic, config-driven)
  fetchProviderModels(
    providerId: string,
    options?: { baseUrl?: string; zaiRegion?: string },
  ): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string }>;
    error?: string;
  }>;

  // OpenRouter configuration
  fetchOpenRouterModels(): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string; provider: string; contextLength: number }>;
    error?: string;
  }>;

  // LiteLLM configuration
  testLiteLLMConnection(
    url: string,
    apiKey?: string,
  ): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string; provider: string; contextLength: number }>;
    error?: string;
  }>;
  fetchLiteLLMModels(): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string; provider: string; contextLength: number }>;
    error?: string;
  }>;
  getLiteLLMConfig(): Promise<{
    baseUrl: string;
    enabled: boolean;
    lastValidated?: number;
    models?: Array<{ id: string; name: string; provider: string; contextLength: number }>;
  } | null>;
  setLiteLLMConfig(
    config: {
      baseUrl: string;
      enabled: boolean;
      lastValidated?: number;
      models?: Array<{ id: string; name: string; provider: string; contextLength: number }>;
    } | null,
  ): Promise<void>;

  // LM Studio configuration
  testLMStudioConnection(url: string): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string; toolSupport: ToolSupportStatus }>;
    error?: string;
  }>;
  fetchLMStudioModels(): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string; toolSupport: ToolSupportStatus }>;
    error?: string;
  }>;
  getLMStudioConfig(): Promise<{
    baseUrl: string;
    enabled: boolean;
    lastValidated?: number;
    models?: Array<{ id: string; name: string; toolSupport: ToolSupportStatus }>;
  } | null>;
  setLMStudioConfig(
    config: {
      baseUrl: string;
      enabled: boolean;
      lastValidated?: number;
      models?: Array<{ id: string; name: string; toolSupport: ToolSupportStatus }>;
    } | null,
  ): Promise<void>;

  // HuggingFace configuration (ENG-687)
  getHuggingFaceLocalConfig(): Promise<{
    selectedModelId: string | null;
    serverPort: number | null;
    enabled: boolean;
    quantization: 'q4' | 'fp32' | null;
    devicePreference: 'auto' | 'cpu' | 'cuda' | 'webgpu' | null;
  } | null>;
  setHuggingFaceLocalConfig(
    config: {
      selectedModelId: string | null;
      serverPort: number | null;
      enabled: boolean;
      quantization: 'q4' | 'fp32' | null;
      devicePreference: 'auto' | 'cpu' | 'cuda' | 'webgpu' | null;
    } | null,
  ): Promise<void>;
  listHuggingFaceModels(): Promise<{
    cached: Array<{ id: string; displayName: string; sizeBytes?: number; downloaded: boolean }>;
    suggested: Array<{ id: string; displayName: string; sizeBytes?: number; downloaded: boolean }>;
  }>;
  downloadHuggingFaceModel(modelId: string): Promise<{ success: boolean; error?: string }>;
  startHuggingFaceServer(
    modelId: string,
  ): Promise<{ success: boolean; port?: number; error?: string }>;
  stopHuggingFaceServer(): Promise<{ success: boolean; error?: string }>;
  getHuggingFaceServerStatus(): Promise<{
    running: boolean;
    port: number | null;
    loadedModel: string | null;
    isLoading: boolean;
  }>;
  testHuggingFaceConnection(): Promise<{ success: boolean; error?: string }>;
  deleteHuggingFaceModel(modelId: string): Promise<{ success: boolean; error?: string }>;
  onHuggingFaceDownloadProgress(
    callback: (progress: {
      modelId: string;
      status: 'downloading' | 'complete' | 'error';
      progress: number;
      error?: string;
    }) => void,
  ): () => void;

  // NVIDIA NIM configuration
  testNimConnection(
    url: string,
    apiKey: string,
  ): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string; provider: string; contextLength: number }>;
    error?: string;
  }>;
  fetchNimModels(): Promise<{
    success: boolean;
    models?: Array<{ id: string; name: string; provider: string; contextLength: number }>;
    error?: string;
  }>;

  // Custom OpenAI-compatible endpoint configuration
  testCustomConnection(
    baseUrl: string,
    apiKey?: string,
  ): Promise<{
    success: boolean;
    error?: string;
  }>;

  // Bedrock configuration
  validateBedrockCredentials(
    credentials: BedrockCredentials,
  ): Promise<{ valid: boolean; error?: string }>;
  saveBedrockCredentials(credentials: BedrockCredentials): Promise<ApiKeyConfig>;
  getBedrockCredentials(): Promise<BedrockCredentials | null>;
  fetchBedrockModels(credentials: string): Promise<{
    success: boolean;
    models: Array<{ id: string; name: string; provider: string }>;
    error?: string;
  }>;

  // Vertex AI configuration
  validateVertexCredentials(
    credentials: VertexCredentials,
  ): Promise<{ valid: boolean; error?: string }>;
  saveVertexCredentials(credentials: VertexCredentials): Promise<ApiKeyConfig>;
  getVertexCredentials(): Promise<VertexCredentials | null>;
  fetchVertexModels(credentials: string): Promise<{
    success: boolean;
    models: Array<{ id: string; name: string; provider: string }>;
    error?: string;
  }>;
  detectVertexProject(): Promise<{ success: boolean; projectId: string | null }>;
  listVertexProjects(): Promise<{
    success: boolean;
    projects: Array<{ projectId: string; name: string }>;
    error?: string;
  }>;

  // E2E Testing
  isE2EMode(): Promise<boolean>;

  // Provider Settings API
  getProviderSettings(): Promise<ProviderSettings>;
  setActiveProvider(providerId: ProviderId | null): Promise<void>;
  getConnectedProvider(providerId: ProviderId): Promise<ConnectedProvider | null>;
  setConnectedProvider(providerId: ProviderId, provider: ConnectedProvider): Promise<void>;
  removeConnectedProvider(providerId: ProviderId): Promise<void>;
  updateProviderModel(providerId: ProviderId, modelId: string | null): Promise<void>;
  setProviderDebugMode(enabled: boolean): Promise<void>;
  getProviderDebugMode(): Promise<boolean>;

  // Todo operations
  getTodosForTask(taskId: string): Promise<TodoItem[]>;

  // Favorites
  addFavorite(taskId: string): Promise<void>;
  removeFavorite(taskId: string): Promise<void>;
  listFavorites(): Promise<StoredFavorite[]>;

  // File attachments
  pickFolder(): Promise<string | null>;
  pickFiles(): Promise<FileAttachmentInfo[]>;
  getFilePath(file: File): string;
  processDroppedFiles(paths: string[]): Promise<FileAttachmentInfo[]>;

  // Event subscriptions
  onTaskUpdate(callback: (event: TaskUpdateEvent) => void): () => void;
  onTaskUpdateBatch?(
    callback: (event: { taskId: string; messages: TaskMessage[] }) => void,
  ): () => void;
  onPermissionRequest(callback: (request: PermissionRequest) => void): () => void;
  onTaskProgress(callback: (progress: TaskProgress) => void): () => void;
  onRfqSkillProgress?(callback: (event: RfqSkillProgressEvent) => void): () => void;
  onDebugLog(callback: (log: unknown) => void): () => void;
  onDebugModeChange?(callback: (data: { enabled: boolean }) => void): () => void;
  onTaskStatusChange?(callback: (data: { taskId: string; status: TaskStatus }) => void): () => void;
  onTaskSummary?(callback: (data: { taskId: string; summary: string }) => void): () => void;
  onTodoUpdate?(callback: (data: { taskId: string; todos: TodoItem[] }) => void): () => void;
  onAuthError?(callback: (data: { providerId: string; message: string }) => void): () => void;

  // Browser Preview (ENG-695)
  onBrowserFrame?(callback: (event: BrowserFramePayload & { taskId: string }) => void): () => void;
  onBrowserNavigate?(
    callback: (event: BrowserNavigatePayload & { taskId: string; pageName: string }) => void,
  ): () => void;
  onBrowserStatus?(
    callback: (
      event: BrowserStatusPayload & { taskId: string; pageName: string; message?: string },
    ) => void,
  ): () => void;
  startBrowserPreview?(taskId: string, pageName?: string): Promise<{ success: boolean }>;
  stopBrowserPreview?(taskId: string): Promise<{ stopped: boolean }>;
  getBrowserPreviewStatus?(): Promise<{ active: boolean }>;

  // Speech-to-Text
  speechIsConfigured(): Promise<boolean>;
  speechGetConfig(): Promise<{ enabled: boolean; hasApiKey: boolean; apiKeyPrefix?: string }>;
  speechValidate(apiKey?: string): Promise<{ valid: boolean; error?: string }>;
  speechTranscribe(
    audioData: ArrayBuffer,
    mimeType?: string,
  ): Promise<
    | {
        success: true;
        result: { text: string; confidence?: number; duration: number; timestamp: number };
      }
    | {
        success: false;
        error: { code: string; message: string };
      }
  >;

  // Logging
  logEvent(payload: {
    level?: string;
    message: string;
    context?: Record<string, unknown>;
  }): Promise<unknown>;
  exportLogs(): Promise<{ success: boolean; path?: string; error?: string; reason?: string }>;

  // Debug bug reporting
  captureScreenshot(): Promise<{
    success: boolean;
    data?: string;
    width?: number;
    height?: number;
    error?: string;
  }>;
  captureAxtree(): Promise<{ success: boolean; data?: string; error?: string }>;
  generateBugReport(data: {
    taskId?: string;
    taskPrompt?: string;
    taskStatus?: string;
    taskCreatedAt?: string;
    taskCompletedAt?: string;
    messages?: unknown[];
    debugLogs?: unknown[];
    screenshot?: string;
    axtree?: string;
    appVersion?: string;
    platform?: string;
  }): Promise<{ success: boolean; path?: string; error?: string; reason?: string }>;

  // Workspace management
  listWorkspaces(): Promise<Workspace[]>;
  getActiveWorkspaceId(): Promise<string | null>;
  switchWorkspace(workspaceId: string): Promise<{ success: boolean; reason?: string }>;
  createWorkspace(input: WorkspaceCreateInput): Promise<Workspace>;
  updateWorkspace(id: string, input: WorkspaceUpdateInput): Promise<Workspace | null>;
  deleteWorkspace(id: string): Promise<boolean>;

  // Knowledge Notes
  listKnowledgeNotes(workspaceId: string): Promise<KnowledgeNote[]>;
  createKnowledgeNote(input: KnowledgeNoteCreateInput): Promise<KnowledgeNote>;
  updateKnowledgeNote(
    id: string,
    workspaceId: string,
    input: KnowledgeNoteUpdateInput,
  ): Promise<KnowledgeNote | null>;
  deleteKnowledgeNote(id: string, workspaceId: string): Promise<boolean>;

  // Workspace event subscriptions
  onWorkspaceChanged?(callback: (data: { workspaceId: string }) => void): () => void;
  onWorkspaceDeleted?(callback: (data: { workspaceId: string }) => void): () => void;

  // Skills management
  getSkills(): Promise<Skill[]>;
  getEnabledSkills(): Promise<Skill[]>;
  setSkillEnabled(id: string, enabled: boolean): Promise<void>;
  getSkillContent(id: string): Promise<string | null>;
  getUserSkillsPath(): Promise<string>;
  pickSkillFolder(): Promise<string | null>;
  addSkillFromFolder(folderPath: string): Promise<Skill | null>;
  addSkillFromGitHub(rawUrl: string): Promise<Skill>;
  deleteSkill(id: string): Promise<void>;
  resyncSkills(): Promise<Skill[]>;
  openSkillInEditor(filePath: string): Promise<void>;
  showSkillInFolder(filePath: string): Promise<void>;

  // Daemon
  getDaemonSocketPath(): Promise<string>;

  // Daemon control
  daemonPing(): Promise<{ status: string; uptime: number }>;
  daemonRestart(): Promise<{ success: boolean }>;
  daemonStop(): Promise<{ success: boolean }>;
  daemonStart(): Promise<{ success: boolean }>;

  // Close behavior
  getCloseBehavior(): Promise<string>;
  setCloseBehavior(behavior: string): Promise<void>;

  // App close dialog
  onCloseRequested?(callback: () => void): () => void;
  respondToClose?(decision: 'keep-daemon' | 'stop-daemon' | 'cancel'): void;

  // Daemon connection events
  onDaemonDisconnected(callback: () => void): () => void;
  onDaemonReconnected(callback: () => void): () => void;
  onDaemonReconnectFailed(callback: () => void): () => void;

  // Sandbox configuration
  getSandboxConfig(): Promise<{
    mode: 'disabled' | 'native' | 'docker';
    allowedPaths: string[];
    networkRestricted: boolean;
    allowedHosts: string[];
    dockerImage?: string;
    networkPolicy?: { allowOutbound: boolean; allowedHosts?: string[] };
  }>;
  setSandboxConfig(config: {
    mode: 'disabled' | 'native' | 'docker';
    allowedPaths: string[];
    networkRestricted: boolean;
    allowedHosts: string[];
    dockerImage?: string;
    networkPolicy?: { allowOutbound: boolean; allowedHosts?: string[] };
  }): Promise<void>;

  // Scheduler
  listSchedules(workspaceId?: string): Promise<ScheduledTask[]>;
  createSchedule(cron: string, prompt: string, workspaceId?: string): Promise<ScheduledTask>;
  deleteSchedule(scheduleId: string): Promise<void>;
  setScheduleEnabled(scheduleId: string, enabled: boolean): Promise<void>;
  isAutoStartEnabled(): Promise<boolean>;

  // MCP Connectors
  getConnectors(): Promise<McpConnector[]>;
  addConnector(name: string, url: string): Promise<McpConnector>;
  deleteConnector(id: string): Promise<void>;
  setConnectorEnabled(id: string, enabled: boolean): Promise<void>;
  startConnectorOAuth(connectorId: string): Promise<{ state: string; authUrl: string }>;
  completeConnectorOAuth(state: string, code: string): Promise<McpConnector>;
  disconnectConnector(connectorId: string): Promise<void>;
  onMcpAuthCallback?(callback: (url: string) => void): () => void;

  // Built-in connector OAuth (Jira, GitHub, Notion, monday.com, Lightdash, Datadog)
  getBuiltInConnectorAuthStatus(): Promise<ConnectorAuthStatus[]>;
  loginBuiltInConnector(providerId: OAuthProviderId): Promise<{ ok: boolean }>;
  logoutBuiltInConnector(providerId: OAuthProviderId): Promise<void>;
  lightdashGetServerUrl(): Promise<string | null>;
  lightdashSetServerUrl(url: string): Promise<void>;
  datadogGetServerUrl(): Promise<string | null>;
  datadogSetServerUrl(url: string): Promise<void>;

  // Accomplish AI Free Tier
  accomplishAiConnect(): Promise<{
    deviceFingerprint: string;
    spentCredits: number;
    remainingCredits: number;
    totalCredits: number;
    resetsAt: string;
  }>;
  accomplishAiEnsureReady(): Promise<{ deviceFingerprint: string }>;
  accomplishAiDisconnect(): Promise<void>;
  accomplishAiGetUsage(): Promise<{
    spentCredits: number;
    remainingCredits: number;
    totalCredits: number;
    resetsAt: string;
  }>;
  accomplishAiGetStatus(): Promise<{ connected: boolean }>;
  onAccomplishAiUsageUpdate(
    callback: (usage: {
      spentCredits: number;
      remainingCredits: number;
      totalCredits: number;
      resetsAt: string;
    }) => void,
  ): () => void;

  // Build capabilities
  getBuildCapabilities(): Promise<{ hasFreeMode: boolean; hasAnalytics: boolean }>;

  // Google Workspace multi-account
  gws?: GwsAPI;

  // Analytics — renderer-side tracking bridge
  analytics: {
    track(eventName: string, params?: Record<string, string | number | boolean>): Promise<void>;
    trackPageView(pagePath: string, pageTitle?: string): Promise<void>;
    trackSubmitTask(): Promise<void>;
    trackNewTask(): Promise<void>;
    trackOpenSettings(): Promise<void>;
    trackSaveApiKey(provider: string, success: boolean, connectionMethod?: string): Promise<void>;
    trackSelectProvider(provider: string): Promise<void>;
    trackSelectModel(model: string, provider?: string): Promise<void>;
    trackToggleDebugMode(enabled: boolean): Promise<void>;
    trackTaskStart(taskId: string, sessionId: string, taskType: string): Promise<void>;
    trackTaskComplete(
      taskId: string,
      sessionId: string,
      taskType: string,
      durationMs: number,
      totalSteps: number,
      hadErrors: boolean,
    ): Promise<void>;
    trackTaskError(
      taskId: string,
      sessionId: string,
      taskType: string,
      durationMs: number,
      totalSteps: number,
      errorType: string,
    ): Promise<void>;
    trackPermissionRequested(
      taskId: string,
      sessionId: string,
      taskType: string,
      permissionType: string,
    ): Promise<void>;
    trackPermissionResponse(
      taskId: string,
      sessionId: string,
      taskType: string,
      permissionType: string,
      granted: boolean,
    ): Promise<void>;
    trackToolUsed(
      taskId: string,
      sessionId: string,
      taskType: string,
      toolName: string,
    ): Promise<void>;
    trackUserInteraction(
      taskId: string,
      sessionId: string,
      taskType: string,
      interactionType: string,
      usedSuggestion: boolean,
    ): Promise<void>;
    trackAppClose(): Promise<void>;
    trackAppBackgrounded(): Promise<void>;
    trackAppForegrounded(): Promise<void>;
    trackModelSelectionStep(
      step: string,
      isOnboarding: boolean,
      provider?: string,
      model?: string,
    ): Promise<void>;
    trackModelSelectionComplete(
      provider: string,
      isOnboarding: boolean,
      model?: string,
    ): Promise<void>;
    trackModelSelectionAbandoned(lastStep: string, isOnboarding: boolean): Promise<void>;
    trackHistoryViewed(): Promise<void>;
    trackTaskFromHistory(): Promise<void>;
    trackHistoryCleared(): Promise<void>;
    trackTaskDetailsExpanded(): Promise<void>;
    trackOutputCopied(): Promise<void>;
    trackProviderDisconnected(provider: string): Promise<void>;
    trackHelpLinkClicked(provider: string): Promise<void>;
    trackSkillAction(params: {
      action: string;
      skill_name?: string;
      enabled?: boolean;
      filter?: string;
      source?: string;
    }): Promise<void>;
    trackSaveVoiceApiKey(success: boolean): Promise<void>;
    trackExportLogs(): Promise<void>;
    trackThreadExported(): Promise<void>;
    trackTaskLauncherAction(action: string): Promise<void>;
    trackTaskFeedback(
      taskId: string,
      sessionId: string,
      rating: string,
      taskStatus: string,
      feedbackStage: string,
      feedbackReason?: string,
      feedbackText?: string,
    ): Promise<void>;
    trackStopAgent(taskId: string, sessionId: string): Promise<void>;
    trackProviderBoxClicked(params: {
      provider_id: string;
      is_connected: boolean;
      is_onboarding: boolean;
    }): Promise<void>;
  };
}

type RawAccomplishAPI = Omit<
  AccomplishAPI,
  | 'validateBedrockCredentials'
  | 'saveBedrockCredentials'
  | 'validateVertexCredentials'
  | 'saveVertexCredentials'
> & {
  validateBedrockCredentials(credentials: string): Promise<{ valid: boolean; error?: string }>;
  saveBedrockCredentials(credentials: string): Promise<ApiKeyConfig>;
  validateVertexCredentials(credentials: string): Promise<{ valid: boolean; error?: string }>;
  saveVertexCredentials(credentials: string): Promise<ApiKeyConfig>;
};

interface AccomplishShell {
  version: string;
  platform: string;
  isElectron: true;
}

// Extend Window interface
declare global {
  interface Window {
    accomplish?: RawAccomplishAPI;
    accomplishShell?: AccomplishShell;
  }
}

// Singleton — getAccomplish() must return the same reference on every call.
// Components include it in useEffect dependency arrays; a new object every call
// would trigger infinite re-render loops.
let _accomplishSingleton: AccomplishAPI | null = null;

function _buildAccomplish(): AccomplishAPI {
  const base = window.accomplish!;
  // Overrides that adapt the raw IPC surface (JSON serialization, namespace flattening).
  // Stored as a plain object so the Proxy below can check membership cheaply.
  const overrides: Record<string, unknown> = {
    validateBedrockCredentials: async (
      credentials: BedrockCredentials,
    ): Promise<{ valid: boolean; error?: string }> => {
      return window.accomplish!.validateBedrockCredentials(JSON.stringify(credentials));
    },

    saveBedrockCredentials: async (credentials: BedrockCredentials): Promise<ApiKeyConfig> => {
      return window.accomplish!.saveBedrockCredentials(JSON.stringify(credentials));
    },

    getBedrockCredentials: async (): Promise<BedrockCredentials | null> => {
      return window.accomplish!.getBedrockCredentials();
    },

    fetchBedrockModels: (credentials: string) => window.accomplish!.fetchBedrockModels(credentials),

    validateVertexCredentials: async (
      credentials: VertexCredentials,
    ): Promise<{ valid: boolean; error?: string }> => {
      return window.accomplish!.validateVertexCredentials(JSON.stringify(credentials));
    },

    saveVertexCredentials: async (credentials: VertexCredentials): Promise<ApiKeyConfig> => {
      return window.accomplish!.saveVertexCredentials(JSON.stringify(credentials));
    },

    getVertexCredentials: async (): Promise<VertexCredentials | null> => {
      return window.accomplish!.getVertexCredentials();
    },

    fetchVertexModels: (credentials: string) => window.accomplish!.fetchVertexModels(credentials),

    detectVertexProject: () => window.accomplish!.detectVertexProject(),

    listVertexProjects: () => window.accomplish!.listVertexProjects(),

    listHuggingFaceModels: () => window.accomplish!.listHuggingFaceModels(),

    downloadHuggingFaceModel: (modelId: string) =>
      window.accomplish!.downloadHuggingFaceModel(modelId),

    startHuggingFaceServer: (modelId: string) => window.accomplish!.startHuggingFaceServer(modelId),

    stopHuggingFaceServer: () => window.accomplish!.stopHuggingFaceServer(),

    onHuggingFaceDownloadProgress: (
      callback: (progress: {
        modelId: string;
        status: 'downloading' | 'complete' | 'error';
        progress: number;
        error?: string;
      }) => void,
    ) => window.accomplish!.onHuggingFaceDownloadProgress(callback),

    // Google Workspace flat helpers — delegate to the gws namespace
    gwsListAccounts: (): Promise<GoogleAccount[]> => {
      if (!window.accomplish?.gws) {
        return Promise.reject(new Error('GWS API not available'));
      }
      return window.accomplish.gws.listAccounts();
    },

    gwsStartAuth: (label: string): Promise<{ state: string; authUrl: string }> => {
      if (!window.accomplish?.gws) {
        return Promise.reject(new Error('GWS API not available'));
      }
      return window.accomplish.gws.startAuth(label);
    },

    gwsCompleteAuth: (state: string, code: string): Promise<GoogleAccount> => {
      if (!window.accomplish?.gws) {
        return Promise.reject(new Error('GWS API not available'));
      }
      return window.accomplish.gws.completeAuth(state, code);
    },

    gwsRemoveAccount: (id: string): Promise<void> => {
      if (!window.accomplish?.gws) {
        return Promise.reject(new Error('GWS API not available'));
      }
      return window.accomplish.gws.removeAccount(id);
    },

    gwsUpdateLabel: (id: string, label: string): Promise<void> => {
      if (!window.accomplish?.gws) {
        return Promise.reject(new Error('GWS API not available'));
      }
      return window.accomplish.gws.updateLabel(id, label);
    },

    gwsOnStatusChanged: (cb: (id: string, status: GoogleAccountStatus) => void): (() => void) => {
      if (!window.accomplish?.gws) {
        throw new Error('GWS API not available');
      }
      return window.accomplish.gws.onStatusChanged(cb);
    },
  };

  // Use a Proxy so every AccomplishAPI method is reachable even when `base` is itself
  // a Proxy (e.g. the dev mock). Spreading a Proxy only copies own enumerable keys of its
  // target — the get-trap fallback is lost. Proxy delegation preserves it.
  return new Proxy(overrides, {
    get(target, prop) {
      if (prop in target) return target[String(prop)];
      return Reflect.get(base, prop);
    },
  }) as unknown as AccomplishAPI;
}

/**
 * Get the accomplish API (singleton — same reference on every call).
 * Throws if not running in Electron.
 */
export function getAccomplish() {
  if (!window.accomplish) {
    _accomplishSingleton = null;
    throw new Error('Accomplish API not initialized — accomplish-backend.ts must load first');
  }
  if (!_accomplishSingleton) {
    _accomplishSingleton = _buildAccomplish();
  }
  return _accomplishSingleton;
}

/**
 * Check if running in Electron shell
 */
export function isRunningInElectron(): boolean {
  return window.accomplishShell?.isElectron === true;
}

/**
 * Get shell version if available
 */
export function getShellVersion(): string | null {
  return window.accomplishShell?.version ?? null;
}

/**
 * Get shell platform if available
 */
export function getShellPlatform(): string | null {
  return window.accomplishShell?.platform ?? null;
}

/**
 * React hook to use the accomplish API
 */
export function useAccomplish(): AccomplishAPI {
  return getAccomplish();
}

/** Settings > Feasibility: the rules the Feasibility & Risk step applies (the pipeline reads them on every run). */
export interface FeasibilityMachineRule { name: string; column: string; operator: string; value: string; effect: string }
export interface FeasibilitySettingsInput {
  lead_time_limit_weeks: number;
  cannot_build_statuses: string[];
  medium_statuses: string[];
  no_price_cannot_build: boolean;
  no_lead_time_high: boolean;
  ltb_high: boolean;
  ncnr_medium: boolean;
  expired_validity_medium: boolean;
  constraints: FeasibilityMachineRule[];
}
export interface FeasibilityReadResult {
  settings: FeasibilitySettingsInput;
  saved: boolean;
  defaults: FeasibilitySettingsInput;
  updatedAt: string | null;
  updatedBy: string | null;
}
