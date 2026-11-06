import { CheckCircle, Warning, WarningOctagon } from '@phosphor-icons/react';
import type { LintFinding } from '@/lib/manifestsCodegen';

/** Lint findings, errors first; each jumps to its JSON path in the editor. */
export function LintList({ findings, onJump }: { findings: LintFinding[]; onJump: (path: string) => void }) {
  if (findings.length === 0) {
    return <p className="flex items-center gap-2 p-3 text-sm text-muted-foreground" role="status"><CheckCircle className="h-4 w-4" aria-hidden="true" />Lint: no findings.</p>;
  }
  const sorted = [...findings].sort((a, b) => Number(b.level === 'error') - Number(a.level === 'error'));
  return (
    <ul aria-label="Lint findings">
      {sorted.map((f, i) => {
        const Icon = f.level === 'error' ? WarningOctagon : Warning;
        return (
          <li key={`${f.path}:${i}`}>
            <button
              type="button"
              onClick={() => onJump(f.path)}
              aria-label={`${f.level} at ${f.path || 'document'}: ${f.message}`}
              className="flex min-h-7 w-full items-baseline gap-2 px-3 py-1 text-left text-xs hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
            >
              <span className={`inline-flex shrink-0 items-center gap-1 font-semibold uppercase ${f.level === 'error' ? 'text-destructive' : 'text-amber-700 dark:text-amber-400'}`}>
                <Icon className="h-3.5 w-3.5" weight="fill" aria-hidden="true" />{f.level}
              </span>
              <code className="shrink-0 rounded bg-muted px-1 font-mono text-[11px]">{f.path || '(document)'}</code>
              <span>{f.message}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
