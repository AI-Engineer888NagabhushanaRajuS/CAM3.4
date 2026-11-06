import { CheckCircle, WarningOctagon } from '@phosphor-icons/react';
import type { Validation } from '@/lib/manifestsApi';

/** The server's validation result; each error jumps to its line in the editor. */
export function ValidationList({ validation, onJump }: { validation: Validation | null; onJump: (path: string) => void }) {
  if (!validation) return null;
  if (validation.ok && validation.errors.length === 0) {
    return (
      <p className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground" role="status">
        <CheckCircle className="h-4 w-4 text-emerald-600 dark:text-emerald-400" weight="fill" aria-hidden="true" />
        Server validation: no problems.
      </p>
    );
  }
  return (
    <section aria-label="Validation problems" className="max-h-40 overflow-y-auto">
      <h3 className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-destructive">
        <WarningOctagon className="h-4 w-4" weight="fill" aria-hidden="true" />
        {validation.errors.length} validation problem{validation.errors.length === 1 ? '' : 's'}
      </h3>
      <ul>
        {validation.errors.map((e, i) => (
          <li key={`${e.path}:${i}`}>
            <button
              type="button"
              onClick={() => onJump(e.path)}
              className="flex min-h-6 w-full items-baseline gap-2 px-3 py-1 text-left text-xs hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
              aria-label={`Go to ${e.path || 'document'}: ${e.message}`}
            >
              <code className="shrink-0 rounded bg-muted px-1 font-mono text-[11px]">{e.path || '(document)'}</code>
              <span className="text-foreground">{e.message}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
