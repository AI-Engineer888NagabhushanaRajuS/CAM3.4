import { useCallback, useEffect, useState } from 'react';
import { Cloud, Cpu, Sparkle } from '@phosphor-icons/react';
import { backendUrl } from '@/config/endpoints';
import { getSessionToken } from '@/lib/session';
import { cn } from '@/lib/utils';
import type { ChatProviderMode, ChatProvidersInfo } from '@/lib/chatContract';

interface ProviderSwitchProps {
  mode: ChatProviderMode;
  onChange: (mode: ChatProviderMode) => void;
  /** Opens Settings on the model providers, where the OpenRouter key is saved. */
  onOpenSettings?: () => void;
}

/** What the daemon can offer right now (is an OpenRouter key saved, which models); null until it answers or when it cannot. */
function useProviders(): ChatProvidersInfo | null {
  const [info, setInfo] = useState<ChatProvidersInfo | null>(null);
  const load = useCallback(async () => {
    try {
      const token = getSessionToken();
      const res = await fetch(backendUrl('/api/chat/providers'), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (res.ok) setInfo((await res.json()) as ChatProvidersInfo);
    } catch {
      setInfo(null); // daemon down: the switch still works, it just cannot show key status
    }
  }, []);
  useEffect(() => {
    void load();
    window.addEventListener('focus', load); // back from Settings after saving a key
    return () => window.removeEventListener('focus', load);
  }, [load]);
  return info;
}

const OPTIONS = [
  { mode: 'auto' as const, label: 'Auto', Icon: Sparkle },
  { mode: 'local' as const, label: 'Local', Icon: Cpu },
  { mode: 'openrouter' as const, label: 'OpenRouter', Icon: Cloud },
];

/** Which model answers: Local (Ollama, stays on this machine), OpenRouter (cloud, needs the key from Settings) or Auto. */
export function ProviderSwitch({ mode, onChange, onOpenSettings }: ProviderSwitchProps) {
  const info = useProviders();
  const noKey = info !== null && !info.openrouter.hasKey;

  const hint = (m: ChatProviderMode): string => {
    if (m === 'local') return `Local: ${info?.local.model ?? 'Ollama'} runs on this machine; nothing leaves it.`;
    if (m === 'openrouter') {
      if (noKey) return 'OpenRouter: no API key saved yet. Choosing it opens Settings to add one.';
      return `OpenRouter: ${info?.openrouter.model ?? 'cloud model'}. The RFQ rows used for an answer are sent to OpenRouter.`;
    }
    return noKey ? 'Auto: no OpenRouter key saved, so the local model answers.' : 'Auto: OpenRouter answers, the local model is the fallback.';
  };

  const pick = (m: ChatProviderMode) => {
    if (m === 'openrouter' && noKey) {
      onOpenSettings?.();
      return;
    }
    onChange(m);
  };

  return (
    <div role="radiogroup" aria-label="Model provider" className="inline-flex items-center rounded-full border border-border bg-muted/40 p-0.5">
      {OPTIONS.map(({ mode: m, label, Icon }) => (
        <button
          key={m}
          type="button"
          role="radio"
          aria-checked={mode === m}
          title={hint(m)}
          onClick={() => pick(m)}
          className={cn(
            'inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            mode === m ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Icon className="h-3.5 w-3.5" weight={mode === m ? 'fill' : 'regular'} aria-hidden />
          {label}
          {m === 'openrouter' && noKey && <span className="sr-only"> (no API key saved)</span>}
          {m === 'openrouter' && noKey && <span aria-hidden className="ml-0.5 h-1.5 w-1.5 rounded-full bg-amber-500" />}
        </button>
      ))}
    </div>
  );
}
