import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { AdminUserRow } from '@/lib/accomplish';

interface ResetPasswordDialogProps {
  user: AdminUserRow | null;
  onOpenChange: (open: boolean) => void;
  onReset: (userId: string, newPassword: string) => Promise<void>;
}

export function ResetPasswordDialog({ user, onOpenChange, onReset }: ResetPasswordDialogProps) {
  const [newPassword, setNewPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!user) { return; }
    if (newPassword.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onReset(user.id, newPassword);
      setNewPassword('');
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset password');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={user !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Reset password{user ? ` — ${user.uid}` : ''}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">New password</label>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={() => { void handleSubmit(); }} disabled={submitting}>
            {submitting ? 'Resetting…' : 'Reset password'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
