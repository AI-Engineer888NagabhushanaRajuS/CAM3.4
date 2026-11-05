import * as DialogPrimitive from '@radix-ui/react-dialog';
import { motion, AnimatePresence } from 'framer-motion';
import { NavLink } from 'react-router';
import { Buildings, Calculator, Kanban, X } from '@phosphor-icons/react';
import { BrandMark } from '@/components/BrandMark';

const NAV_ITEMS = [
  { to: '/organization', label: 'Organization Master', icon: Buildings },
  { to: '/project', label: 'Project Master', icon: Kanban },
  { to: '/costing', label: 'Quote Master', icon: Calculator },
] as const;

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-4 dark:border-white/10">
        <BrandMark className="text-lg" />
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'text-foreground/75 hover:bg-muted/50'
                }`
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}

interface AdminSidebarProps {
  mobileOpen: boolean;
  onMobileOpenChange: (open: boolean) => void;
}

export function AdminSidebar({ mobileOpen, onMobileOpenChange }: AdminSidebarProps) {
  return (
    <>
      {/* Persistent desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-border bg-card lg:block">
        <SidebarBody />
      </aside>

      {/* Mobile drawer -- same slide-in Radix Dialog pattern used elsewhere in the admin UI, mirrored to the left */}
      <DialogPrimitive.Root open={mobileOpen} onOpenChange={onMobileOpenChange}>
        <AnimatePresence>
          {mobileOpen && (
            <DialogPrimitive.Portal forceMount>
              <DialogPrimitive.Overlay asChild forceMount>
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="fixed inset-0 z-50 bg-background/60 backdrop-blur-[8px] lg:hidden"
                />
              </DialogPrimitive.Overlay>
              <DialogPrimitive.Content asChild forceMount aria-describedby={undefined}>
                <motion.div
                  initial={{ x: '-100%' }}
                  animate={{ x: 0 }}
                  exit={{ x: '-100%' }}
                  transition={{ duration: 0.22, ease: 'easeOut' }}
                  className="fixed left-0 top-0 z-50 h-full w-60 border-r border-border bg-card shadow-2xl dark:border-white/10 lg:hidden"
                >
                  <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
                  <DialogPrimitive.Close className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground">
                    <X className="h-4 w-4" />
                  </DialogPrimitive.Close>
                  <SidebarBody onNavigate={() => onMobileOpenChange(false)} />
                </motion.div>
              </DialogPrimitive.Content>
            </DialogPrimitive.Portal>
          )}
        </AnimatePresence>
      </DialogPrimitive.Root>
    </>
  );
}
