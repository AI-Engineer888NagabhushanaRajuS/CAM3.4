import {
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from '@/components/ui/dropdown-menu';
import {
  DEFAULT_PROVIDERS,
  PROVIDER_META,
  getModelDisplayName,
} from '@accomplish_ai/agent-core/common';
import type { ConnectedProvider, ProviderId } from '@accomplish_ai/agent-core/common';
import { useEffect, useState } from 'react';
import { getAccomplish } from '@/lib/accomplish';

interface ProviderSubMenuProps {
  providerId: ProviderId;
  provider: ConnectedProvider;
  onSelectModel: (providerId: ProviderId, modelId: string) => Promise<void>;
  disabled: boolean;
}

export function ProviderSubMenu({
  providerId,
  provider,
  onSelectModel,
  disabled,
}: ProviderSubMenuProps) {
  const providerName = PROVIDER_META[providerId]?.name ?? providerId;

  // If availableModels is defined (even empty) use it; only fall back to static config when undefined
  const stored: Array<{ id: string; displayName: string }> =
    provider.availableModels !== undefined
      ? provider.availableModels.map((m) => ({ id: m.id, displayName: m.name }))
      : (DEFAULT_PROVIDERS.find((p) => p.id === providerId)?.models ?? []).map((m) => ({
          id: m.fullId,
          displayName: getModelDisplayName(m.fullId),
        }));

  // A connected OpenRouter whose stored list is empty: ask the daemon for the models it offers, so the choice is there.
  const [fetched, setFetched] = useState<Array<{ id: string; displayName: string }> | null>(null);
  useEffect(() => {
    if (providerId !== 'openrouter' || stored.length > 0) return;
    let alive = true;
    getAccomplish().fetchOpenRouterModels()
      .then((r) => {
        if (alive && r.success && r.models) {
          setFetched(r.models.map((m) => ({ id: `openrouter/${m.id}`, displayName: m.name })));
        }
      })
      .catch(() => undefined);
    return () => { alive = false; };
  }, [providerId, stored.length]);
  const models = stored.length > 0 ? stored : (fetched ?? []);

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger
        disabled={disabled}
        className="gap-2 px-3 py-2 text-sm cursor-pointer"
      >
        {providerName}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="w-48">
        {models.length === 0 ? (
          <DropdownMenuItem disabled className="px-3 py-2 text-sm text-muted-foreground">
            No models available
          </DropdownMenuItem>
        ) : (
          models.map((model) => (
            <DropdownMenuItem
              key={model.id}
              disabled={disabled}
              className="px-3 py-2 text-sm cursor-pointer"
              onClick={() => void onSelectModel(providerId, model.id)}
            >
              {model.displayName}
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
