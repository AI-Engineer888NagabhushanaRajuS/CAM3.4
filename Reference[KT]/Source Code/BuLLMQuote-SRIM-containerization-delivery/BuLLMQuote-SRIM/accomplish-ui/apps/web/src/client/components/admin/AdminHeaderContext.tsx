import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

interface AdminHeaderInfo {
  title: string;
  count: number;
  total: number;
}

interface AdminHeaderContextValue {
  header: AdminHeaderInfo | null;
  setHeader: (info: AdminHeaderInfo) => void;
}

const AdminHeaderContext = createContext<AdminHeaderContextValue | null>(null);

export function AdminHeaderProvider({ children }: { children: ReactNode }) {
  const [header, setHeader] = useState<AdminHeaderInfo | null>(null);
  const value = useMemo(() => ({ header, setHeader }), [header]);
  return <AdminHeaderContext.Provider value={value}>{children}</AdminHeaderContext.Provider>;
}

/** Pages call this once per render with their current title/counts to publish them into the persistent top header. */
export function useAdminHeader(info: AdminHeaderInfo) {
  const ctx = useContext(AdminHeaderContext);
  if (!ctx) { throw new Error('useAdminHeader must be used within AdminHeaderProvider'); }
  const { setHeader } = ctx;
  useEffect(() => {
    setHeader(info);
    // Intentionally keyed on the primitive fields below, not `info` itself --
    // `info` is a fresh object literal every render, so using it as a dep
    // would defeat the point of this effect (fire only on real value changes).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info.title, info.count, info.total, setHeader]);
}

export function useAdminHeaderValue(): AdminHeaderInfo | null {
  const ctx = useContext(AdminHeaderContext);
  if (!ctx) { throw new Error('useAdminHeaderValue must be used within AdminHeaderProvider'); }
  return ctx.header;
}
