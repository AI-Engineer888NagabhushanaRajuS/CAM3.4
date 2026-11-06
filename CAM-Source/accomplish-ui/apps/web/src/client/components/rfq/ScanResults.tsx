import { motion, useReducedMotion } from 'framer-motion';
import { CheckCircle, ShieldWarning, WarningCircle, XCircle } from '@phosphor-icons/react';
import { cn } from '@/lib/utils';
import { formatBytes, type ScanResponse, type ScanResult, type Verdict } from '@/lib/rfqAttachments';

const CHIP: Record<Verdict, string> = {
  clean: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  threat: 'border-destructive/30 bg-destructive/10 text-destructive',
  error: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
};
const VERDICT_TEXT: Record<Verdict, string> = { clean: 'clean', threat: 'threat', error: 'could not scan' };

function EngineChip({ label, verdict, detail }: { label: string; verdict: Verdict; detail?: string }) {
  return (
    <span title={detail || undefined} className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', CHIP[verdict])}>
      {label}: {VERDICT_TEXT[verdict]}
    </span>
  );
}

/** The verdict lands with a small pop: the icon springs in as its row appears (still under reduced motion). */
function Decision({ result, still }: { result: ScanResult; still: boolean }) {
  const icon = result.decision === 'released' ? <CheckCircle className="h-5 w-5 text-emerald-600 dark:text-emerald-400" weight="fill" aria-hidden />
    : result.decision === 'quarantined' ? <XCircle className="h-5 w-5 text-destructive" weight="fill" aria-hidden />
    : <WarningCircle className="h-5 w-5 text-amber-600 dark:text-amber-400" weight="fill" aria-hidden />;
  return (
    <motion.span className="shrink-0" initial={still ? false : { scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: 'spring', stiffness: 380, damping: 18, delay: 0.1 }}>
      {icon}
    </motion.span>
  );
}

/** What the bridge found inside a released file: its role, why, and what would make the run reject it. */
function RoleLine({ r }: { r: ScanResult }) {
  if (r.decision !== 'released' || !r.role || r.role === 'document') return null;
  const bad = r.role === 'bom' || r.role === 'unknown';
  return (
    <div className="mt-1.5 space-y-1">
      <span
        title={r.role_reason}
        className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
          bad ? 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400' : 'border-primary/30 bg-primary/10 text-primary')}
      >
        Detected: {r.role_label}
      </span>
      {r.problems?.map((p) => <p key={p} className="text-xs text-amber-800 dark:text-amber-300">{p}</p>)}
    </div>
  );
}

/** Real verdicts from the scan service, one row per file: both engines and the twin decision. */
export function ScanResults({ response }: { response: ScanResponse }) {
  const still = useReducedMotion() ?? false;
  const count = (d: ScanResult['decision']) => response.results.filter((r) => r.decision === d).length;
  const down = response.engines.filter((e) => e.status !== 'ok');
  return (
    <div className="space-y-3">
      <p role="status" className="text-sm text-foreground">
        <strong>{count('released')}</strong> of {response.results.length} released
        {count('quarantined') > 0 && <> · <strong className="text-destructive">{count('quarantined')}</strong> quarantined</>}
        {count('error') > 0 && <> · <strong className="text-amber-700 dark:text-amber-400">{count('error')}</strong> held</>}
      </p>
      {down.length > 0 && (
        <p className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-foreground">
          <ShieldWarning className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          {down.map((e) => e.label).join(' and ')} {down.length > 1 ? 'are' : 'is'} unavailable. Files are held, not released, until both engines can check them.
        </p>
      )}
      <ul className="max-h-[46dvh] divide-y divide-border overflow-y-auto rounded-xl border border-border">
        {response.results.map((r, i) => (
          <motion.li
            key={`${r.name}-${r.sha256}`}
            className="flex items-start gap-3 px-3 py-2.5"
            initial={still ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: still ? 0 : Math.min(i, 10) * 0.06, duration: 0.25 }}
          >
            <Decision result={r} still={still} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground" title={r.name}>
                {r.name} <span className="text-xs font-normal text-muted-foreground">{formatBytes(r.size)}</span>
              </p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <EngineChip label="BuLL*Sav (ClamAV)" verdict={r.clamav.verdict} detail={r.clamav.detail ?? undefined} />
                <EngineChip label="Repel Shield" verdict={r.repel.verdict} detail={[...(r.repel.flags ?? []), r.repel.detail].filter(Boolean).join(', ')} />
              </div>
              <RoleLine r={r} />
              {r.decision !== 'released' && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.reason ?? (r.repel.flags?.length ? `Repel flags: ${r.repel.flags.join(', ')}` : 'Not released')}
                </p>
              )}
            </div>
            <span className="shrink-0 pt-0.5 text-[11px] uppercase tracking-wide text-muted-foreground">
              {r.decision === 'released' ? 'Released' : r.decision === 'quarantined' ? 'Quarantined' : 'Held'}
            </span>
          </motion.li>
        ))}
      </ul>
    </div>
  );
}
