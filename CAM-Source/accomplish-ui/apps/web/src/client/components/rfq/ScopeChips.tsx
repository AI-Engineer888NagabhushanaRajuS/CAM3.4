import { Stack, X } from '@phosphor-icons/react';
import type { ChatScope } from '@/lib/chatContract';

interface ScopeChipsProps {
  scope: ChatScope;
  /** Remove one RFQ, or 'all' for the All context chip. */
  onRemove: (rfq: string | 'all') => void;
}

const chip = 'inline-flex max-w-[220px] items-center gap-1 rounded-full bg-muted py-0.5 pl-2.5 pr-1 text-xs font-medium text-foreground';

/** What the conversation is about, as removable chips. Removing the last one returns to normal chat (no RFQ chosen). */
export function ScopeChips({ scope, onRemove }: ScopeChipsProps) {
  const chips = scope.mode === 'rfqs' ? scope.rfqIds : [];
  if (scope.mode === 'all') {
    chips.push('all');
  }
  if (chips.length === 0) {
    return <span className="inline-flex shrink-0 items-center rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">No RFQ chosen</span>;
  }
  return (
    <ul className="flex min-w-0 flex-wrap items-center gap-1" aria-label="Conversation scope">
      {chips.map((id) => {
        const label = id === 'all' ? 'All context' : id;
        return (
          <li key={id} className={chip}>
            {id === 'all' && <Stack className="h-3 w-3 shrink-0 text-primary" weight="fill" aria-hidden />}
            <span className="truncate" title={label}>{label}</span>
            <button
              type="button"
              aria-label={`Remove ${label} from scope`}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-background/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onRemove(id)}
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
