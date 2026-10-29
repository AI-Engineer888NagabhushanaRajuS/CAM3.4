import type { Config } from 'tailwindcss';
import tailwindcssAnimate from 'tailwindcss-animate';
import tailwindcssTypography from '@tailwindcss/typography';

const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // EMS RFQ global design system (WCAG 2.2 AA), sourced from CSS variables
        // in globals.css. `<alpha-value>` lets Tailwind inject opacity modifiers
        // (e.g. bg-primary/90) at build time — required for the doc's own button/
        // pill examples to render at anything other than full opacity.
        background: 'hsl(var(--background) / <alpha-value>)',
        foreground: 'hsl(var(--foreground) / <alpha-value>)',
        card: {
          DEFAULT: 'hsl(var(--card) / <alpha-value>)',
          foreground: 'hsl(var(--card-foreground) / <alpha-value>)',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover) / <alpha-value>)',
          foreground: 'hsl(var(--popover-foreground) / <alpha-value>)',
        },
        surface: {
          DEFAULT: 'hsl(var(--surface) / <alpha-value>)',
          2: 'hsl(var(--surface-2) / <alpha-value>)',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary) / <alpha-value>)',
          foreground: 'hsl(var(--primary-foreground) / <alpha-value>)',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary) / <alpha-value>)',
          foreground: 'hsl(var(--secondary-foreground) / <alpha-value>)',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted) / <alpha-value>)',
          foreground: 'hsl(var(--muted-foreground) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent) / <alpha-value>)',
          foreground: 'hsl(var(--accent-foreground) / <alpha-value>)',
          hover: 'hsl(var(--accent-foreground) / <alpha-value>)',
          blue: '#3397FC', // Keep for backward compatibility
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive) / <alpha-value>)',
          foreground: 'hsl(var(--destructive-foreground) / <alpha-value>)',
        },
        brand: {
          DEFAULT: 'hsl(var(--brand) / <alpha-value>)',
          foreground: 'hsl(var(--brand-foreground) / <alpha-value>)',
        },
        link: 'hsl(var(--link) / <alpha-value>)',
        // border/input hold full rgba(...) values directly (translucent white
        // overlays, not opaque hues) — no hsl() wrapper, no <alpha-value>.
        border: 'var(--border)',
        input: 'var(--input)',
        ring: 'hsl(var(--ring) / <alpha-value>)',
        'background-card': 'hsl(var(--card) / <alpha-value>)',
        text: 'hsl(var(--foreground) / <alpha-value>)',
        'text-secondary': 'hsl(var(--foreground) / <alpha-value>)',
        'text-muted': 'hsl(var(--muted-foreground) / <alpha-value>)',
        danger: {
          DEFAULT: 'hsl(var(--destructive) / <alpha-value>)',
          foreground: 'hsl(var(--destructive-foreground) / <alpha-value>)',
        },
        warning: {
          DEFAULT: '#EE7909',
        },
        success: {
          DEFAULT: '#019E55',
        },
        'provider-bg': 'hsl(var(--provider-bg))',
        'provider-bg-active': 'hsl(var(--provider-bg-active))',
        'provider-bg-hover': 'hsl(var(--provider-bg-hover))',
        'provider-border-active': 'hsl(var(--provider-border-active))',
        'provider-accent': 'hsl(var(--provider-accent))',
        'provider-accent-text': 'hsl(var(--provider-accent-text))',
        'todo-progress-pending': 'hsl(var(--todo-progress-pending))',
        'todo-item-completed': 'hsl(var(--todo-item-completed))',
        'todo-item-in-progress': 'hsl(var(--todo-item-in-progress))',
      },
      boxShadow: {
        sm: '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 1px 2px -1px hsl(0 0% 0% / 0.10)',
        DEFAULT: '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 1px 2px -1px hsl(0 0% 0% / 0.10)',
        md: '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 2px 4px -1px hsl(0 0% 0% / 0.10)',
        lg: '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 4px 6px -1px hsl(0 0% 0% / 0.10)',
        xl: '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 8px 10px -1px hsl(0 0% 0% / 0.10)',
        '2xl': '0 1px 3px 0px hsl(0 0% 0% / 0.25)',
        card: '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 1px 2px -1px hsl(0 0% 0% / 0.10)',
        'card-hover': '0 1px 3px 0px hsl(0 0% 0% / 0.10), 0 4px 6px -1px hsl(0 0% 0% / 0.10)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        DEFAULT: 'var(--radius)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        '2xl': 'var(--radius-2xl)',
        '3xl': 'var(--radius-2xl)',
        card: 'var(--radius-lg)',
      },
      fontFamily: {
        sans: [
          'Geist',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        apparat: ['KMR Apparat', 'Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      transitionTimingFunction: {
        accomplish: 'cubic-bezier(0.64, 0, 0.78, 0)',
      },
      animation: {
        shimmer: 'shimmer 2s infinite',
        'spin-ccw': 'spinCcw 1s linear infinite',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        spinCcw: {
          '0%': { transform: 'rotate(360deg)' },
          '100%': { transform: 'rotate(0deg)' },
        },
      },
    },
  },
  plugins: [tailwindcssAnimate, tailwindcssTypography],
};

export default config;
