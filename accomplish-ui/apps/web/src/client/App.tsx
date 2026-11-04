import { lazy, Suspense, useEffect, useState, useCallback, useMemo, useRef, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useOutlet, useLocation, useNavigate } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { getAccomplish, type RfqSkillProgressEvent, type RfqProjectTracking, type RfqSkillHistoryEntry, type RoutingProfileSkill } from './lib/accomplish';
import { backendUrl, RFQ_UPLOAD_URL, PYTHON_BRIDGE_URL } from './config/endpoints';
import { authFetch } from './lib/apiAuth';
import { logger } from './lib/logger';
import { springs, variants } from './lib/animations';
import { getSession, clearSession } from './lib/session';
import { Avatar, AvatarFallback } from './components/ui/avatar';
import { ThemeToggle } from './components/ui/ThemeToggle';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from './components/ui/dropdown-menu';
import type { ProviderId } from '@accomplish_ai/agent-core/common';
import { OAuthProviderId } from '@accomplish_ai/agent-core/common';

// Components
// import Sidebar from './components/layout/Sidebar';
// import { SidebarFallback } from './components/layout/SidebarFallback';
import { StageExecutionOutput } from './components/execution/StageExecutionOutput';
import { SupersetDashboardPanel } from './components/execution/SupersetDashboardPanel';
import { TaskLauncher } from './components/TaskLauncher';
import { AuthErrorToast } from './components/AuthErrorToast';
import { DaemonConnectionToast } from './components/DaemonConnectionToast';
import { useTaskStore } from './stores/taskStore';
// import { getDaemonClient } from './daemon-bootstrap';
import {
  SpinnerGap,
  Warning,
  CloudArrowUp,
  Scan,
  Tag,
  Paperclip,
  Briefcase,
  ShieldWarning,
  Stack,
  Calculator,
  ClipboardText,
  CheckCircle,
  ChartLineUp,
  CaretLeft,
  CaretRight,
  LockSimple,
  Gear,
  SignOut,
  MagnifyingGlass,
  Pulse,
  DownloadSimple,
} from '@phosphor-icons/react';
import { RfqIntakeUploadModal } from './components/rfq/RfqIntakeUploadModal';
import { RfqErpQuoteWinUploadModal } from './components/rfq/RfqErpQuoteWinUploadModal';
import { RfqIntakeProgressPanel, initialIntakeProgress, type IntakeProgressState } from './components/rfq/RfqIntakeProgressPanel';
import { RfqVersionSelectModal } from './components/rfq/RfqVersionSelectModal';
import type { RfqFileVersion } from './components/rfq/RfqVersionSelectModal';
import { RfqExecutionCard } from './components/rfq/RfqExecutionCard';
import { RfqProgressTimeline } from './components/rfq/RfqProgressTimeline';
import { RfqProvider } from './contexts/RfqContext';
// import { AgentActivityStrip } from './components/execution/AgentActivityStrip';
import { AdditionalCostingSheetsModal } from './components/costing-sheets/AdditionalCostingSheetsModal';
// import { ErrorBoundary } from './components/ui/ErrorBoundary';

const SettingsDialog = lazy(() => import('./components/layout/SettingsDialog'));

type AppStatus = 'loading' | 'ready' | 'error';

// Full 9-stage RFQ pipeline shown in Column 1 and the Column 3 badge.
// `mainHeading` is the short action phrase shown as the card's primary title;
// `name` is the formal stage name shown underneath as the secondary heading.
// `color` matches the accent already used for this stage's Column 3 log text, so the
// two columns read as one connected system rather than two independent palettes.
// Each stage's `subSkills` back the Left Pane accordion: 'createRfq' opens the
// inline RfqExecutionCard, 'ingest' re-runs the existing version-check/upload
// flow, 'jump' just navigates to that stage (the macro header used to do this
// directly; it now only expands/collapses), and 'info' is a non-interactive
// line describing an automatic pipeline step (e.g. virus scanning).
const WORKFLOW_STAGES = [
  {
    id: 'intake', mainHeading: 'Upload file', name: 'Intake & Normalization', icon: CloudArrowUp, color: 'emerald', tag: 'INTAKE',
    subSkills: [
      { label: 'Create RFQ', action: 'createRfq' },
      { label: 'Scan for virus', action: 'info' },
      { label: 'Ingest BOM and Volume file', action: 'ingest' },
    ],
  },
  // No longer comingSoon -- gerber_integration__extract_features (RFQ_Flow's
  // optional Gerber ZIP feature extraction) is now a real, registered skill
  // at macro_category=2, the slot this stage was always reserved for.
  { id: 'extraction', mainHeading: 'Extract features', name: 'Feature Extraction', icon: Scan, color: 'blue', tag: 'EXTRACT', subSkills: [] },
  {
    id: 'pricing', mainHeading: 'Get online pricing', name: 'Distributor Pricing', icon: Tag, color: 'amber', tag: 'PRICE',
    subSkills: [{ label: 'Fetch Prices', action: 'jump' }],
  },
  // No longer comingSoon -- Standard_BOM_Flow runs enrich_erp and enrich_costing_sheet
  // (macro_category 4), so this stage has real backend progress to show.
  { id: 'erpDataSync', mainHeading: 'ERP & Quoting tools', name: 'ERP & QuoteWin Data Sync', icon: Briefcase, color: 'cyan', tag: 'SYNC', subSkills: [] },
  { id: 'risk', mainHeading: 'Analyze feasibility & Risks', name: 'Feasibility & Risk Assessment', icon: ShieldWarning, color: 'purple', tag: 'RISK', comingSoon: true, subSkills: [] },
  {
    id: 'pricingConsolidation', mainHeading: 'Consolidate Pricing Sources', name: 'Pricing Source Consolidation & Validation', icon: Stack, color: 'indigo', tag: 'VALIDATE',
    subSkills: [{ label: 'Detect alternates', action: 'jump' }],
  },
  {
    id: 'priceDecision', mainHeading: 'Finalize price', name: 'Price Decision & Costed BOM Build', icon: Calculator, color: 'rose', tag: 'DECISION',
    subSkills: [
      { label: 'Apply alternates', action: 'jump' },
      { label: 'Export Consolidated CBOM', action: 'jump' },
    ],
  },
  {
    id: 'quoteReadiness', mainHeading: 'Quote Readiness', name: 'Quote Readiness Package', icon: ClipboardText, color: 'lime', tag: 'READY',
    subSkills: [{ label: 'Export Quote', action: 'jump' }],
  },
  { id: 'reportingAnalytics', mainHeading: 'Reports & Analytics', name: 'Post-Quote Reporting & Analytics', icon: ChartLineUp, color: 'teal', tag: 'REPORT', subSkills: [] },
] as const;

export type WorkflowStageId = (typeof WORKFLOW_STAGES)[number]['id'];
type StageColor = (typeof WORKFLOW_STAGES)[number]['color'];

// Explicit backend macro_category (1-indexed) → stage id mapping for SSE-driven
// progress, kept independent of WORKFLOW_STAGES' array order. 0 = STAGED_INTAKE
// per the Python backend's rfq_process_tracking convention — same as 'intake'.
const MACRO_CATEGORY_TO_STAGE: Record<number, WorkflowStageId> = {
  0: 'intake',
  1: 'intake',
  2: 'extraction',
  3: 'pricing',
  4: 'erpDataSync',
  5: 'risk',
  6: 'pricingConsolidation',
  7: 'priceDecision',
  8: 'quoteReadiness',
  9: 'reportingAnalytics',
};

// Mirrors GET /api/bom/export-status/{rfq_id}'s response shape 1:1 (see
// duck_db_api.py's get_export_status) -- each field is independently null
// ("this artifact doesn't exist") or populated, so the Quote Readiness panel
// can render up to three distinct download buttons instead of guessing from
// stage alone whether a real file is on disk.
interface ExportArtifact { filename: string; generatedAt: string }
interface ExportStatus {
  cbom: ExportArtifact | null;
  consolidatedBom: ExportArtifact | null;
  quoteSummary: ExportArtifact | null;
}

// Walks forward from `fromId` to the next non-comingSoon stage — greyed-out
// wizards are never a valid landing spot, whether reached via SSE skill-progress
// or via the resume-on-Enter flow. Falls back to `fromId` if nothing enabled is
// found ahead (shouldn't happen in practice since the last stage is always live).
function getNextEnabledStage(fromId: WorkflowStageId): WorkflowStageId {
  const startIdx = WORKFLOW_STAGES.findIndex((s) => s.id === fromId);
  if (startIdx === -1) { return fromId; }
  for (let i = startIdx; i < WORKFLOW_STAGES.length; i++) {
    const stage = WORKFLOW_STAGES[i];
    if (!('comingSoon' in stage && stage.comingSoon)) { return stage.id; }
  }
  return fromId;
}

// The HITL UI treatments StageExecutionOutput can render, plus two silent
// modes that never reach hitlContext/StageExecutionOutput:
// - 'ignore': the pipeline is unblocked automatically (auto-approved).
// - 'awaitUploads': the OPPOSITE of auto-resolve — no popup, no layout
//   change, but the HITL is deliberately left UNRESOLVED. Used for the
//   intake stage: standardize_scrub_bom halts the pipeline (hitl=1) right
//   after BOM standardization so the user can upload QuoteWin/Costing Sheet;
//   RfqErpQuoteWinUploadModal resumes the run itself (GET /api/dify/start)
//   once both uploads succeed, so nothing here should auto-clear it first.
// 'pricingSources' backs a separate, unrelated supplier/alternate-selection
// feature (left as-is). 'rfqBomPreview' is RFQ_Flow's own stage-7 review —
// distinct from 'cbomPreview' because RFQ_Flow never populates cbom_db.cbom
// (Standard_BOM_Flow's multi-source-reconciled schema); it previews
// processed_bom_items instead, via duck_db_api.py's /api/bom/rfq-preview.
type HitlMode = 'ignore' | 'awaitUploads' | 'yesNo' | 'preview' | 'alternates' | 'pricingSources' | 'cbomPreview' | 'priceSourceReview' | 'rfqBomPreview' | 'gerberPreview';
type HitlDisplayMode = Exclude<HitlMode, 'ignore' | 'awaitUploads'>;

