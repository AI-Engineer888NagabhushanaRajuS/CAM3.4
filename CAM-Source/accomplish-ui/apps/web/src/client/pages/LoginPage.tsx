import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, Eye, EyeSlash, Moon, Sun } from '@phosphor-icons/react';
import { loginWithCredentials } from '@/lib/session';
import type { UserRole } from '@/lib/session';
import { useTheme } from '@/hooks/useTheme';
import './login.css';

// Login page copied from the RFQ wireframe (ParvithaCGowda29/RFQ_automation, src/LoginPage.tsx + login.css).
// Only the sign-in itself differs: it checks the real account (daemon, Postgres users table), not a demo.

const SHOWCASE_MESSAGES = [
  { headline: 'From RFQ package to quote review.', flow: 'Upload files > Check the BOM > Review the quote' },
  { headline: 'Keep feasibility and parts risks in view.', flow: 'Buildability > EOL parts > Lead times' },
  { headline: 'Follow the work through to final approval.', flow: 'RFQ intake > Costed BOM > Quote approval' },
];

// Admins land on the Organization master, FDE accounts on the FDE staging pipeline, everyone else on the RFQ workspace.
const ADMIN_ROUTE = '/organization';
const FDE_ROUTE = '/workflow-builder';
const USER_ROUTE = '/';

