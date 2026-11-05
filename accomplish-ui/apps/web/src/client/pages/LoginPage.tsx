import { useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { loginWithCredentials, clearSession } from '@/lib/session';
import type { UserRole } from '@/lib/session';
import { Eye, EyeSlash, LockKey, ShieldCheck, User } from '@phosphor-icons/react';
import { AuthLayout, Field, PrimaryButton } from './auth-shared';

// For development/testing only. Remove or disable in production.
const TEST_CREDS = {
  username: 'digibull',
  password: 'srim-test-2026',
};

type LoginType = 'user' | 'admin';

const USER_WORKSPACE_ROUTE = '/';
// Organization Master is the first item in the Bulletproof Admin UI's flat
// sidebar nav order, so that's where an admin lands after signing in.
const ADMIN_CONTROL_PLANE_ROUTE = '/organization';
// FDE Staging Pipeline's own landing page -- an 'fde'-role account signing
// in via the normal (non-admin-toggle) login form lands here instead of
// the RFQ workspace, since /workflow-builder's own requireFde() loader is
// the only route that role can actually reach.
const FDE_WORKSPACE_ROUTE = '/workflow-builder';

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [loginType, setLoginType] = useState<LoginType>('user');
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(() => {
    const state = location.state as { loggedOut?: boolean } | null;
    return state?.loggedOut ? 'You have been signed out successfully.' : null;
  });
  const [error, setError] = useState<string | null>(null);

  const classifyError = (err: unknown): string => {
    const msg = (err instanceof Error ? err.message : String(err)).toLowerCase();
    if (msg.includes('fetch') || msg.includes('network') || msg.includes('refused') || msg.includes('failed to fetch')) {
      return '🔴 Cannot reach authentication server. Check your network or firewall.';
    }
    if (msg.includes('inactive') || msg.includes('disabled') || msg.includes('domain') || msg.includes('403')) {
      return '⚠️ Account inactive or domain access denied. Contact your administrator.';
    }
    return '❌ Invalid username or password. Please try again.';
  };

  // Switching login type is only a UX indicator of the intended destination --
  // it never grants privileges itself. The real gate is here: authentication
  // always runs through the same single entry point (loginWithCredentials);
  // this just decides where a successfully-authenticated session is allowed
  // to land, and blocks (and immediately clears) a non-admin session that
  // was authenticated while "Admin Login" was selected.
  const routeAfterLogin = (role: UserRole): true | string => {
    if (loginType === 'admin' && role !== 'admin') {
      clearSession();
      return 'Administrator access is not enabled for this account.';
    }
    const destination =
      loginType === 'admin'
        ? ADMIN_CONTROL_PLANE_ROUTE
        : role === 'fde'
          ? FDE_WORKSPACE_ROUTE
          : USER_WORKSPACE_ROUTE;
    void navigate(destination, { replace: true });
    return true;
  };

  const handleLoginTypeChange = (next: LoginType) => {
    setLoginType(next);
    setPassword('');
    setError(null);
    setNotice(null);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!identifier.trim()) {
      setError('Enter your username or email.');
      return;
    }
    if (!password.trim()) {
      setError('Enter your password.');
      return;
    }
    setLoading(true);
    setError(null);
    setNotice(null);
    loginWithCredentials(identifier.trim(), password)
      .then(({ role }) => {
        const result = routeAfterLogin(role);
        if (result !== true) { setError(result); }
      })
      .catch((err) => { setError(classifyError(err)); })
      .finally(() => { setLoading(false); });
  };

  // For development/testing only. Remove or disable in production.
  const handleTestLogin = () => {
    setLoading(true);
    setError(null);
    setNotice(null);
    loginWithCredentials(TEST_CREDS.username, TEST_CREDS.password)
      .then(({ role }) => {
        const result = routeAfterLogin(role);
        if (result !== true) { setError(result); }
      })
      .catch((err) => { setError(classifyError(err)); })
      .finally(() => { setLoading(false); });
  };

  return (
    <AuthLayout subtitle="Welcome back" title="Login to CAM 3.4" badge="Secure">
      {/* Login Type selector -- a UX indicator of intended destination only;
          it never grants privileges by itself (see routeAfterLogin above). */}
      <div className="mt-5">
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground dark:text-white/45">
          Login Type
        </span>
        <div className="mt-1.5 grid grid-cols-2 gap-1.5 rounded-2xl border border-border bg-muted/30 p-1 dark:border-white/10 dark:bg-white/[0.04]">
          <button
            type="button"
            onClick={() => handleLoginTypeChange('user')}
            aria-pressed={loginType === 'user'}
            className={`flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold transition-all duration-150 ${
              loginType === 'user'
                ? 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white shadow-sm'
                : 'border border-border bg-card text-foreground hover:bg-muted/50 dark:border-white/10 dark:bg-white/[0.02] dark:text-white/80'
              }`}
          >
            <User className="h-4 w-4" weight={loginType === 'user' ? 'fill' : 'regular'} />
            User Login
          </button>
          <button
            type="button"
            onClick={() => handleLoginTypeChange('admin')}
            aria-pressed={loginType === 'admin'}
            className={`flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold transition-all duration-150 ${
              loginType === 'admin'
                ? 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white shadow-sm'
                : 'border border-border bg-card text-foreground hover:bg-muted/50 dark:border-white/10 dark:bg-white/[0.02] dark:text-white/80'
              }`}
          >
            <ShieldCheck className="h-4 w-4" weight={loginType === 'admin' ? 'fill' : 'regular'} />
            Admin Login
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="mt-4 space-y-4">
        <Field
          id="identifier"
          label="Username or Email"
          value={identifier}
          placeholder="username or email@example.com"
          autoComplete="username"
          onChange={(v) => {
            setIdentifier(v);
            setError(null);
          }}
        />
        <Field
          id="password"
          label="Password"
          type={showPassword ? 'text' : 'password'}
          value={password}
          placeholder="Enter password"
          autoComplete="current-password"
          onChange={(v) => {
            setPassword(v);
            setError(null);
          }}
          rightAdornment={
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowPassword((s) => !s)}
              className="text-muted-foreground transition hover:text-foreground dark:text-white/40 dark:hover:text-white/70"
            >
              {showPassword ? <EyeSlash size={16} /> : <Eye size={16} />}
            </button>
          }
        />
        <PrimaryButton loading={loading} loadingText="Signing in...">
          Sign In
        </PrimaryButton>

        {/* On-Prem Verified badge */}
        <div className="flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
          <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">On-Prem Verified</p>
            <p className="text-[10px] text-emerald-700/70 dark:text-emerald-300/60">Authentication handled locally — no cloud access</p>
          </div>
          <LockKey className="ml-auto h-4 w-4 shrink-0 text-emerald-500/50" />
        </div>
      </form>

      <AnimatePresence>
        {(error ?? notice) && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className={`mt-3 rounded-2xl border px-4 py-3 text-sm ${
              error
                ? error.startsWith('⚠️')
                  ? 'border-amber-500/30 bg-amber-400/10 text-amber-700 dark:border-amber-300/20 dark:text-amber-100'
                  : 'border-red-500/30 bg-red-400/10 text-red-700 dark:border-red-300/20 dark:text-red-100'
                : 'border-cyan-500/30 bg-cyan-200/10 text-cyan-700 dark:border-cyan-200/20 dark:text-cyan-50'
            }`}
          >
            {error ?? notice}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-4 flex items-center justify-end text-xs">
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-400/10 px-2.5 py-1 text-[11px] font-semibold text-amber-700 dark:border-amber-300/20 dark:text-amber-100/80">
          New user? Contact your admin
        </span>
      </div>

      {/* For development/testing only. Remove or disable in production. */}
      {import.meta.env.DEV && (
        <div className="mt-5 rounded-2xl border border-dashed border-border bg-muted/30 p-3 text-xs text-muted-foreground dark:border-white/15 dark:bg-white/[0.045] dark:text-white/50">
          <div className="flex items-center justify-between gap-3">
            <p className="font-mono uppercase tracking-widest text-cyan-700 dark:text-cyan-100/80">Dev test access</p>
            <button
              type="button"
              disabled={loading}
              onClick={handleTestLogin}
              className="rounded-full bg-cyan-200 px-3 py-1.5 font-black text-slate-950 disabled:opacity-50"
            >
              Sign in as Tester
            </button>
          </div>
          <p className="mt-2 font-mono">
            user: {TEST_CREDS.username} / pass: {TEST_CREDS.password}
          </p>
        </div>
      )}
    </AuthLayout>
  );
}