// Business mapping: which HITL mode a stage's HITL requests use, keyed by
// WorkflowStageId (resolved from the RFQ's live rfq_process_stage). Any stage
// not listed here falls back to the incoming hitl:request event's own legacy
// `type` field via legacyHitlTypeToMode below.
//
// pricingConsolidation and priceDecision below are repurposed specifically
// for RFQ_Flow (this project's only active pipeline through this UI) —
// pricingConsolidation previously backed Standard_BOM_Flow's
// resolve_final_selection HITL ('priceSourceReview'); priceDecision's
// 'cbomPreview' mapping was never actually exercised (no skill was ever
// registered at macro_category=7). Both stages become live only for
// RFQ_Flow's rfq_ids, resolved by the daemon's rfq.getProcessStage.
const STAGE_TO_HITL_MODE: Partial<Record<WorkflowStageId, HitlMode>> = {
  intake: 'awaitUploads',
  // RFQ_Flow's optional gerber_integration__extract_features HITL gate --
  // macro_category=2 ('extraction') was already reserved for exactly this
  // in MACRO_CATEGORY_TO_STAGE/WORKFLOW_STAGES, just never had a real skill
  // registered against it until now.
  extraction: 'gerberPreview',
  // RFQ_Flow's distributor__detect_alternates HITL gate -- same
  // suppliers[]-per-candidate AG Grid StageExecutionOutput.tsx already
  // renders for 'alternates', backed by duck_db_api.py's
  // /api/bom/alternatives/{rfqId} (not hitl_router.py).
  pricingConsolidation: 'alternates',
  // RFQ_Flow's distributor__apply_alternatives HITL gate -- review the
  // finalized, deduplicated BOM before distributor__export_enriched_bom runs.
  priceDecision: 'rfqBomPreview',
};

// Legacy fallback for stages not yet covered by STAGE_TO_HITL_MODE — preserves
// today's behavior (preview/alternates AG Grids), with 'approval' upgraded to
// the new real yesNo confirmation UI instead of the old static placeholder text.
function legacyHitlTypeToMode(type: string | undefined): HitlDisplayMode {
  if (type === 'preview') { return 'preview'; }
  if (type === 'alternates') { return 'alternates'; }
  return 'yesNo';
}

// Same Python RFQ-processing service the upload modals already call.
const RFQ_UPLOAD = RFQ_UPLOAD_URL;
// duck_db_api.py — same bridge StageExecutionOutput.tsx already uses for cbomPreview.
const PYTHON_BRIDGE = PYTHON_BRIDGE_URL;

// Tailwind needs literal class names — this lookup keeps every class string static so
// the JIT compiler picks them up, instead of building them with template interpolation.
const STAGE_COLOR_CLASSES: Record<StageColor, { border: string; borderLeft: string; icon: string; tagBorder: string; tagText: string }> = {
  emerald: { border: 'border-emerald-400/30', borderLeft: 'border-l-emerald-400', icon: 'text-emerald-400', tagBorder: 'border-emerald-400/40', tagText: 'text-emerald-400' },
  blue: { border: 'border-blue-400/30', borderLeft: 'border-l-blue-400', icon: 'text-blue-400', tagBorder: 'border-blue-400/40', tagText: 'text-blue-400' },
  amber: { border: 'border-amber-400/30', borderLeft: 'border-l-amber-400', icon: 'text-amber-400', tagBorder: 'border-amber-400/40', tagText: 'text-amber-400' },
  cyan: { border: 'border-cyan-400/30', borderLeft: 'border-l-cyan-400', icon: 'text-cyan-400', tagBorder: 'border-cyan-400/40', tagText: 'text-cyan-400' },
  purple: { border: 'border-purple-400/30', borderLeft: 'border-l-purple-400', icon: 'text-purple-400', tagBorder: 'border-purple-400/40', tagText: 'text-purple-400' },
  indigo: { border: 'border-indigo-400/30', borderLeft: 'border-l-indigo-400', icon: 'text-indigo-400', tagBorder: 'border-indigo-400/40', tagText: 'text-indigo-400' },
  rose: { border: 'border-rose-400/30', borderLeft: 'border-l-rose-400', icon: 'text-rose-400', tagBorder: 'border-rose-400/40', tagText: 'text-rose-400' },
  lime: { border: 'border-lime-400/30', borderLeft: 'border-l-lime-400', icon: 'text-lime-400', tagBorder: 'border-lime-400/40', tagText: 'text-lime-400' },
  teal: { border: 'border-teal-400/30', borderLeft: 'border-l-teal-400', icon: 'text-teal-400', tagBorder: 'border-teal-400/40', tagText: 'text-teal-400' },
};

/**
 * Freezes the outlet so exit animations can complete before the new outlet renders.
 */
function AnimatedOutlet() {
  // Lazy routes resolve after the first render; do not freeze the initial null outlet.
  return useOutlet();
}

/**
 * Wraps the outlet with AnimatePresence + motion for page transitions.
 */
function AnimatedOutletWrapper() {
  const location = useLocation();

  // Analytics: track page views on route changes
  useEffect(() => {
    try {
      getAccomplish()
        .analytics?.trackPageView(location.pathname)
        .catch(() => { });
    } catch {
      /* analytics unavailable */
    }
  }, [location.pathname]);

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname}
        className="h-full"
        initial="initial"
        animate="animate"
        exit="exit"
        variants={variants.fadeUp}
        transition={springs.gentle}
      >
        <AnimatedOutlet />
      </motion.div>
    </AnimatePresence>
  );
}

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');
}

