import { useEffect, useState } from 'react';
import { FolderOpen, Gear } from '@phosphor-icons/react';
import { listFdeProjects, type FdeProject } from '@/lib/fdeApi';

interface FDEProjectPickerProps {
  onSelectProject: (projectId: string) => void;
  onOpenSettings: () => void;
}

/** "Pick or see projects" -- shown inside the center-pane card before a
 * project is selected. Per spec, this view only SELECTS an existing
 * project; creating one happens exclusively via the gear-icon Settings
 * dialog (FDESettingsDialog). */
export function FDEProjectPicker({ onSelectProject, onOpenSettings }: FDEProjectPickerProps) {
  const [projects, setProjects] = useState<FdeProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listFdeProjects()
      .then((data) => {
        if (!cancelled) setProjects(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load projects');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="w-full max-w-md space-y-4 rounded-xl border border-border bg-card p-6">
        <div>
          <h2 className="text-sm font-bold text-foreground">Select a project</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Choose an existing FDE project, or create a new one via Settings.
          </p>
        </div>

        {loading && <p className="text-xs text-muted-foreground">Loading projects…</p>}
        {error && (
          <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        )}

        {!loading && !error && projects.length === 0 && (
          <p className="text-xs text-muted-foreground">No projects yet -- create one via Settings.</p>
        )}

        {!loading && projects.length > 0 && (
          <div className="max-h-72 space-y-1.5 overflow-y-auto">
            {projects.map((p) => (
              <button
                key={p.project_id}
                type="button"
                onClick={() => onSelectProject(p.project_id)}
                className="flex w-full items-center gap-2.5 rounded-lg border border-border px-3 py-2 text-left transition hover:border-primary hover:bg-primary/5"
              >
                <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">{p.project_name}</span>
                  <span className="block truncate font-mono text-[10px] text-muted-foreground">{p.project_id}</span>
                </span>
              </button>
            ))}
          </div>
        )}

        <button
          type="button"
          onClick={onOpenSettings}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-foreground px-3 py-2 text-xs font-semibold text-background transition hover:opacity-90"
        >
          <Gear className="h-3.5 w-3.5" weight="bold" />
          Open Settings to create a new project
        </button>
      </div>
    </div>
  );
}
