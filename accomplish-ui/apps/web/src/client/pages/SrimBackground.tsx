import { motion } from 'framer-motion';
import { BrandMark } from '@/components/BrandMark';

const EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 24 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.7, delay, ease: EASE },
});

export function SrimBackground() {
  return (
    <div className="relative flex h-full min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-10 py-10">

      {/* Ambient glow orbs — translucent, read fine on either background */}
      <div className="pointer-events-none absolute left-1/4 top-1/4 h-96 w-96 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan-400/10 blur-[90px]" />
      <div className="pointer-events-none absolute bottom-1/4 right-1/4 h-80 w-80 translate-x-1/2 translate-y-1/2 rounded-full bg-amber-400/8 blur-[80px]" />
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-[28rem] w-[28rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-500/6 blur-[100px]" />

      {/* Center branding stack */}
      <div className="relative z-10 flex flex-col items-center gap-8 text-center">

        {/* Product name as text, so it stays legible on both themes. */}
        <motion.div {...fadeUp(0.1)} className="drop-shadow-[0_0_40px_rgba(34,211,238,0.35)]">
          <BrandMark className="text-6xl" />
        </motion.div>

        {/* Tagline */}
        <motion.p
          {...fadeUp(0.6)}
          className="text-sm font-semibold uppercase tracking-[0.28em] text-muted-foreground dark:text-white/40"
        >
          BOM automation for Centum
        </motion.p>
      </div>


    </div>
  );
}
