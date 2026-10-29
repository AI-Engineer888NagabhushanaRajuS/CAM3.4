import { motion } from 'framer-motion';
import bullmquoteLogo from '/assets/bullmquote-logo.png';

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

        {/* BuLLMQuote logo -- a wide wordmark, sized by height with width left
            auto so it doesn't overflow the half-viewport-width panel. The
            wordmark's "Quote" half is rendered in solid black, so on a dark
            background it disappears entirely -- the dark:bg-white plate
            below gives it a light backdrop to stay legible without touching
            the source image. */}
        <motion.div
          {...fadeUp(0.1)}
          className="rounded-2xl drop-shadow-[0_0_40px_rgba(34,211,238,0.35)] dark:bg-white dark:px-6 dark:py-3.5 dark:shadow-[0_20px_50px_-20px_rgba(0,0,0,0.7)]"
        >
          <img src={bullmquoteLogo} alt="BuLLMQuote" className="h-16 w-auto object-contain" />
        </motion.div>

        {/* Tagline */}
        <motion.p
          {...fadeUp(0.6)}
          className="text-sm font-semibold uppercase tracking-[0.28em] text-muted-foreground dark:text-white/40"
        >
          Powered by SRIM
        </motion.p>
      </div>


    </div>
  );
}
