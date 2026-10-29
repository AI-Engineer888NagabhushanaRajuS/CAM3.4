import { useState } from 'react';
import { Outlet, useNavigate } from 'react-router';
import { ArrowLeft, List, SignOut } from '@phosphor-icons/react';
import { clearSession, getSession } from '../../lib/session';
import { AdminSidebar } from '../../components/admin/AdminSidebar';
import { AdminHeaderProvider, useAdminHeaderValue } from '../../components/admin/AdminHeaderContext';
import { ThemeToggle } from '../../components/ui/ThemeToggle';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../../components/ui/dropdown-menu';

function AdminHeader({ onOpenMobileNav }: { onOpenMobileNav: () => void }) {
  const navigate = useNavigate();
  const session = getSession();
  const sessionUser = session?.user ?? { name: 'Admin', email: '' };
  const header = useAdminHeaderValue();

  const handleSignOut = () => {
    clearSession();
    navigate('/login', { replace: true, state: { loggedOut: true } });
  };

  return (
    <header className="flex shrink-0 items-center justify-between border-b border-border bg-card px-5 py-3 dark:border-white/10">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onOpenMobileNav}
          title="Open navigation"
          className="rounded-lg p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground lg:hidden"
        >
          <List className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => navigate('/')}
          title="Back to workspace"
          className="rounded-lg p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0">
          <p className="truncate text-sm font-bold leading-tight text-foreground">{header?.title ?? ''}</p>
          {header && <p className="text-[11px] leading-tight text-muted-foreground">{header.count} of {header.total} records</p>}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <ThemeToggle />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary transition hover:bg-primary/25"
            >
              {sessionUser.name.slice(0, 1).toUpperCase()}
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
  );
}

export function AdminAppLayout() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <AdminHeaderProvider>
      <div className="flex h-screen bg-background text-foreground">
        <AdminSidebar mobileOpen={mobileNavOpen} onMobileOpenChange={setMobileNavOpen} />

        <div className="flex min-w-0 flex-1 flex-col">
          <AdminHeader onOpenMobileNav={() => setMobileNavOpen(true)} />
          <main className="min-w-0 flex-1 overflow-y-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </AdminHeaderProvider>
  );
}

export const Component = AdminAppLayout;