function BrandBlock({ mobile = false, dark }: { mobile?: boolean; dark: boolean }) {
  const logo = mobile && !dark ? '/assets/centum-logo-wireframe.png' : '/assets/centum-logo-dark.png';
  return (
    <div className={`login-brand-block${mobile ? ' login-brand-mobile' : ''}`} aria-label="Centum Automation Modules, CAM4, powered by BuLLM">
      <img className="login-centum-logo" src={logo} alt="Centum" />
      <span className="login-brand-name">CENTUM AUTOMATION MODULES</span>
      <span className="login-brand-version">CAM4</span>
      <span className="login-brand-powered">POWERED BY <strong><span className="login-bullm-bu">Bu</span><span className="login-bullm-llm">LLM</span></strong></span>
    </div>
  );
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark, toggleTheme } = useTheme();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [messageIndex, setMessageIndex] = useState(0);
  const [carouselHeld, setCarouselHeld] = useState(false);
  const [pageHidden, setPageHidden] = useState(() => document.hidden);
  const [notice, setNotice] = useState<string | null>(() => {
    const state = location.state as { loggedOut?: boolean } | null;
    return state?.loggedOut ? 'You have been signed out successfully.' : null;
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onVisibility = () => setPageHidden(document.hidden);
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);
  useEffect(() => {
    if (carouselHeld || pageHidden || SHOWCASE_MESSAGES.length < 2) return;
    const timer = window.setInterval(() => setMessageIndex((index) => (index + 1) % SHOWCASE_MESSAGES.length), 6000);
    return () => window.clearInterval(timer);
  }, [carouselHeld, pageHidden]);

  const classifyError = (err: unknown): string => {
    const msg = (err instanceof Error ? err.message : String(err)).toLowerCase();
    if (msg.includes('fetch') || msg.includes('network') || msg.includes('refused') || msg.includes('failed to fetch')) {
      return 'Cannot reach the sign-in server. Check your network or firewall.';
    }
    if (msg.includes('inactive') || msg.includes('disabled') || msg.includes('403')) {
      return 'This account is inactive. Contact your administrator.';
    }
    return 'Invalid username or password. Please try again.';
  };

  const routeAfterLogin = (role: UserRole) => {
    const destination = role === 'admin' ? ADMIN_ROUTE : role === 'fde' ? FDE_ROUTE : USER_ROUTE;
    void navigate(destination, { replace: true });
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (!identifier.trim() || !password.trim()) {
      setError('Enter your username or email and password.');
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    loginWithCredentials(identifier.trim(), password)
      .then(({ role }) => {
        setPassword('');
        routeAfterLogin(role);
      })
      .catch((err) => setError(classifyError(err)))
      .finally(() => setBusy(false));
  };

  // Dev server only: one-click sign-in for testing. The accounts and passwords come from apps/web/.env.local (git-ignored), never from source.
  const quickSignIn = (username: string, pass: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    loginWithCredentials(username, pass)
      .then(({ role }) => routeAfterLogin(role))
      .catch((err) => setError(classifyError(err)))
      .finally(() => setBusy(false));
  };
  const testerUser = import.meta.env.VITE_DEV_TESTER_USER ?? '';
  const testerPass = import.meta.env.VITE_DEV_TESTER_PASSWORD ?? '';
  const adminUser = import.meta.env.VITE_DEV_ADMIN_USER ?? '';
  const adminPass = import.meta.env.VITE_DEV_ADMIN_PASSWORD ?? '';

  const theme = isDark ? 'dark' : 'light';

  return (
    <main className="login-page" data-theme={theme}>
      <div className="login-frame">
        <section className="login-showcase" aria-label="CAM RFQ workspace">
          <div className="login-showcase-inner">
            <BrandBlock dark={isDark} />
            <div className="login-story" onMouseEnter={() => setCarouselHeld(true)} onMouseLeave={() => setCarouselHeld(false)}>
              <div className="login-story-copy" aria-live="polite" key={messageIndex}>
                <span className="login-story-label">BUILT AROUND YOUR RFQ</span>
                <h2>{SHOWCASE_MESSAGES[messageIndex].headline}</h2>
                <p>{SHOWCASE_MESSAGES[messageIndex].flow}</p>
              </div>
              <div className="login-story-indicators" aria-hidden="true">
                {SHOWCASE_MESSAGES.map((message, index) => <span key={message.headline} className={`login-story-dot${index === messageIndex ? ' is-active' : ''}`} />)}
              </div>
            </div>
            <div className="login-showcase-foot" aria-label="Workflow areas">
              <span className="login-foot-chip">RFQ intake</span><span className="login-foot-chip">BOM analysis</span><span className="login-foot-chip">Quote review</span>
            </div>
          </div>
        </section>

        <section className="login-form-panel" aria-labelledby="login-title">
          <button className="login-theme-toggle" type="button" onClick={toggleTheme}
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}>
            {isDark ? <Sun size={17} /> : <Moon size={17} />}
          </button>
          <div className="login-form-content">
            <BrandBlock mobile dark={isDark} />
            <div className="login-copy">
              <span className="login-eyebrow">YOUR RFQ WORKSPACE</span>
              <h2 id="login-title">Welcome back</h2>
            </div>
            <form className="login-form" onSubmit={submit}>
              <label htmlFor="cam-login-email">Username or email</label>
              <input id="cam-login-email" type="text" autoComplete="username" placeholder="you@company.com"
                value={identifier} onChange={(event) => { setIdentifier(event.target.value); setError(null); }} required disabled={busy} />
              <div className="login-password-label"><label htmlFor="cam-login-password">Password</label></div>
              <div className="login-password-wrap">
                <input id="cam-login-password" type={showPassword ? 'text' : 'password'} autoComplete="current-password"
                  placeholder="Enter password" value={password} onChange={(event) => { setPassword(event.target.value); setError(null); }} required disabled={busy} />
                <button type="button" className="login-password-toggle" onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} disabled={busy}>
                  {showPassword ? <EyeSlash size={19} /> : <Eye size={19} />}
                </button>
              </div>
              <button className="login-submit" type="submit" disabled={busy}>
                {busy ? 'Signing in...' : <>Sign in <ArrowRight size={18} /></>}
              </button>
            </form>
            <AnimatePresence>
              {(error ?? notice) && (
                <motion.p
                  key={error ?? notice ?? ''}
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="login-demo-note"
                  role={error ? 'alert' : 'status'}
                >
                  {error ?? notice}
                </motion.p>
              )}
            </AnimatePresence>
            <div className="login-secure-note"><span className="login-secure-dot" /> Signed in against this site's accounts</div>
            {import.meta.env.DEV && (testerUser || adminUser) && (
              <div className="login-dev-quick" aria-label="Dev quick sign-in">
                {testerUser && (
                  <button type="button" className="login-dev-button" disabled={busy} onClick={() => quickSignIn(testerUser, testerPass)}>
                    Sign in as Tester
                  </button>
                )}
                {adminUser && (
                  <button type="button" className="login-dev-button" disabled={busy} onClick={() => quickSignIn(adminUser, adminPass)}>
                    Sign in as Admin
                  </button>
                )}
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