export function App() {
  const { t } = useTranslation('errors');
  const [status, setStatus] = useState<AppStatus>('loading');
  const [errorMessage, _setErrorMessage] = useState<string | null>(null);
  const [authSettingsOpen, setAuthSettingsOpen] = useState(false);
  const [authSettingsTab, setAuthSettingsTab] = useState<
    'providers' | 'skills' | 'general' | 'about'
  >('providers');
  const [authSettingsProvider, setAuthSettingsProvider] = useState<ProviderId | undefined>(
    undefined,
  );

  // Local tracking state for workflow stages canvas rendering
  const [currentWorkflowStage, setCurrentWorkflowStage] = useState<WorkflowStageId>('intake');
  // Furthest stage this RFQ has ever reached -- tracked separately from
  // currentWorkflowStage so that navigating BACK to review an earlier
  // completed stage doesn't re-lock the stages ahead of it. Only goToStage()
  // below should ever move currentWorkflowStage; it keeps this in sync.
  // Read binding is unused now that per-stage status comes from getStageStatus()
  // (see below) rather than idx < maxReachedStageIdx -- the setter below still
  // tracks progress via goToStage, left untouched.
  const [_maxReachedStageIdx, setMaxReachedStageIdx] = useState(0);
  const goToStage = useCallback((stageId: WorkflowStageId, opts?: { reset?: boolean }) => {
    const idx = WORKFLOW_STAGES.findIndex((s) => s.id === stageId);
    setCurrentWorkflowStage(stageId);
    setMaxReachedStageIdx((prev) => (opts?.reset ? idx : Math.max(prev, idx)));
  }, []);
  // The 8 routing-profile skill toggles (Settings -> Skills), used to derive
  // per-stage "fully disabled by toggle" below. No live push exists for a
  // toggle change (see Settings' own routing-profile panel) -- re-fetching
  // on mount and whenever the Settings dialog transitions closed is a cheap,
  // pragmatic substitute for true live cross-tab updates.
  const [routingProfileSkills, setRoutingProfileSkills] = useState<RoutingProfileSkill[]>([]);
  useEffect(() => {
    let isCurrent = true;
    getAccomplish().rfqGetRoutingProfileSkills()
      .then(({ skills }) => { if (isCurrent) { setRoutingProfileSkills(skills); } })
      .catch((err) => { logger.error('Failed to load routing profile skills', { err }); });
    return () => { isCurrent = false; };
  }, [authSettingsOpen]);
  const [intakeModalOpen, setIntakeModalOpen] = useState(false);
  const [erpSyncModalOpen, setErpSyncModalOpen] = useState(false);
  const [versionSelectOpen, setVersionSelectOpen] = useState(false);
  const [costingSheetsOpen, setCostingSheetsOpen] = useState(false);
  const [intakeProgress, setIntakeProgress] = useState<IntakeProgressState>(initialIntakeProgress);
  const [rfqVersions, setRfqVersions] = useState<RfqFileVersion[]>([]);
  // null = not checked yet for this RFQ (or no RFQ loaded); once checked, each
  // of the three fields is independently null/populated -- see resumeRfq.
  const [exportStatus, setExportStatus] = useState<ExportStatus | null>(null);

  // Persisted across reloads -- see resumeRfq/the mount-time restore effect
  // below, which re-fetches this RFQ's live state from the DB (process stage
  // + skill history) rather than trusting any stale client-side snapshot.
  const ACTIVE_RFQ_ID_KEY = 'srim.activeRfqId';
  const [customRfqId, setCustomRfqIdRaw] = useState<string>(() => {
    try { return localStorage.getItem(ACTIVE_RFQ_ID_KEY) ?? ''; } catch { return ''; }
  });
  const setCustomRfqId = useCallback((value: string) => {
    setCustomRfqIdRaw(value);
    try { localStorage.setItem(ACTIVE_RFQ_ID_KEY, value); } catch { /* ignore */ }
  }, []);
  // Distinct from customRfqId (which updates on every keystroke of the RFQ-ID
  // search box) -- this only changes at the discrete moments the user actually
  // commits to a different RFQ (Enter, clicking a search result, or creating a
  // new RFQ), matching resumeRfq's own call sites. Exists solely to drive the
  // SSE effect below: reconnecting on every keystroke would be wasteful/
  // disruptive, but never reconnecting at all means the daemon's per-rfqId
  // scoping for the 'rfq:skill-progress' channel (see sendToRfqNamed in
  // browser-api-server.ts) would go stale the first time a user switches RFQs
  // without a page reload, silently cutting off live progress updates for the
  // new RFQ. Initialized from customRfqId's own already-loaded (localStorage)
  // value so the very first EventSource connection is correctly scoped too.
  const [activeRfqId, setActiveRfqId] = useState<string>(customRfqId);
  // The SSE effect below subscribes once with an empty dep array (it must
  // not re-open the connection on every keystroke) -- its handler closure
  // would otherwise only ever see customRfqId's mount-time value ('').
  // Keep this ref in sync so that closure can read the live value instead.
  const customRfqIdRef = useRef(customRfqId);
  useEffect(() => {
    customRfqIdRef.current = customRfqId;
  }, [customRfqId]);
  const [rfqValidationMessage, setRfqValidationMessage] = useState('');
  const [rfqCreatePaneOpen, setRfqCreatePaneOpen] = useState(false);
  const [rfqSearchResults, setRfqSearchResults] = useState<RfqProjectTracking[]>([]);
  const [rfqSearchLoading, setRfqSearchLoading] = useState(false);
  // Controls dropdown *visibility* independent of customRfqId's value --
  // typing opens it, explicitly selecting a result closes it. Without this
  // separation, selecting a result (which sets customRfqId, re-triggering the
  // debounced search effect below) would re-populate and re-show the dropdown
  // a moment later even though the user already made their choice.
  const [showRfqDropdown, setShowRfqDropdown] = useState(false);
  // Append-only progress log for the right panel -- seeded from DB via
  // rfq.getSkillHistory in resumeRfq, kept current by live SSE events.
  const [rfqProgressLog, setRfqProgressLog] = useState<RfqSkillHistoryEntry[]>([]);
  const [paneRatios, setPaneRatios] = useState<[number, number, number]>([30, 40, 30]);
  const splitWrapperRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<null | {
    side: 'control' | 'output';
    startX: number;
    startRatios: [number, number, number];
  }>(null);


  // Checks whether a real, downloadable export already exists for this RFQ --
  // called from resumeRfq below so every reopen (not just the live moment
  // right after export_reports finishes) can show the right download
  // button(s). Deliberately independent of StageExecutionOutput.tsx's own
  // exportInfo, which answers a different question ("did the export I just
  // triggered succeed") on a different timeline -- see the Quote Readiness
  // export plan for why these two aren't shared.
  const refreshExportStatus = useCallback(async (rfqId: string) => {
    try {
      const res = await authFetch(`${PYTHON_BRIDGE}/api/bom/export-status/${encodeURIComponent(rfqId)}`, rfqId);
      if (!res.ok) { setExportStatus(null); return; }
      const data = await res.json();
      setExportStatus({ cbom: data.cbom, consolidatedBom: data.consolidatedBom, quoteSummary: data.quoteSummary });
    } catch (err) {
      logger.error('Failed to fetch export status', { err });
      setExportStatus(null);
    }
  }, []);

  // Resumes an existing RFQ: jump the UI to its live process stage, restore
  // the right panel's progress log from DB (rfq.getSkillHistory -- this is
  // what makes it survive a hard refresh, not any client-side cache), then
  // call the backend's resume endpoint (no file needed — the workflow itself
  // handles resuming from where it left off). Shared by pressing Enter on the
  // RFQ-ID textbox, clicking a live search result, and the mount-time restore
  // effect below.
  const resumeRfq = useCallback(async (rfqId: string) => {
    try {
      const accomplish = getAccomplish();
      setExportStatus(null); // clear any previous RFQ's stale artifacts before this one resolves
      const { exists } = await accomplish.checkRfqExists({ rfqId });
      if (!exists) { return; }

      const { history } = await accomplish.rfqGetSkillHistory({ rfqId });
      setRfqProgressLog(history);

      const { stage } = await accomplish.rfqGetProcessStage({ rfqId });
      if (typeof stage === 'number') {
        const mapped = MACRO_CATEGORY_TO_STAGE[stage];
        if (mapped) {
          goToStage(getNextEnabledStage(mapped));
          // >= (not ===) also covers RFQs that already locally advanced to
          // 'reportingAnalytics' in an earlier session -- goToStage has no
          // forward-only guard, so that's a real reachable state on reopen.
          if (stage >= 8) { void refreshExportStatus(rfqId); }
        }
        authFetch(`${RFQ_UPLOAD}/api/dify/start/${encodeURIComponent(rfqId)}`, rfqId).catch((err) => {
          logger.error('Failed to resume workflow via /api/dify/start', { err });
        });
      } else {
        // Exists (e.g. created via Project Tracking's Create RFQ flow) but
        // has no rfq_process_tracking row yet -- nothing has been uploaded,
        // so "where it left off" is the intake stage. Nothing to resume via
        // /api/dify/start since no run has ever started for this RFQ.
        goToStage('intake', { reset: true });
      }
    } catch (err) {
      logger.error('Resume RFQ lookup failed', { err });
    }
  }, [goToStage, refreshExportStatus]);

  // Restores the active RFQ's state on load (including a hard refresh) --
  // customRfqId's initial value already came from localStorage above, this
  // just re-fetches everything else about it (stage, progress log) from the
  // DB rather than trusting any stale client snapshot.
  useEffect(() => {
    if (customRfqIdRef.current.trim()) { void resumeRfq(customRfqIdRef.current.trim()); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRfqIdEnter = async (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') { return; }
    const rfqId = customRfqId.trim();
    if (!rfqId) { return; }
    setShowRfqDropdown(false);
    setActiveRfqId(rfqId);
    await resumeRfq(rfqId);
  };

  const handleRfqSearchResultClick = useCallback((rfqId: string) => {
    setCustomRfqId(rfqId);
    setShowRfqDropdown(false);
    setRfqSearchResults([]);
    setActiveRfqId(rfqId);
    void resumeRfq(rfqId);
  }, [resumeRfq, setCustomRfqId]);

  // "Ingest BOM and Volume file" sub-skill -- same version-check flow the
  // "Upload file" macro header used to run directly on click, now moved here
  // since the header itself only expands/collapses the accordion.
  const handleIngestClick = useCallback(() => {
    if (!customRfqId.trim()) {
      setIntakeProgress(initialIntakeProgress);
      setIntakeModalOpen(true);
      return;
    }
    void (async () => {
      try {
        const data = await getAccomplish().rfqGetFileVersions({ rfqId: customRfqId.trim() });
        if (data.versions.length > 0) {
          setRfqVersions(data.versions);
          setVersionSelectOpen(true);
        } else {
          setIntakeProgress(initialIntakeProgress);
          setIntakeModalOpen(true);
        }
      } catch {
        setIntakeProgress(initialIntakeProgress);
        setIntakeModalOpen(true);
      }
    })();
  }, [customRfqId]);

  const handleSubSkillClick = useCallback((stageId: WorkflowStageId, action: string) => {
    if (action === 'info') { return; }
    goToStage(stageId);
    if (action === 'createRfq') { setRfqCreatePaneOpen(true); return; }
    if (action === 'ingest') { handleIngestClick(); return; }
    // 'jump' -- goToStage above already moved the workspace to this stage.
  }, [goToStage, handleIngestClick]);

  // Live search-as-you-type across RFQ ID / customer / project, plus the
  // exists/not-found validation message -- one shared 250ms-debounced,
  // cancelable effect for both. These used to be two separate un-coordinated
  // lookups (an un-debounced checkRfqExists on every keystroke racing the
  // debounced search), which could let a slow, stale keystroke's response
  // land after a newer one and show "not found" for an RFQ that had in fact
  // already resolved as existing. The same textbox that drives customRfqId
  // (search, resume-on-Enter, and every other place customRfqId is read) is
  // now multipurpose -- there's no separate search-only field anymore.
  useEffect(() => {
    const query = customRfqId.trim();
    if (!query) {
      setRfqSearchResults([]);
      setRfqSearchLoading(false);
      setRfqValidationMessage('');
      setActiveRfqId('');
      return;
    }
    let cancelled = false;
    setRfqSearchLoading(true);
    const timeout = setTimeout(() => {
      // Fallback sync for activeRfqId (see its own declaration comment):
      // handleRfqIdEnter/handleRfqSearchResultClick/RfqExecutionCard's onCreated
      // already set it immediately at their own explicit commit points, but a user
      // can also type a brand-new RFQ ID and act on it WITHOUT ever pressing
      // Enter or picking a search result -- e.g. typing an ID then directly
      // clicking the "Intake" stage to open RfqIntakeUploadModal. Without
      // this, activeRfqId (and therefore the SSE subscription) would never
      // update for that flow, silently dropping every skill-progress/HITL
      // event for the new RFQ. 250ms after typing settles is a safe point to
      // treat the typed value as "the one being worked on" -- short enough
      // that it's already committed by the time any button click follows.
      setActiveRfqId(query);
      Promise.all([
        getAccomplish().searchRfqs({ query }),
        getAccomplish().checkRfqExists({ rfqId: query }),
      ])
        .then(([{ rfqs }, { exists }]) => {
          if (cancelled) { return; }
          setRfqSearchResults(rfqs);
          setRfqValidationMessage(exists ? 'RFQ ID already exists' : 'RFQ ID not found');
        })
        .catch((err: unknown) => {
          logger.error('RFQ search/validation failed', { err });
          if (!cancelled) { setRfqValidationMessage('Unable to validate RFQ ID'); }
        })
        .finally(() => { if (!cancelled) { setRfqSearchLoading(false); } });
    }, 250);
    return () => { cancelled = true; clearTimeout(timeout); };
  }, [customRfqId]);


  const [sseConnection, setSseConnection] = useState<EventSource | null>(null);
  const [hitlActive, setHitlActive] = useState<boolean>(false);

  const [hitlContext, setHitlContext] = useState<HitlContext | null>(null);
  const [sharedRowData, setSharedRowData] = useState<Record<string, unknown>[]>([]);
  // Manual override for the HITL collapsed layout — lets the user toggle back to the
  // full 3-panel view (and re-collapse) without waiting for the backend's hitl:clear.
  // Independent of hitlContext, which keeps driving Column 3's content regardless.
  const [hitlLayoutExpanded, setHitlLayoutExpanded] = useState(false);
  // Same idea for stage 9's auto-collapsed sidebar -- without this, collapsing Column 1
  // on that stage would permanently hide the only way to navigate to a different stage
  // (a real lockout, not just a cosmetic issue).
  const [reportingAnalyticsLayoutExpanded, setReportingAnalyticsLayoutExpanded] = useState(false);

  interface HitlContext {
    rfqId: string;
    stage: string;
    type: HitlDisplayMode;
    message?: string;
  }

  // Routes StageExecutionOutput's `hitl:submit-decision` request through the real
  // daemon RPC (rfq/hitl bridge) instead of the previous console.log-only stub —
  // this is what actually clears the HITL flag and resumes the backend pipeline.
  const realRpcClient = useMemo(() => ({
    request: async (channel: string, args: unknown[]) => {
      if (channel === 'hitl:submit-decision') {
        const [rfqId, approved] = args as [string, boolean];
        return getAccomplish().hitlSubmitDecision(rfqId, approved);
      }
      logger.warn('Unhandled RPC channel from StageExecutionOutput', { channel, args });
      return null;
    }
  }), []);

  // Backend-driven skill/stage progress (rfq:skill-progress). Declared here,
  // above the SSE effect below, since that effect's handleGlobalInterceptStream
  // now dispatches to this on a matching payload.event -- see that effect's
  // own comment for why this event arrives on THIS connection (App.tsx's own,
  // rfqId-scoped one) rather than accomplish-backend.ts's separate, unscoped
  // one. The backend is the sole source of truth: this handler never computes
  // the next stage/skill, it only reflects whatever the event reports.
  const applyRfqSkillProgress = useCallback((event: RfqSkillProgressEvent) => {
    if (!event?.skillCode || typeof event.macroCategory !== 'number') {
      logger.warn('Ignoring malformed rfq:skill-progress event', { event });
      return;
    }
    // Always-correct layer, same reasoning as the HITL branches below: the
    // server-side rfqId scoping on this connection reflects activeRfqId at
    // whichever moment it last reconnected -- this catches anything that
    // could otherwise fall out of sync (e.g. a stale in-flight event landing
    // right as the user switches RFQs).
    if (event.rfqId !== customRfqIdRef.current.trim()) { return; }

    // Append a new row for a skill we haven't seen yet, or update the
    // existing row in place (e.g. running -> completed) -- never replace the
    // whole log with just this one event, so earlier skills' history stays
    // visible instead of being overwritten by whichever skill just fired.
    setRfqProgressLog((prev) => {
      const idx = prev.findIndex((e) => e.skillCode === event.skillCode);
      const entry: RfqSkillHistoryEntry = {
        skillCode: event.skillCode,
        skillName: event.skillName ?? event.skillCode,
        macroCategory: event.macroCategory,
        stepStatus: event.stepStatus ?? 'running',
        error: event.error,
      };
      if (idx === -1) { return [...prev, entry]; }
      const next = [...prev];
      next[idx] = entry;
      return next;
    });

    // A failed step never advances the pipeline (fastapi_router.py's
    // /tool/execute leaves rfq_process_stage untouched on failure) -- the
    // wizard must not jump to the next stage as if it had. The failure is
    // still recorded in the log above so it's visible in place.
    if (event.stepStatus === 'failed') { return; }

    const mappedStage = MACRO_CATEGORY_TO_STAGE[event.macroCategory];
    // Reaching any stage past intake means the BOM step is over; the intake
    // panel must stop showing "Standardizing BOM" (it only learns this here).
    if (mappedStage && mappedStage !== 'intake') {
      setIntakeProgress((prev) => (prev.bomStatus === 'done' ? prev : { ...prev, bomStatus: 'done' }));
    }
    if (mappedStage) {
      // The "reports are ready" banner (below) renders as soon as this
      // stage is reached, but its download buttons depend on exportStatus,
      // which otherwise only gets (re-)checked once, inside resumeRfq --
      // never while a session is already open and watching a run complete
      // live. Re-check here, on the same live signal that drives the
      // banner, so both go stale/fresh together instead of racing.
      // Standard_BOM_Flow's export_reports is macro 9 (reportingAnalytics), so both stages must refresh.
      const exportStage = mappedStage === 'quoteReadiness' || mappedStage === 'reportingAnalytics';
      if (exportStage && event.stepStatus === 'completed') {
        void refreshExportStatus(event.rfqId);
      }
      goToStage(getNextEnabledStage(mappedStage));
    } else {
      logger.warn('Unknown macroCategory in rfq:skill-progress event', {
        macroCategory: event.macroCategory,
      });
    }
  }, [goToStage, refreshExportStatus]);

  // ─── ROOT LEVEL SSE CHANNEL INITIALIZATION LOOP ───
  useEffect(() => {
    // backendUrl() resolves against window.location.hostname in dev, not a
    // hardcoded loopback -- required so this connects correctly when the app
    // is opened from another device on the LAN, not just the daemon's own host.
    // Carries the tab's current rfqId (if any) so the daemon can scope
    // HITL/rfq:skill-progress broadcasts to this connection (see sendToRfq
    // in browser-api-server.ts -- accomplish-backend.ts's own separate SSE
    // connection is a module-level singleton that never carries rfqId, so
    // it can't receive RFQ-scoped events; both channels are delivered here
    // instead). Depends on activeRfqId (set only at explicit RFQ-switch
    // commit points, never on every keystroke -- see its own declaration
    // above), so this effect reconnects with the new rfqId exactly when the
    // user actually switches RFQs, not while typing. The handlers below
    // still separately re-check customRfqIdRef as an always-correct layer
    // in case anything ever falls out of sync between an event's arrival
    // and this effect's reconnect.
    const eventsUrl = activeRfqId
      ? `/events?rfqId=${encodeURIComponent(activeRfqId)}`
      : '/events';
    const sse = new EventSource(backendUrl(eventsUrl));

    const handleGlobalInterceptStream = (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data);
        if (payload.event === 'hitl:request') {
          console.log("⚠️ HITL Intercept detected! Hydrating data array:", payload.rowData);

          // Resolve which HITL mode to use from the RFQ's live process stage
          // rather than trusting the event's own `type` field — falls back to
          // the legacy type-based mapping for any stage not in STAGE_TO_HITL_MODE.
          void (async () => {
            let mode: HitlMode = legacyHitlTypeToMode(payload.type);
            try {
              const { stage } = await getAccomplish().rfqGetProcessStage({ rfqId: payload.rfqId });
              if (typeof stage === 'number') {
                const stageId = MACRO_CATEGORY_TO_STAGE[stage];
                const mapped = stageId && STAGE_TO_HITL_MODE[stageId];
                if (mapped) { mode = mapped; }
              }
            } catch (err) {
              logger.warn('Failed to resolve stage-based HITL mode, using legacy type mapping', { err });
            }
            // Standard_BOM_Flow's final-selection gate sends its tool name as `stage`. The stage-number
            // table above is RFQ_Flow's, and it maps that same step (macro 6) to the alternates screen.
            const gateSkill = String(payload.stage ?? '').split('__').pop() ?? '';
            if (gateSkill === 'resolve_final_selection') {
              mode = 'priceSourceReview';
            }

            if (mode === 'ignore') {
              // No popup, no layout change — silently unblock the pipeline.
              getAccomplish().hitlSubmitDecision(payload.rfqId, true).catch((err) => {
                logger.error('Failed to auto-resolve ignored HITL request', { err });
              });
              return;
            }

            if (mode === 'awaitUploads') {
              // Deliberately do nothing — no popup, and no auto-resolve. The
              // pipeline stays halted (hitl_required stays true, skill_index
              // stays at the BOM-standardization skill) until
              // RfqErpQuoteWinUploadModal's own upload success handler calls
              // GET /api/dify/start/{rfqId} to resume it.
              logger.info('Intake HITL received — awaiting QuoteWin/Costing Sheet upload before resuming', { rfqId: payload.rfqId });
              // Only patch the progress panel if this event is actually for
              // the RFQ ID currently shown -- guards against a stale event
              // landing after the user has already typed a different ID.
              // Reads the ref (not the closed-over customRfqId state) since
              // this handler is captured once by an effect with an empty
              // dep array.
              if (payload.rfqId === customRfqIdRef.current.trim()) {
                setIntakeProgress((prev) => ({ ...prev, bomStatus: 'done' }));
              }
              return;
            }

            // CRITICAL: only show the popup in tabs actually viewing this
            // rfqId. Without this check, EVERY connected browser tab (any
            // user, any RFQ) processed every hitl:request unconditionally --
            // the root cause of "User 1's HITL popup appears for all users."
            // Reads the ref (not the closed-over customRfqId state), same
            // reasoning as the awaitUploads branch's own rfqId check above --
            // this handler is captured once by an effect with an empty dep
            // array, so only the ref reflects the tab's live current value.
            if (payload.rfqId !== customRfqIdRef.current.trim()) {
              logger.info('Ignoring hitl:request for a different rfqId than this tab is viewing', {
                eventRfqId: payload.rfqId,
                viewingRfqId: customRfqIdRef.current.trim(),
              });
              return;
            }

            setSharedRowData(payload.rowData || []);
            setHitlLayoutExpanded(false);
            setHitlContext({
              rfqId: payload.rfqId,
              stage: payload.stage,
              type: mode,
              message: payload.message,
            });
          })();
        } else if (payload.event === 'hitl:clear') {
          // Same rfqId guard as hitl:request above -- otherwise User 1
          // resolving their own HITL would also incorrectly clear a
          // genuinely different, still-pending HITL popup showing in
          // another tab/user for a different rfqId.
          if (payload.rfqId !== customRfqIdRef.current.trim()) {
            return;
          }
          setHitlContext(null);
          setSharedRowData([]);
          setHitlLayoutExpanded(false);
        } else if (payload.event === 'rfq:skill-progress') {
          applyRfqSkillProgress(payload);
        }
      } catch (err) {
        console.error("Error reading stream transmission frames:", err);
      }
    };

    sse.addEventListener('message', handleGlobalInterceptStream);
    setSseConnection(sse);

    return () => {
      sse.removeEventListener('message', handleGlobalInterceptStream);
      sse.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRfqId]);
  // ───────────────────────────────────────────────────

  const startPanelDrag = useCallback((side: 'control' | 'output', event: ReactPointerEvent<HTMLButtonElement>) => {
    const wrapper = splitWrapperRef.current;
    if (!wrapper) return;

    event.preventDefault();
    dragStateRef.current = {
      side,
      startX: event.clientX,
      startRatios: paneRatios,
    };

    const handlePointerMove = (moveEvent: PointerEvent) => {
      const drag = dragStateRef.current;
      if (!drag || drag.side !== side) return;
      const usableWidth = wrapper.getBoundingClientRect().width;
      const delta = ((moveEvent.clientX - drag.startX) / usableWidth) * 100;
      const next = [...drag.startRatios] as [number, number, number];

      if (side === 'control') {
        next[0] = Math.min(42, Math.max(22, drag.startRatios[0] + delta));
        next[1] = 100 - next[0] - next[2];
        if (next[1] < 30) {
          next[1] = 30;
          next[0] = 100 - next[1] - next[2];
        }
      } else {
        next[1] = Math.min(48, Math.max(30, drag.startRatios[1] + delta));
        next[2] = 100 - next[0] - next[1];
        if (next[2] < 22) {
          next[2] = 22;
          next[1] = 100 - next[0] - next[2];
        }
      }

      setPaneRatios(next);
    };
    const handlePointerUp = () => {
      dragStateRef.current = null;
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
  }, [paneRatios]);

  // Get store state and actions
  const { openLauncher, authError, clearAuthError } = useTaskStore();


  // Handle re-login from auth error toast
  const handleAuthReLogin = useCallback(() => {
    if (authError) {
      if (authError.providerId === OAuthProviderId.Slack) {
        setAuthSettingsProvider(undefined);
        setAuthSettingsTab('providers');
      } else {
        setAuthSettingsProvider(authError.providerId as ProviderId);
        setAuthSettingsTab('providers');
      }
      setAuthSettingsOpen(true);
    }
  }, [authError]);

  // Handle auth settings dialog close
  const handleAuthSettingsClose = useCallback(
    (open: boolean) => {
      setAuthSettingsOpen(open);
      if (!open) {
        setAuthSettingsTab('providers');
        setAuthSettingsProvider(undefined);
        clearAuthError();
      }
    },
    [clearAuthError],
  );

  const navigate = useNavigate();
  const session = getSession();
  const sessionUser = session?.user ?? { name: 'Guest', email: '' };
  const handleSignOut = useCallback(() => {
    setCustomRfqId('');
    clearSession();
    navigate('/login', { replace: true, state: { loggedOut: true } });
  }, [navigate, setCustomRfqId]);

  // Per-stage status label (Left Pane) -- derived entirely from the existing
  // rfqProgressLog SSE data, no new state or backend calls. A stage is
  // 'failed' if any of its logged skills failed (failures never advance the
  // pipeline -- see applyRfqSkillProgress -- so they stay visible in place),
  // 'running' if it's the live stage AND has real activity, 'completed' if
  // every logged skill for it finished, else 'waiting'.
  const getStageStatus = useCallback((stageId: WorkflowStageId): 'completed' | 'running' | 'waiting' | 'failed' => {
    const stageEntries = rfqProgressLog.filter((entry) => MACRO_CATEGORY_TO_STAGE[entry.macroCategory] === stageId);
    if (stageEntries.some((entry) => entry.stepStatus === 'failed')) { return 'failed'; }
    // Being the "current" stage isn't enough on its own -- intake starts out
    // current before any upload is dispatched, which used to show "Running"
    // with zero real activity. Require either a real backend entry, or (for
    // intake specifically, which has no backend entry until the upload is
    // already in flight) the local upload-dispatch signal.
    const hasStarted = stageEntries.length > 0
      || (stageId === 'intake' && (intakeProgress.bomStatus === 'uploading' || intakeProgress.bomStatus === 'processing'));
    if (stageId === currentWorkflowStage && hasStarted) { return 'running'; }
    if (stageEntries.length > 0 && stageEntries.every((entry) => entry.stepStatus === 'completed')) { return 'completed'; }
    return 'waiting';
  }, [rfqProgressLog, currentWorkflowStage, intakeProgress.bomStatus]);

  // RFQ-level status (header pill) -- same underlying signals rolled up to
  // one badge; only meaningful once an RFQ is actually active.
  // intakeProgress.bomStatus is a real, local signal set directly by
  // RfqExecutionCard's onUploadStart/onUploadSuccess/onUploadError -- unlike
  // rfqProgressLog (which only fills in once the separate Python backend
  // actually emits rfq:skill-progress SSE events), this reflects the upload
  // the moment the user dispatches it, regardless of whether that backend is
  // reachable. Folding intakeProgress.bomStatus === 'error' into 'failed'
  // surfaces a real local upload failure that rfqProgressLog alone can't see.
  const rfqStatus: 'running' | 'completed' | 'failed' =
    rfqProgressLog.some((entry) => entry.stepStatus === 'failed') || intakeProgress.bomStatus === 'error'
      ? 'failed'
      : currentWorkflowStage === 'reportingAnalytics'
        ? 'completed'
        : 'running';

  // Cmd+K keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        openLauncher();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [openLauncher]);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const accomplish = getAccomplish();
        await accomplish.setOnboardingComplete(true);
      } catch (error) {
        logger.error('Failed to initialize app:', error);
      }
      setStatus('ready');
    };

    void checkStatus();
  }, []);

  // Loading state
  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <SpinnerGap className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Error state
  if (status === 'error') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-8">
        <div className="max-w-md text-center">
          <div className="mb-6 flex justify-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
              <Warning className="h-8 w-8 text-destructive" />
            </div>
          </div>
          <h1 className="mb-2 text-xl font-semibold text-foreground">{t('app.unableToStart')}</h1>
          <p className="text-muted-foreground">{errorMessage}</p>
        </div>
      </div>
    );
  }

  // Ready - render canvas view split equally into 3 distinct sections
  // When a HITL intercept is active, Col 1 collapses completely (0 width), Col 2
  // narrows to ~20% of the screen, and Col 3 (the intercept table) takes the rest
  // — paneRatios itself is left untouched so the manual drag layout is restored
  // automatically once hitlContext clears. The user can also manually toggle back to
  // the full 3-panel view (and re-collapse) via hitlLayoutExpanded, independent of
  // hitlContext, which keeps driving Column 3's content regardless of layout state.
  const isHitlCollapsed = !!hitlContext && !hitlLayoutExpanded;
  // Stage 9 (Reports & Analytics) auto-collapses Column 1 the same way a HITL
  // intercept does, freeing its width to Column 3 (the embedded dashboard) -- but,
  // same as HITL, only while `reportingAnalyticsLayoutExpanded` hasn't been manually
  // toggled on. Without that manual override, collapsing the sidebar on this stage
  // would permanently hide the only way to navigate to a different stage.
  const isOnReportingAnalyticsStage = currentWorkflowStage === 'reportingAnalytics';
  const isReportingAnalyticsCollapsed = isOnReportingAnalyticsStage && !reportingAnalyticsLayoutExpanded;
  const isLeftPanelCollapsed = isHitlCollapsed || isReportingAnalyticsCollapsed;
  // Collapsed states narrow column 1 to a fixed icon-only rail (64px) rather than
  // removing it entirely -- step icons stay visible/clickable, only the text labels
  // hide. The resize gutter still collapses to 0px since dragging a fixed rail
  // wouldn't mean anything.
  const gridTemplateColumns = isHitlCollapsed
    ? '64px 0px minmax(0, 20fr) 12px minmax(480px, 80fr)'
    : isReportingAnalyticsCollapsed
      ? `64px 0px minmax(360px, ${paneRatios[1]}fr) 12px minmax(480px, ${paneRatios[0] + paneRatios[2]}fr)`
      : `minmax(280px, ${paneRatios[0]}fr) 12px minmax(360px, ${paneRatios[1]}fr) 12px minmax(280px, ${paneRatios[2]}fr)`;

  return (
    <div
      className="srim-console srim-theme-shell flex flex-col h-screen w-screen overflow-hidden"
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        event.currentTarget.style.setProperty('--pointer-x', `${((event.clientX - rect.left) / rect.width) * 100}%`);
        event.currentTarget.style.setProperty('--pointer-y', `${((event.clientY - rect.top) / rect.height) * 100}%`);
      }}
    >
      {/* Invisible drag region for window dragging (macOS hiddenInset titlebar) */}
      <div className="drag-region fixed top-0 left-0 right-0 h-10 z-50 pointer-events-none" />
      <div className="srim-orbit-field pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
        <motion.div className="srim-orbit srim-orbit-one" animate={{ rotate: 360 }} transition={{ duration: 32, repeat: Infinity, ease: 'linear' }} />
        <motion.div className="srim-orbit srim-orbit-two" animate={{ rotate: -360 }} transition={{ duration: 44, repeat: Infinity, ease: 'linear' }} />
        <motion.div className="srim-signal-dot" animate={{ scale: [0.8, 1.2, 0.8], opacity: [0.35, 0.9, 0.35] }} transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }} />
      </div>

      {/* Manual layout toggle — lets the user get the sidebar/chat back (or re-collapse
          for more space) during an active HITL intercept or while on stage 9, without
          waiting for hitl:clear or navigating away first. Without this, the sidebar
          auto-collapsing on either case would have no way back to itself. */}
      {(hitlContext || isOnReportingAnalyticsStage) && (
        <button
          type="button"
          onClick={() => {
            if (hitlContext) setHitlLayoutExpanded((v) => !v);
            else setReportingAnalyticsLayoutExpanded((v) => !v);
          }}
          className="fixed top-14 left-3 z-40 flex h-8 w-8 items-center justify-center rounded-full border border-primary/40 bg-background/90 text-primary shadow-lg backdrop-blur-sm transition-transform hover:scale-105"
          title={isLeftPanelCollapsed ? 'Restore sidebar & chat panels' : 'Collapse panels for more space'}
        >
          {isLeftPanelCollapsed ? <CaretLeft className="h-4 w-4" /> : <CaretRight className="h-4 w-4" />}
        </button>
      )}

      <RfqIntakeUploadModal
        open={intakeModalOpen}
        rfqId={customRfqId}
        onClose={() => setIntakeModalOpen(false)}
        onUploadStart={(fileName) =>
          setIntakeProgress((prev) => ({ ...prev, bomFileName: fileName, bomStatus: 'uploading', errorMessage: null }))
        }
        onSuccess={(fileName) => {
          setIntakeModalOpen(false);
          goToStage('intake', { reset: true });
          setIntakeProgress((prev) => ({ ...prev, bomFileName: fileName, bomStatus: 'processing' }));
        }}
        onUploadError={(message) =>
          setIntakeProgress((prev) => ({ ...prev, bomStatus: 'error', errorMessage: message }))
        }
      />

      <RfqErpQuoteWinUploadModal
        open={erpSyncModalOpen}
        rfqId={customRfqId}
        onClose={() => setErpSyncModalOpen(false)}
        onUploadStart={(files) =>
          setIntakeProgress((prev) => ({
            ...prev,
            quoteWinFileName: files.quoteWinFileName ?? null,
            costingSheetFileName: files.costingSheetFileName ?? null,
            erpStatus: 'uploading',
            errorMessage: null,
          }))
        }
        onSuccess={(files) => {
          setErpSyncModalOpen(false);
          goToStage('erpDataSync');
          setIntakeProgress((prev) => ({
            ...prev,
            quoteWinFileName: files.quoteWinFileName ?? null,
            costingSheetFileName: files.costingSheetFileName ?? null,
            erpStatus: 'done',
          }));
        }}
        onUploadError={(message) =>
          setIntakeProgress((prev) => ({ ...prev, erpStatus: 'error', errorMessage: message }))
        }
      />

      <RfqVersionSelectModal
        open={versionSelectOpen}
        rfqId={customRfqId}
        versions={rfqVersions}
        onClose={() => setVersionSelectOpen(false)}
        onSelectVersion={async (v) => {
          await getAccomplish().rfqActivateVersion({
            rfqId: customRfqId.trim(),
            version: v.version,
          });
          setVersionSelectOpen(false);
          goToStage('intake', { reset: true });
        }}
        onUploadNew={() => {
          setVersionSelectOpen(false);
          setIntakeProgress(initialIntakeProgress);
          setIntakeModalOpen(true);
        }}
      />

      <AdditionalCostingSheetsModal
        open={costingSheetsOpen}
        onClose={() => setCostingSheetsOpen(false)}
      />

      {/* ─── GLOBAL HEADER ────────────────────────────────────────────────── */}
      <header className="relative z-10 flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-card px-4">
        <div className="flex min-w-0 items-center gap-3">
          {/* Centum logo is white-on-transparent, so it sits on a dark chip to stay visible on the light header. */}
          <span className="inline-flex items-center rounded-md bg-[#1f1f1f] px-3 py-1.5">
            <img src="/assets/centum-logo.png" alt="Centum" className="h-5 w-auto object-contain" />
          </span>
          {/* Only once real processing has actually started -- either rfqProgressLog
              has its first entry (a live SSE skill-progress event or a resumed
              history), or the user has actually dispatched the BOM/Volume upload
              via RfqExecutionCard (intakeProgress.bomStatus leaves 'pending').
              The latter matters because rfqProgressLog alone never fills in when
              the separate Python upload backend isn't reachable -- not merely
              because an RFQ ID exists, e.g. right after "Create RFQ" but before
              any file is uploaded. */}
          {(intakeProgress.bomStatus !== 'pending' || rfqProgressLog.length > 0) && (
            <>
              <span className="h-5 w-px bg-border" aria-hidden="true" />
              <span className="truncate text-sm font-semibold text-foreground">{customRfqId.trim()}</span>
              <span
                className={`pill-base inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${rfqStatus === 'failed' ? 'bg-destructive/10 text-destructive' : 'bg-emerald-500/10 text-emerald-500'
                  }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${rfqStatus === 'failed' ? 'bg-destructive' : 'bg-emerald-500'
                    }`}
                />
                {rfqStatus === 'failed' ? 'Failed' : rfqStatus === 'completed' ? 'Completed' : 'Running'}
              </span>
            </>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <ThemeToggle />
          <button
            type="button"
            title="Settings"
            aria-label="Settings"
            onClick={() => {
              setAuthSettingsTab('general');
              setAuthSettingsOpen(true);
            }}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Gear className="h-4 w-4" />
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className="ml-1" aria-label="Account menu">
                <Avatar className="size-9 ring-2 ring-background shadow-sm">
                  <AvatarFallback className="text-xs font-semibold">{initialsFor(sessionUser.name)}</AvatarFallback>
                </Avatar>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="bottom" align="end" className="w-40">
              <DropdownMenuItem variant="destructive" onClick={handleSignOut}>
                <SignOut />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* ─── CANVAS GRID WRAPPER (Three Columns) ─────────────────────────── */}
      <div
        ref={splitWrapperRef}
        className="srim-pane-grid flex flex-1 min-h-0 w-full"
        style={{ gridTemplateColumns }}
      >
        {/* COLUMN 1: SIDEBAR CONTAINER & WORKFLOW MANAGER */}
        <div className="srim-column-shell relative h-full min-w-0 overflow-hidden">
          <motion.div
            className={`srim-panel srim-panel-left srim-theme-panel relative h-full flex flex-col justify-between py-4 bg-card transition-[padding] duration-300 ${isLeftPanelCollapsed ? 'px-2' : 'px-4'}`}
            style={{ minWidth: 0, width: '100%' }}
          >

            {/* Top Panel: Workflow Sequence Control */}
            <div className="flex-1 min-h-0 flex flex-col justify-start overflow-y-auto">
              {!isLeftPanelCollapsed && (
                <div className="mb-4 border-b border-border pb-4">
                  <h2 className="text-sm font-bold uppercase tracking-wide text-foreground">RFQ Pipeline</h2>
                  <p className="text-xs text-muted-foreground">Track and manage your RFQ workflow</p>
                </div>
              )}

              <div className="mb-3">
                {!isLeftPanelCollapsed && (
                  <div className="mb-2.5 space-y-1">
                    <label htmlFor="rfq-search-textbox" className="sr-only">
                      Search or enter RFQ ID
                    </label>
                    <div className="relative">
                      <MagnifyingGlass className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                      <input
                        id="rfq-search-textbox"
                        type="text"
                        value={customRfqId}
                        onChange={(e) => {
                          setCustomRfqId(e.target.value);
                          setShowRfqDropdown(true);
                        }}
                        onKeyDown={(e) => { void handleRfqIdEnter(e); }}
                        placeholder="Search by RFQ ID, customer, or project"
                        className="w-full text-[11px] pl-8 pr-2.5 py-2 rounded-full border border-transparent bg-muted/60 text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 focus:bg-background transition-colors"
                      />
                    </div>
                    {showRfqDropdown && customRfqId.trim() && (
                      <div className="max-h-40 overflow-y-auto rounded-lg border border-border/70 bg-background/60 divide-y divide-border/50">
                        {rfqSearchLoading ? (
                          <p className="px-2.5 py-1.5 text-[11px] text-muted-foreground">Searching…</p>
                        ) : rfqSearchResults.length === 0 ? (
                          <p className="px-2.5 py-1.5 text-[11px] text-muted-foreground">No matching RFQs.</p>
                        ) : (
                          rfqSearchResults.map((r) => (
                            <button
                              key={r.rfq_id}
                              type="button"
                              onClick={() => handleRfqSearchResultClick(r.rfq_id)}
                              className="w-full px-2.5 py-1.5 text-left hover:bg-primary/[0.06] transition-colors"
                            >
                              <p className="text-[11px] font-medium text-foreground">{r.rfq_id}</p>
                              <p className="text-[10px] text-muted-foreground truncate">{r.customer_name} · {r.project_name}</p>
                            </button>
                          ))
                        )}
                      </div>
                    )}
                    {showRfqDropdown && rfqValidationMessage && (
                      <p className="srim-theme-muted mt-1 text-[11px]">
                        {rfqValidationMessage}
                      </p>
                    )}
                  </div>
                )}

                <div className="space-y-0" role="tree" aria-label="RFQ Pipeline macro-skills">
                  {WORKFLOW_STAGES.map((stage, idx) => {
                    const isSelected = currentWorkflowStage === stage.id;
                    const isComingSoon = 'comingSoon' in stage && stage.comingSoon;
                    // A stage is "skipped by toggle" iff it has at least one backing
                    // routing-profile skill (i.e. is one of the 4 real stages the 8
                    // skills map onto via macroCategory) AND every one of those
                    // skills is currently disabled in Settings. Stages with zero
                    // backing skills (comingSoon ones, or ones with no
                    // system_skills_registry entry at all) are never toggle-disabled.
                    const backingSkills = routingProfileSkills.filter(
                      (skill) => MACRO_CATEGORY_TO_STAGE[skill.macroCategory] === stage.id,
                    );
                    const isSkippedByToggle = !isComingSoon
                      && backingSkills.length > 0
                      && backingSkills.every((skill) => !skill.isEnabled);
                    const isLocked = isComingSoon || isSkippedByToggle;
                    const hasSubSkills = stage.subSkills.length > 0;
                    // Expansion is derived entirely from currentWorkflowStage, never an
                    // independent toggle -- whether that variable changes because the
                    // backend advanced or because the user clicked a navigable stage
                    // (both funnel through goToStage), the previously-current stage
                    // collapses and the newly-current one expands in the same
                    // recomputation, so at most one stage is ever expanded.
                    const isExpanded = !isLocked && hasSubSkills && stage.id === currentWorkflowStage;
                    const panelId = `macro-skill-${stage.id}-panel`;
                    // Per-stage status word/dot (Completed/Running/Waiting/Failed) --
                    // replaces the old idx < maxReachedStageIdx checkmark with the
                    // more accurate per-skill derivation from getStageStatus().
                    const stageStatus = isLocked ? 'waiting' : getStageStatus(stage.id as WorkflowStageId);
                    const stageStatusLabel = { completed: 'Completed', running: 'Running...', waiting: 'Waiting', failed: 'Failed' }[stageStatus];
                    const stageStatusTextClass = {
                      completed: 'text-emerald-500',
                      running: 'text-brand',
                      waiting: 'text-muted-foreground',
                      failed: 'text-destructive',
                    }[stageStatus];

                    // Every real, live stage (not comingSoon, not fully
                    // toggled off) stays clickable regardless of
                    // maxReachedStageIdx -- previously gated on "can't jump
                    // ahead of where this RFQ has actually reached," which in
                    // practice locked the entire sidebar past 'intake' for any
                    // RFQ_Flow run until enough SSE skill-progress events had
                    // landed to advance it. stageStatus (above) still reflects
                    // real backend progress for the status dot/label --
                    // this only stops disabling the button itself.
                    const isLast = idx === WORKFLOW_STAGES.length - 1;

                    return (
                      <div key={stage.id} className="flex gap-2.5">
                        {/* Node column -- icon tile (filled green+check when completed,
                            filled blue when current, outlined muted otherwise) plus a
                            connector line down to the next stage (solid green once this
                            stage is done, dashed/muted while still upcoming). */}
                        <div className="flex shrink-0 flex-col items-center pt-2.5">
                          <button
                            type="button"
                            disabled={isLocked}
                            title={stage.mainHeading}
                            aria-label={stage.mainHeading}
                            onClick={() => {
                              if (isLocked) { return; }
                              // Navigating is the only click behavior now -- expansion
                              // follows from currentWorkflowStage, not from this click
                              // directly (see isExpanded above).
                              goToStage(stage.id as WorkflowStageId);
                            }}
                            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border transition-colors ${isLocked
                                ? 'cursor-not-allowed border-border/50 bg-muted/30 text-muted-foreground/40'
                                : stageStatus === 'completed'
                                  ? 'border-transparent bg-emerald-500 text-white'
                                  : isSelected
                                    ? 'border-transparent bg-brand text-white'
                                    : 'border-border bg-card text-muted-foreground hover:border-brand/40 hover:text-brand'
                              }`}
                          >
                            {!isLocked && stageStatus === 'completed' ? (
                              <CheckCircle weight="fill" className="h-4 w-4" />
                            ) : (
                              <stage.icon className="h-4 w-4" weight="regular" />
                            )}
                          </button>
                          {!isLast && (
                            <div
                              className={`mt-1 min-h-[18px] w-0 flex-1 border-l-2 ${
                                stageStatus === 'completed' ? 'border-solid border-emerald-500' : 'border-dashed border-border'
                              }`}
                            />
                          )}
                        </div>

                        {!isLeftPanelCollapsed && (
                          <div className={`min-w-0 flex-1 rounded-md ${isExpanded ? 'border border-border/70 bg-muted/30' : ''} ${isLast ? '' : 'pb-1.5'}`}>
                            <button
                              type="button"
                              disabled={isLocked}
                              aria-expanded={hasSubSkills ? isExpanded : undefined}
                              aria-controls={hasSubSkills ? panelId : undefined}
                              onClick={() => {
                                if (isLocked) { return; }
                                goToStage(stage.id as WorkflowStageId);
                              }}
                              className={`relative w-full flex items-center gap-2.5 rounded-md py-3 pl-2.5 pr-3 text-left transition-colors duration-150 ${isSelected ? 'border-l-2 border-brand bg-brand/10 pl-[calc(0.625rem-2px)]' : 'border-l-2 border-transparent'
                              } ${isLocked
                                ? 'text-muted-foreground/50 cursor-not-allowed'
                                : isSelected
                                  ? 'text-brand hover:bg-brand/[0.14]'
                                  : stageStatus === 'completed'
                                    ? 'text-foreground hover:bg-muted/60'
                                    : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                              }`}
                            >
                              <span className="min-w-0 flex-1 flex flex-col">
                                <span className={`truncate text-[15px] ${isSelected ? 'font-semibold' : 'font-medium'}`}>{stage.mainHeading}</span>
                                <span className={`truncate text-[13px] ${stageStatusTextClass}`}>{stageStatusLabel}</span>
                              </span>
                              {/* Trailing slot -- exactly one of: lock, failed dot, or
                                  running spinner. No expand chevron: expansion follows
                                  currentWorkflowStage automatically, it's not a click
                                  toggle, so there's nothing to signal here. */}
                              {isLocked ? (
                                <LockSimple className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                              ) : stageStatus === 'failed' ? (
                                <span className="block h-2.5 w-2.5 shrink-0 rounded-full bg-destructive" />
                              ) : stageStatus === 'running' ? (
                                <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-border border-t-brand" />
                              ) : null}
                            </button>

                            {isExpanded && (
                              <div id={panelId} role="group" aria-label={`${stage.mainHeading} sub-skills`} className="space-y-0.5 px-2 pb-2 pl-2">
                                {stage.subSkills.map((sub) => (
                                  sub.action === 'info' ? (
                                    <div key={sub.label} className="flex items-center gap-2 rounded px-2 py-1 text-[13px] text-muted-foreground/70">
                                      <span className="h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
                                      {sub.label}
                                    </div>
                                  ) : (
                                    <button
                                      key={sub.label}
                                      type="button"
                                      onClick={() => handleSubSkillClick(stage.id as WorkflowStageId, sub.action)}
                                      className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px] transition-colors ${sub.action === 'createRfq'
                                          ? 'bg-primary font-semibold text-primary-foreground hover:bg-primary/90'
                                          : 'text-foreground/80 hover:bg-muted/60 hover:text-foreground'
                                        }`}
                                    >
                                      <span className={`h-1 w-1 shrink-0 rounded-full ${sub.action === 'createRfq' ? 'bg-primary-foreground' : 'bg-muted-foreground/50'}`} />
                                      {sub.label}
                                    </button>
                                  )
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

          </motion.div>
        </div>

        <div className="srim-pane-gutter" role="separator" aria-label="Resize control plane and chat">
          <button
            type="button"
            disabled={isLeftPanelCollapsed}
            className={`srim-splitter-handle transition-opacity duration-300 ${isLeftPanelCollapsed ? 'opacity-0 pointer-events-none' : ''}`}
            onPointerDown={(event) => startPanelDrag('control', event)}
            aria-label="Resize control plane and chat"
          />
        </div>

        {/* COLUMN 2: CENTRAL AI ASSISTANT CHAT CONTAINER — narrows to ~20% width when HITL is active, stays visible/usable */}
        <div className="srim-column-shell relative h-full min-w-0 overflow-hidden">
          <motion.div
            className="srim-panel srim-chat srim-theme-shell h-full flex flex-col overflow-hidden bg-card"
            style={{ minWidth: 0, width: '100%' }}
          >
            <main className="flex-1 overflow-hidden relative">
              {rfqCreatePaneOpen ? (
                <RfqExecutionCard
                  onCancel={() => setRfqCreatePaneOpen(false)}
                  onCreated={(rfqId) => {
                    setRfqCreatePaneOpen(false);
                    setCustomRfqId(rfqId);
                    setShowRfqDropdown(false);
                    setRfqProgressLog([]);
                    setActiveRfqId(rfqId);
                  }}
                  onUploadStart={(fileName) =>
                    setIntakeProgress((prev) => ({ ...prev, bomFileName: fileName, bomStatus: 'uploading', errorMessage: null }))
                  }
                  onUploadSuccess={(fileName) => {
                    goToStage('intake', { reset: true });
                    setIntakeProgress((prev) => ({ ...prev, bomFileName: fileName, bomStatus: 'processing' }));
                  }}
                  onUploadError={(message) =>
                    setIntakeProgress((prev) => ({ ...prev, bomStatus: 'error', errorMessage: message }))
                  }
                />
              ) : (
                <RfqProvider activeRfqId={activeRfqId}>
                  <AnimatedOutletWrapper />
                </RfqProvider>
              )}
            </main>
          </motion.div>
        </div>

        <div className="srim-pane-gutter" role="separator" aria-label="Resize chat and stage output">
          <button
            type="button"
            disabled={!!hitlContext}
            className={`srim-splitter-handle transition-opacity duration-300 ${hitlContext ? 'opacity-0 pointer-events-none' : ''}`}
            onPointerDown={(event) => startPanelDrag('output', event)}
            aria-label="Resize chat and stage output"
          />
        </div>

        {/* COLUMN 3: REAL-TIME OUTPUT STREAM WORKSPACE — expands to ~80% width on HITL */}
        <div className="srim-column-shell relative h-full min-w-0 overflow-hidden">
          <motion.div
            className="srim-panel srim-output srim-theme-panel relative h-full flex flex-col overflow-hidden bg-card p-6"
            style={{ minWidth: 0, width: '100%' }}
          >
            {/* Skipped entirely during HITL review -- the table itself is
                self-evidently the content at that point, and every line of
                header here is vertical space taken away from it. */}
            {!hitlContext && (
              <div className="mb-4 flex items-center justify-between gap-3 border-b border-border pb-4">
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-bold uppercase tracking-wide text-foreground">
                    See your work, flowing here
                  </h2>
                  <p className="truncate text-xs text-muted-foreground">Real-time results and artifacts</p>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {WORKFLOW_STAGES.find((s) => s.id === currentWorkflowStage)?.name ?? currentWorkflowStage}
                </span>
              </div>
            )}

            {/* Dynamic render area tracking layout sequence state switches or grid injections */}
            <div className="srim-panel-body flex-1 min-h-0 w-full rounded-xl border border-border/70 bg-background/70 overflow-hidden shadow-inner">
              {hitlContext ? (
                /* ✅ Directly pass the context data down through explicit component props */
                // key forces a full unmount/remount whenever the review session
                // itself changes (new rfqId or new hitl type/stage) -- without
                // it, back-to-back hitl:request events for the SAME rfqId
                // (e.g. alternates resolved -> resume -> apply_alternatives
                // halts moments later, since it's a fast, local-only DB
                // operation with no external API calls) can arrive close
                // enough together that React just re-renders the SAME
                // component instance with new props instead of remounting.
                // That leaks StageExecutionOutput's internal state --
                // isSubmitting in particular -- from the PRIOR hitl session
                // into the new one, silently disabling its Approve/Resume
                // button on the very next click.
                <StageExecutionOutput
                  key={`${hitlContext.rfqId}-${hitlContext.type}-${hitlContext.stage}`}
                  rpcClient={realRpcClient}
                  hitlContextData={hitlContext}
                  rowDataPayload={sharedRowData}
                  onNavigateToStage={goToStage}
                />
              ) : currentWorkflowStage === 'reportingAnalytics' ? (
                <SupersetDashboardPanel rfqId={customRfqId.trim() || undefined} />
              ) : (
                /* Continuous progress view -- keyed on broad mode only (not
                   currentWorkflowStage), so it never remounts/refades just
                   because a new skill advanced the stage. Appended entries
                   should feel like they're growing in place, not replacing
                   the whole panel each time. */
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div
                    key={hitlContext ? 'hitl' : 'progress'}
                    initial={{ opacity: 0, y: 12, filter: 'blur(4px)' }}
                    animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                    exit={{ opacity: 0, y: -12, filter: 'blur(4px)' }}
                    transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                    className="srim-log h-full overflow-y-auto text-xs leading-relaxed text-foreground/85"
                  >
                    {(currentWorkflowStage === 'intake' || currentWorkflowStage === 'erpDataSync') && (
                      <div className="p-5 pb-0">
                        <RfqIntakeProgressPanel
                          progress={intakeProgress}
                          currentWorkflowStage={currentWorkflowStage}
                          onRequestErpUpload={() => setErpSyncModalOpen(true)}
                        />
                      </div>
                    )}
                    {/* Real-activity card -- shown only while the upload is genuinely in
                        flight and no skill-progress SSE entry has arrived yet. Once
                        rfqProgressLog gets its first real entry, this naturally stops
                        rendering and the real per-skill list below takes over. */}
                    {(intakeProgress.bomStatus === 'uploading' || intakeProgress.bomStatus === 'processing') && rfqProgressLog.length === 0 && (
                      <div className="px-5 pt-3">
                        <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-4 shadow-sm">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand">
                            <Pulse className="h-4 w-4" />
                          </span>
                          <div className="min-w-0">
                            <p className="text-sm font-semibold text-foreground">Processing in progress</p>
                            <p className="text-xs text-muted-foreground">We are working on your RFQ.</p>
                          </div>
                        </div>
                      </div>
                    )}
                    <RfqProgressTimeline entries={rfqProgressLog} />
                    {currentWorkflowStage === 'quoteReadiness' && (
                      <div className="space-y-3 px-5 pb-5">
                        <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4">
                          <CheckCircle weight="fill" className="h-6 w-6 shrink-0 text-emerald-500" />
                          <div className="min-w-0">
                            <p className="text-sm font-bold text-foreground">CBOM generation completed successfully.</p>
                            <p className="text-xs text-muted-foreground">Your reports are ready.</p>
                          </div>
                        </div>

                        {/* Each row is independently gated on exportStatus's own
                            fields (populated by refreshExportStatus inside resumeRfq,
                            re-checked on every open/reopen) rather than assuming a
                            file exists just because this stage was reached -- a stale
                            or failed export step would otherwise show a button that
                            404s on click. */}
                        {exportStatus?.cbom && (
                          <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
                            <span className="flex h-8 w-10 shrink-0 items-center justify-center rounded-md bg-emerald-500/15 text-[10px] font-bold text-emerald-500">
                              XLS
                            </span>
                            <span
                              className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/85"
                              title={new Date(exportStatus.cbom.generatedAt).toLocaleString()}
                            >
                              {exportStatus.cbom.filename}
                            </span>
                            <button
                              type="button"
                              disabled={!customRfqId.trim()}
                              onClick={() => {
                                window.open(
                                  `${PYTHON_BRIDGE}/api/bom/export/${encodeURIComponent(customRfqId.trim())}/download`,
                                  '_blank',
                                );
                              }}
                              className="flex shrink-0 items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs font-semibold text-background transition hover:opacity-90 disabled:opacity-50"
                            >
                              <DownloadSimple className="h-3.5 w-3.5" weight="bold" />
                              Download
                            </button>
                          </div>
                        )}
                        {exportStatus?.consolidatedBom && (
                          <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
                            <span className="flex h-8 w-10 shrink-0 items-center justify-center rounded-md bg-emerald-500/15 text-[10px] font-bold text-emerald-500">
                              XLS
                            </span>
                            <span
                              className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/85"
                              title={new Date(exportStatus.consolidatedBom.generatedAt).toLocaleString()}
                            >
                              {exportStatus.consolidatedBom.filename}
                            </span>
                            <button
                              type="button"
                              disabled={!customRfqId.trim()}
                              onClick={() => {
                                // Deterministic Consolidated-BOM-only endpoint (same
                                // one StageExecutionOutput.tsx's handleDownloadExport
                                // uses) -- never the catch-all, so this can't
                                // accidentally serve the Quote Summary file instead.
                                window.open(
                                  `${PYTHON_BRIDGE}/api/bom/export-cbom/${encodeURIComponent(customRfqId.trim())}/download`,
                                  '_blank',
                                );
                              }}
                              className="flex shrink-0 items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs font-semibold text-background transition hover:opacity-90 disabled:opacity-50"
                            >
                              <DownloadSimple className="h-3.5 w-3.5" weight="bold" />
                              Download Consolidated BOM
                            </button>
                          </div>
                        )}
                        {exportStatus?.quoteSummary && (
                          <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
                            <span className="flex h-8 w-10 shrink-0 items-center justify-center rounded-md bg-emerald-500/15 text-[10px] font-bold text-emerald-500">
                              XLS
                            </span>
                            <span
                              className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/85"
                              title={new Date(exportStatus.quoteSummary.generatedAt).toLocaleString()}
                            >
                              {exportStatus.quoteSummary.filename}
                            </span>
                            <button
                              type="button"
                              disabled={!customRfqId.trim()}
                              onClick={() => {
                                window.open(
                                  `${PYTHON_BRIDGE}/api/bom/export-quote/${encodeURIComponent(customRfqId.trim())}/download`,
                                  '_blank',
                                );
                              }}
                              className="flex shrink-0 items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs font-semibold text-background transition hover:opacity-90 disabled:opacity-50"
                            >
                              <DownloadSimple className="h-3.5 w-3.5" weight="bold" />
                              Download Final Quote
                            </button>
                          </div>
                        )}
                        {exportStatus && !exportStatus.cbom && !exportStatus.consolidatedBom && !exportStatus.quoteSummary && (
                          <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
                            No export file found for this RFQ yet — try re-running the export step.
                          </div>
                        )}
                        {exportStatus && (exportStatus.cbom || exportStatus.consolidatedBom || exportStatus.quoteSummary) && (
                          <button
                            type="button"
                            onClick={() => {
                              // Marks Quote Readiness as done (green tick in the left
                              // panel) the same way every earlier stage does -- by
                              // advancing currentWorkflowStage past it. Decoupled from
                              // any individual download click now that there can be up
                              // to three of them -- there's no other trigger that ever
                              // moves past quoteReadiness, so without this its
                              // checkmark never appears.
                              goToStage('reportingAnalytics');
                            }}
                            className="text-xs font-semibold text-foreground underline-offset-2 hover:underline"
                          >
                            Continue to Reports
                          </button>
                        )}
                      </div>
                    )}
                  </motion.div>
                </AnimatePresence>
              )}
            </div>
          </motion.div>
        </div>

      </div>
      {/* ─────────────────────────────────────────────────────────────────── */}

      <TaskLauncher />

      {/* Auth Error Toast - shown when OAuth session expires */}
      <AuthErrorToast error={authError} onReLogin={handleAuthReLogin} onDismiss={clearAuthError} />

      {/* Daemon Connection Toast - shown when daemon disconnects */}
      <DaemonConnectionToast
        onOpenSettings={() => {
          setAuthSettingsTab('general');
          setAuthSettingsOpen(true);
        }}
      />

      {/* Settings Dialog for re-authentication */}
      {authSettingsOpen && (
        <Suspense fallback={null}>
          <SettingsDialog
            open={authSettingsOpen}
            onOpenChange={handleAuthSettingsClose}
            initialProvider={authSettingsProvider}
            initialTab={authSettingsTab}
            onApiKeySaved={() => {
              clearAuthError();
              setAuthSettingsOpen(false);
            }}
          />
        </Suspense>
      )}
    </div>
  );
}
