import { memo, useCallback, useState } from 'react';
import type { AdminUserRow } from '@/lib/accomplish';
import { UserActivity } from './UserActivity';

interface UserCardProps {
  user: AdminUserRow;
  onToggleActive: (userId: string, nextActive: boolean) => void;
  onResetPassword: (user: AdminUserRow) => void;
  onDelete: (user: AdminUserRow) => void;
  disabled?: boolean; // true while an in-flight mutation is pending for this row
}

// Mirrors RoutingProfileCard.tsx's card shell/toggle-switch styling for
// visual consistency across the two Settings panels this session added.
export const UserCard = memo(function UserCard({
  user,
  onToggleActive,
  onResetPassword,
  onDelete,
  disabled,
}: UserCardProps) {
  const [showActivity, setShowActivity] = useState(false);
  const handleToggle = useCallback(() => {
    onToggleActive(user.id, !user.isActive);
  }, [onToggleActive, user.id, user.isActive]);

  const handleResetPassword = useCallback(() => {
    onResetPassword(user);
  }, [onResetPassword, user]);

  const handleDelete = useCallback(() => {
    onDelete(user);
  }, [onDelete, user]);

  return (
    <div className="group rounded-xl border border-border bg-card p-3.5 transition-all duration-200 hover:border-primary hover:shadow-md">
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
            {user.fullName || user.uid}
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                user.role === 'admin'
                  ? 'bg-primary/15 text-primary'
                  : 'bg-secondary text-secondary-foreground'
              }`}
            >
              {user.role}
            </span>
          </span>
          <p className="truncate text-[11px] text-muted-foreground">{user.uid} · {user.email}</p>
        </div>
        <button
          onClick={handleToggle}
          disabled={disabled}
          className={`relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50 ${
            user.isActive ? 'bg-primary' : 'bg-muted'
          }`}
          aria-label={user.isActive ? `Deactivate ${user.uid}` : `Activate ${user.uid}`}
        >
          <span
            className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
              user.isActive ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
          {user.isActive ? 'Active' : 'Inactive'}
        </span>
        <button
          onClick={() => setShowActivity((v) => !v)}
          aria-expanded={showActivity}
          className="text-[11px] font-medium text-primary hover:underline"
        >
          {showActivity ? 'Hide activity' : 'Activity'}
        </button>
        <button
          onClick={handleResetPassword}
          disabled={disabled}
          className="text-[11px] font-medium text-primary hover:underline disabled:opacity-50"
        >
          Reset password
        </button>
        <button
          onClick={handleDelete}
          disabled={disabled}
          className="text-[11px] font-medium text-destructive hover:underline disabled:opacity-50"
        >
          Delete
        </button>
      </div>
      {showActivity && <UserActivity email={user.email} />}
    </div>
  );
});
