import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import type { AdminUserRow } from '@/lib/accomplish';

interface DeleteUserDialogProps {
  user: AdminUserRow | null;
  onOpenChange: (open: boolean) => void;
  onDelete: (userId: string) => Promise<void>;
}

export function DeleteUserDialog({ user, onOpenChange, onDelete }: DeleteUserDialogProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!user) { return; }
    setSubmitting(true);
    setError(null);
    try {
      await onDelete(user.id);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete user');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={user !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Delete user{user ? ` — ${user.uid}` : ''}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          <p className="text-sm text-muted-foreground">
            This permanently removes {user?.fullName || user?.uid}&apos;s account. This can&apos;t be undone.
          </p>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => { void handleSubmit(); }} disabled={submitting}>
            {submitting ? 'Deleting…' : 'Delete user'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
