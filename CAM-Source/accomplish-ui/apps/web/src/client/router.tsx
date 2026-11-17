import { createHashRouter, Navigate, redirect } from 'react-router';
import { HomePage } from './pages/Home';
import ExecutionPage from './pages/Execution';
import { LoginPage } from './pages/LoginPage';
import { OrganizationPage } from './pages/admin/OrganizationPage';
import { CamMastersPage } from './pages/admin/CamMastersPage';
import { ProjectPage } from './pages/admin/ProjectPage';
import { CostingPage } from './pages/admin/CostingPage';
import { RouteErrorFallback } from './components/ui/RouteErrorFallback';
import { isAdmin, isFde, isLoggedIn } from './lib/session';

// Self-service sign-up and password reset are disabled — accounts are
// admin-created only (see the "Contact your admin" badge on LoginPage), and
// only an admin can reset another user's password (Settings -> Users).
// Redirect unauthenticated users to /login.
function requireAuth() {
  if (!isLoggedIn()) return redirect('/login');
  return null;
}

function requireAdmin() {
  if (!isLoggedIn()) return redirect('/login');
  if (!isAdmin()) return redirect('/');
  return null;
}

function requireFde() {
  if (!isLoggedIn()) return redirect('/login');
  if (!isFde()) return redirect('/');
  return null;
}

export const router = createHashRouter([
  // Public auth routes
  { path: '/login', Component: LoginPage },

  // Protected app routes
  {
    path: '/',
    lazy: async () => {
      const { App } = await import('./App');
      return { Component: App };
    },
    errorElement: <RouteErrorFallback />,
    loader: requireAuth,
    children: [
      {
        index: true,
        Component: HomePage,
        errorElement: <RouteErrorFallback />,
      },
      {
        path: 'execution/:id',
        Component: ExecutionPage,
        errorElement: <RouteErrorFallback />,
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },

  // DigiBull Bulletproof Admin UI -- flat left-sidebar nav: Organization
  // Master, Project Master, Quote Master. A pathless layout route: it
  // contributes no URL segment of its own, just wraps every one of these
  // top-level paths in one shared sidebar + header shell.
  {
    lazy: async () => {
      const { AdminAppLayout } = await import('./pages/admin/AdminAppLayout');
      return { Component: AdminAppLayout };
    },
    errorElement: <RouteErrorFallback />,
    loader: requireAdmin,
    children: [
      { path: 'organization', Component: OrganizationPage },
      { path: 'cam-masters', Component: CamMastersPage },
      { path: 'project', Component: ProjectPage },
      { path: 'costing', Component: CostingPage },
      { path: '*', element: <Navigate to="/organization" replace /> },
    ],
  },

  // SPEC-020: manifest tree + Monaco JSON editor. Own full-screen shell; lazy so Monaco only loads here.
  {
    path: 'manifests',
    lazy: () => import('./pages/Manifests'),
    errorElement: <RouteErrorFallback />,
    loader: requireAuth,
  },

  // FDE Staging Pipeline -- role-gated, own top-level route, completely
  // separate shell from both the RFQ App and the Admin UI. Single-page
  // (FDEAppLayout renders its own left/center/right panes directly, unlike
  // AdminAppLayout above which wraps separate child pages) -- no children
  // needed.
  {
    path: 'workflow-builder',
    lazy: async () => {
      const { FDEAppLayout } = await import('./pages/fde/FDEAppLayout');
      return { Component: FDEAppLayout };
    },
    errorElement: <RouteErrorFallback />,
    loader: requireFde,
  },
]);
