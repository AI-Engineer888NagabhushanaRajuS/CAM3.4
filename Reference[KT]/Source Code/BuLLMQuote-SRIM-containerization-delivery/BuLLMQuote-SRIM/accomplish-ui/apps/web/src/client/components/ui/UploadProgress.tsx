import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';

interface UploadProgressProps {
  /** 0-100 */
  value: number;
  className?: string;
}

/** Thin animated progress bar for file upload states. */
export function UploadProgress({ value, className }: UploadProgressProps) {
  const clamped = Math.min(100, Math.max(0, value));

  return (
    <div
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-slate-800', className)}
    >
      <motion.div
        className="h-full rounded-full bg-primary"
        initial={{ width: 0 }}
        animate={{ width: `${clamped}%` }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      />
    </div>
  );
}
