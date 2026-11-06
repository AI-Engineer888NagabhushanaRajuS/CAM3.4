import { CheckCircle, PencilSimple, Question } from '@phosphor-icons/react';
import { cn } from '@/lib/utils';

/** DRAFT / APPROVED as icon + text, never colour alone. */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const label = (status || 'unknown').toUpperCase();
  const Icon = label === 'APPROVED' ? CheckCircle : label === 'DRAFT' ? PencilSimple : Question;
  const tone = label === 'APPROVED' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
    : label === 'DRAFT' ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400'
      : 'border-border bg-muted text-muted-foreground';
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-md border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide', tone, className)}>
      <Icon className="h-3 w-3" weight="bold" aria-hidden="true" />
      {label}
    </span>
  );
}
