import { useEffect, useRef, useState } from 'react';
import type { ManifestKind } from '@/lib/manifestsApi';
import { generateTool, InvalidJsonError, lintManifest, type Codegen, type Lint } from '@/lib/manifestsCodegen';

export interface Preview {
  state: 'loading' | 'ready' | 'invalid' | 'error';
  lint: Lint | null;
  code: Codegen | null;
  message: string;
}
export const DEBOUNCE_MS = 600;

/** Lint + generated tool for the editor text, refreshed DEBOUNCE_MS after the last change; stale requests are aborted. */
export function usePreview(text: string, kind: ManifestKind, subSkillId: string | undefined): Preview {
  const [p, setP] = useState<Preview>({ state: 'loading', lint: null, code: null, message: '' });
  const first = useRef(true);

  useEffect(() => {
    try { JSON.parse(text); } catch (e) {
      setP((o) => ({ ...o, state: 'invalid', message: e instanceof Error ? e.message : 'invalid JSON' }));
      return;
    }
    const ctl = new AbortController();
    const delay = first.current ? 0 : DEBOUNCE_MS;
    first.current = false;
    setP((o) => ({ ...o, state: 'loading' }));
    const timer = setTimeout(() => {
      Promise.all([lintManifest(text, kind, ctl.signal), generateTool(text, subSkillId, ctl.signal)])
        .then(([lint, code]) => { if (!ctl.signal.aborted) setP({ state: 'ready', lint, code, message: '' }); })
        .catch((e: unknown) => {
          if (ctl.signal.aborted) return;
          const msg = e instanceof Error ? e.message : 'unknown error';
          setP((o) => ({ ...o, state: e instanceof InvalidJsonError ? 'invalid' : 'error', message: msg }));
        });
    }, delay);
    return () => { clearTimeout(timer); ctl.abort(); };
  }, [text, kind, subSkillId]);

  return p;
}
