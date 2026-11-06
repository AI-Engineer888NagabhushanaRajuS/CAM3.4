import { cn } from '@/lib/utils';

/** The product name as text: sharp at any size and follows the light/dark theme. Replaces the old BuLLMQuote logo image. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-baseline gap-[0.3em] font-semibold leading-none tracking-tight text-foreground', className)}>
      <span>CAM</span>
      <span className="text-primary">3.4</span>
    </span>
  );
}
