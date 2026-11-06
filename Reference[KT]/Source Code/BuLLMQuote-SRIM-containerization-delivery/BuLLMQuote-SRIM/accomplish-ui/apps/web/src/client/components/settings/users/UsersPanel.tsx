import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { AdminUserRow } from '@/lib/accomplish';
import { UserCard } from './UserCard';
import { CreateUserDialog } from './CreateUserDialog';
import { ResetPasswordDialog } from './ResetPasswordDialog';
import { DeleteUserDialog } from './DeleteUserDialog';
import { useUsersPanel } from './useUsersPanel';

// Replaces the old mock admin/skill-profiler page's purpose (user/role
// management) with a real, admin-gated Settings tab. Vertical list, matching
// RoutingProfilePanel.tsx's layout conventions.
export function UsersPanel() {
  const { loading, users, pendingUserId, error, handleCreate, handleResetPassword, handleToggleActive, handleDelete } = useUsersPanel();
  const [createOpen, setCreateOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState<AdminUserRow | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUserRow | null>(null);

  if (loading) {
    return (
      <div className="flex h-[480px] items-center justify-center text-sm text-muted-foreground">
        Loading users...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Only admins can create accounts or reset passwords — there is no self-service sign-up.
        </p>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          + Add user
        </Button>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex max-h-[480px] flex-col gap-2 overflow-y-auto pr-1">
        {users.map((user) => (
          <UserCard
            key={user.id}
            user={user}
            disabled={pendingUserId === user.id}
            onToggleActive={(userId, nextActive) => { void handleToggleActive(userId, nextActive); }}
            onResetPassword={setResetTarget}
            onDelete={setDeleteTarget}
          />
        ))}
      </div>
      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} onCreate={handleCreate} />
      <ResetPasswordDialog
        user={resetTarget}
        onOpenChange={(open) => { if (!open) { setResetTarget(null); } }}
        onReset={handleResetPassword}
      />
      <DeleteUserDialog
        user={deleteTarget}
        onOpenChange={(open) => { if (!open) { setDeleteTarget(null); } }}
        onDelete={handleDelete}
      />
    </div>
  );
}
