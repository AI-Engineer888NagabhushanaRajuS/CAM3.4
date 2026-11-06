import { Gear, SignOut } from '@phosphor-icons/react';
import { useNavigate } from 'react-router';
import { clearSession, getSession } from '@/lib/session';

export type FdeStageId = 'upload_docs' | 'cognify' | 'okf_bundle' | 'sow_generation' | 'validation' | 'skill';

interface FdeStageDef {
  id: FdeStageId;
  label: string;
  enabled: boolean;
}

// Stage 1 only, for real, right now -- stages 2-6 are inert stub
// placeholders (see FDEStageStub.tsx) until SBAM (the Cognee/OKF/SOW
// engine those stages subprocess-wrap) is available on this machine.
const FDE_STAGES: FdeStageDef[] = [
  { id: 'upload_docs', label: '1. Upload Docs', enabled: true },
  { id: 'cognify', label: '2. Cognify', enabled: false },
  { id: 'okf_bundle', label: '3. OKF Bundle', enabled: false },
  { id: 'sow_generation', label: '4. SOW Generation', enabled: false },
  { id: 'validation', label: '5. Validation', enabled: false },
  { id: 'skill', label: '6. Skill', enabled: false },
];

interface FDEStageSidebarProps {
  activeStage: FdeStageId;
  onSelectStage: (stage: FdeStageId) => void;
  selectedProjectId: string | null;
  onOpenSettings: () => void;
}

export function FDEStageSidebar({ activeStage, onSelectStage, selectedProjectId, onOpenSettings }: FDEStageSidebarProps) {
  const navigate = useNavigate();
  const session = getSession();
  const sessionUser = session?.user ?? { name: 'FDE', email: '' };

  const handleSignOut = () => {
    clearSession();
    navigate('/login', { replace: true, state: { loggedOut: true } });
  };

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-foreground">Skill Build-Time Acceleration</p>
          <p className="text-[11px] text-muted-foreground">FDE Staging Pipeline</p>
        </div>
        <button
          type="button"
          onClick={onOpenSettings}
          title="Settings"
          className="shrink-0 rounded-lg p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
        >
          <Gear className="h-4 w-4" />
        </button>
      </div>

      <div className="px-4 py-3">
        <button
          type="button"
          onClick={() => onSelectStage('upload_docs')}
          className="w-full rounded-lg border border-dashed border-border px-3 py-2 text-left text-xs text-muted-foreground transition hover:border-primary hover:text-foreground"
        >
          {selectedProjectId ? (
            <span className="font-mono text-foreground">{selectedProjectId}</span>
          ) : (
            'Select Project'
          )}
        </button>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
        {FDE_STAGES.map((stage) => {
          const isActive = stage.id === activeStage;
          return (
            <button
              key={stage.id}
              type="button"
              disabled={!stage.enabled}
              onClick={() => stage.enabled && onSelectStage(stage.id)}
              className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                isActive
                  ? 'bg-primary/10 font-semibold text-primary'
                  : stage.enabled
                    ? 'text-foreground hover:bg-muted'
                    : 'cursor-not-allowed text-muted-foreground/50'
              }`}
            >
              {stage.label}
              {!stage.enabled && <span className="ml-1.5 text-[10px] uppercase tracking-wide">(soon)</span>}
            </button>
          );
        })}
      </nav>

      <div className="flex items-center justify-between border-t border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary">
            {sessionUser.name.slice(0, 1).toUpperCase()}
          </span>
          <span className="truncate text-xs text-muted-foreground">{sessionUser.name}</span>
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          title="Sign out"
          className="shrink-0 rounded-lg p-1.5 text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive"
        >
          <SignOut className="h-4 w-4" />
        </button>
      </div>
    </aside>
  );
}
