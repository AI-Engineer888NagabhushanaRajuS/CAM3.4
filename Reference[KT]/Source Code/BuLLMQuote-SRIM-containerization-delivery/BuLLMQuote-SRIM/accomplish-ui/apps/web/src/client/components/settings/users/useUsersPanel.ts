import { useCallback, useEffect, useState } from 'react';
import { getAccomplish, type AdminUserRow } from '@/lib/accomplish';

export interface CreateUserParams {
  uid: string;
  fullName: string;
  email: string;
  password: string;
  role: 'admin' | 'user' | 'fde';
}

export interface UpdateUserParams {
  fullName?: string;
  email?: string;
  role?: 'admin' | 'user' | 'fde';
  isActive?: boolean;
}

export interface UseUsersPanelResult {
  loading: boolean;
  users: AdminUserRow[]; // sorted newest-first by the daemon
  pendingUserId: string | null; // which row has an in-flight mutation, for per-row disabling
  error: string | null;
  handleCreate: (params: CreateUserParams) => Promise<void>;
  handleUpdate: (userId: string, patch: UpdateUserParams) => Promise<void>;
  handleResetPassword: (userId: string, newPassword: string) => Promise<void>;
  handleToggleActive: (userId: string, nextActive: boolean) => Promise<void>;
  handleDelete: (userId: string) => Promise<void>;
}

// Mirrors useRoutingProfilePanel.ts's shape -- fetch-once + mutate + refetch.
// Unlike that hook's optimistic toggle, mutations here do a full refetch
// afterward instead of patching local state in place: user rows have several
// server-assigned/derived fields (id, createdAt) that a create/update
// response already returns correctly, and list sizes are small enough that
// a refetch is cheap and avoids any optimistic-update/rollback edge cases.
export function useUsersPanel(): UseUsersPanelResult {
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    const { users: fetched } = await getAccomplish().adminListUsers();
    setUsers(fetched);
  }, []);

  useEffect(() => {
    let isCurrent = true;
    setLoading(true);
    refetch()
      .catch((err: unknown) => {
        if (isCurrent) { setError(err instanceof Error ? err.message : 'Failed to load users'); }
      })
      .finally(() => {
        if (isCurrent) { setLoading(false); }
      });
    return () => { isCurrent = false; };
  }, [refetch]);

  const handleCreate = useCallback(async (params: CreateUserParams) => {
    setError(null);
    try {
      await getAccomplish().adminCreateUser(params);
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
      throw err;
    }
  }, [refetch]);

  const handleUpdate = useCallback(async (userId: string, patch: UpdateUserParams) => {
    setError(null);
    setPendingUserId(userId);
    try {
      await getAccomplish().adminUpdateUser({ userId, ...patch });
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update user');
      throw err;
    } finally {
      setPendingUserId(null);
    }
  }, [refetch]);

  const handleResetPassword = useCallback(async (userId: string, newPassword: string) => {
    setError(null);
    setPendingUserId(userId);
    try {
      await getAccomplish().adminResetUserPassword({ userId, newPassword });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset password');
      throw err;
    } finally {
      setPendingUserId(null);
    }
  }, []);

  const handleToggleActive = useCallback(async (userId: string, nextActive: boolean) => {
    await handleUpdate(userId, { isActive: nextActive });
  }, [handleUpdate]);

  const handleDelete = useCallback(async (userId: string) => {
    setError(null);
    setPendingUserId(userId);
    try {
      await getAccomplish().adminDeleteUser({ userId });
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete user');
      throw err;
    } finally {
      setPendingUserId(null);
    }
  }, [refetch]);

  return { loading, users, pendingUserId, error, handleCreate, handleUpdate, handleResetPassword, handleToggleActive, handleDelete };
}
