import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { createFdeProject } from '@/lib/fdeApi';

interface FDESettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onProjectCreated: (projectId: string) => void;
}

/** The SOLE project-creation surface, per spec -- a standalone dialog (not
 * nested into the existing RFQ/admin SettingsDialog.tsx, which is a
 * different, tabbed, RFQ/admin-scoped component). */
export function FDESettingsDialog({ open, onOpenChange, onProjectCreated }: FDESettingsDialogProps) {
  const [projectName, setProjectName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setProjectName('');
    setDescription('');
    setError(null);
  };

  const handleClose = () => {
    reset();
    onOpenChange(false);
  };

  const handleCreate = async () => {
    if (!projectName.trim()) {
      setError('Project name is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const project = await createFdeProject(projectName.trim(), description.trim() || undefined);
      reset();
      onOpenChange(false);
      onProjectCreated(project.project_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create project');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) { handleClose(); } }}>
      <DialogContent className="max-w-md border-border bg-card">
        <DialogHeader>
          <DialogTitle className="text-foreground">New FDE Project</DialogTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Creates a new staging project for the FDE pipeline.
          </p>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Project Name
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. Acme Corp Onboarding"
              className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Description <span className="text-muted-foreground/60">(optional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
          </div>

          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </p>
          )}
        </div>

        <DialogFooter className="gap-2">
          <button
            type="button"
            onClick={handleClose}
            className="text-xs text-muted-foreground hover:text-foreground"
            disabled={submitting}
          >
            Cancel
          </button>
          <Button onClick={handleCreate} disabled={submitting} size="sm">
            {submitting ? 'Creating…' : 'Create Project'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
