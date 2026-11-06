import { motion, useReducedMotion } from 'framer-motion';
import { FileText, ShieldCheck } from '@phosphor-icons/react';
import { formatBytes } from '@/lib/rfqAttachments';

interface Props {
  /** The files of the wave being scanned right now. */
  files: File[];
  wave: { n: number; of: number };
  /** All files of the pick, for the count line. */
  total: number;
}

/**
 * What the scan is really doing, drawn: the wave in flight (n of m, a bar that fills as waves finish), and a light sweeping over
 * each file while both engines hold it. There are no per-engine percentages: the service answers once per wave, so nothing
 * finer is shown. With reduced motion the sweep and the pulse stop and the state is carried by the words.
 */
export function ScanProgress({ files, wave, total }: Props) {
  const still = useReducedMotion();
  const done = (wave.n - 1) / wave.of;
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <div className="flex items-center gap-3">
        <motion.span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary"
          animate={still ? undefined : { scale: [1, 1.08, 1], boxShadow: ['0 0 0 0 rgb(0 0 0 / 0)', '0 0 0 6px rgb(0 0 0 / 0.05)', '0 0 0 0 rgb(0 0 0 / 0)'] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
        >
          <ShieldCheck className="h-5 w-5" weight="fill" aria-hidden />
        </motion.span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground">
            {wave.of > 1 ? `Wave ${wave.n} of ${wave.of}: ` : ''}Quarantining and scanning {files.length} {files.length === 1 ? 'file' : 'files'} with both engines
          </p>
          <p className="text-xs text-muted-foreground">{total} {total === 1 ? 'file' : 'files'} in this pick. A file is released only when BuLL*Sav and Repel Shield both clear it.</p>
        </div>
      </div>

      <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        <motion.div
          className="relative h-full rounded-full bg-primary"
          initial={false}
          animate={{ width: `${Math.max(done, 0.06) * 100}%` }}
          transition={still ? { duration: 0 } : { type: 'spring', stiffness: 120, damping: 20 }}
        />
      </div>

      <ul className="space-y-1.5">
        {files.slice(0, 12).map((f, i) => (
          <motion.li
            key={`${f.name}-${f.size}`}
            className="relative flex items-center gap-2 overflow-hidden rounded-lg border border-border bg-card px-3 py-2 text-xs"
            initial={still ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: still ? 0 : Math.min(i, 8) * 0.05, duration: 0.25 }}
          >
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-foreground" title={f.name}>{f.name}</span>
            <span className="shrink-0 text-muted-foreground">{formatBytes(f.size)}</span>
            <span className="shrink-0 font-medium text-primary">scanning</span>
            {!still && (
              <motion.span
                aria-hidden
                className="pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-primary/15 to-transparent"
                animate={{ x: ['-100%', '320%'] }}
                transition={{ duration: 1.6, repeat: Infinity, ease: 'linear', delay: Math.min(i, 8) * 0.12 }}
              />
            )}
          </motion.li>
        ))}
        {files.length > 12 && <li className="px-1 text-xs text-muted-foreground">and {files.length - 12} more in this wave</li>}
      </ul>
    </div>
  );
}
