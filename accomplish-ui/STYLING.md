# EMS RFQ Automation Control Plane — CSS Styling Guide

This document is the complete styling reference for the **EMS RFQ Automation Control Plane** UI.

The entire design system is authored in `src/styles.css` using **Tailwind CSS v4**'s CSS-first configuration model (`@theme`, `@utility`, `@custom-variant`). There is no `tailwind.config.js`.

---

## 1. Architecture Overview

| Item | Value |
|------|-------|
| Entry stylesheet | `src/styles.css` |
| Tailwind version | v4 (CSS-first) |
| Config file | **None** — tokens live in CSS |
| Utility generation | `@theme inline` + `@utility` |
| Dark mode | Always-on dark theme via `:root` tokens |
| Font loading | Via `<link>` in `src/routes/__root.tsx` (not `@import`) |

### Top of `src/styles.css`

```css
@import "tailwindcss" source(none);
@source "../src";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));
```

> `source(none)` disables automatic source scanning from the entry file. The `@source "../src"` directive explicitly tells Tailwind to scan all files in `src/` for class names.

---

## 2. Theme Tokens (`:root`)

All semantic tokens are defined in `:root`. These map to shadcn-compatible color tokens in `@theme inline`.

### 2.1 Core Palette

| Token | Approximate Hex | Usage |
|-------|-----------------|-------|
| `--background` | `#0B0F17` | App/page background |
| `--foreground` | `#F8FAFC` | Primary text color |
| `--card` | `#1E293B` | Cards, panels, table containers |
| `--card-foreground` | `#F8FAFC` | Text on card surfaces |
| `--popover` | `#151B29` | Popover/dropdown surfaces |
| `--popover-foreground` | `#F8FAFC` | Text on popovers |
| `--surface` | `#151B29` | Sidebar, elevated panels |
| `--surface-2` | `#1E293B` | Secondary surfaces, scrollbar thumbs |
| `--primary` | `#6366F1` | Primary buttons, active states |
| `--primary-foreground` | `#FAFAFA` | Text on primary buttons |
| `--secondary` | `#1E293B` | Secondary buttons, muted containers |
| `--secondary-foreground` | `#F8FAFC` | Text on secondary surfaces |
| `--muted` | `#1E293B` | Muted backgrounds |
| `--muted-foreground` | `#94A3B8` | Secondary/muted text |
| `--accent` | `#1E293B` | Accent surfaces |
| `--accent-foreground` | `#F8FAFC` | Text on accent surfaces |
| `--destructive` | `#EF4444` | Destructive actions |
| `--destructive-foreground` | `#F8FAFC` | Text on destructive actions |
| `--border` | `rgba(255,255,255,0.09)` | Borders, dividers |
| `--input` | `rgba(255,255,255,0.12)` | Input field backgrounds |
| `--ring` | `#22D3EE` | Focus rings, brand highlights |
| `--link` | `#67E8F9` | Text links |
| `--brand` | `#5EEAD4` | Brand cyan/teal accent |
| `--brand-foreground` | `#0F172A` | Text on brand accent |

### 2.2 Radius Tokens

| Token | Formula | Value at default |
|-------|---------|------------------|
| `--radius` | base | `0.5rem` (8px) |
| `--radius-sm` | `radius - 4px` | `0.25rem` (4px) |
| `--radius-md` | `radius - 2px` | `0.375rem` (6px) |
| `--radius-lg` | `radius` | `0.5rem` (8px) |
| `--radius-xl` | `radius + 4px` | `0.75rem` (12px) |
| `--radius-2xl` | `radius + 8px` | `1rem` (16px) |

### 2.3 Admin Control Plane Layout Tokens

```css
--admin-sidebar-w: 300px;   /* Large screens (≥1024px) */
--admin-gutter: 1.25rem;     /* Gap between layout regions */
--admin-pad-x: 1.25rem;      /* Horizontal padding inside cards */
--admin-row-h: 2.25rem;      /* Standard control row height */
```

---

## 3. `@theme inline` Mapping

Tailwind v4 utilities are generated from these token declarations. Because they point to existing CSS variables, they use `@theme inline`:

```css
@theme inline {
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --radius-2xl: calc(var(--radius) + 8px);

  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-surface: var(--surface);
  --color-surface-2: var(--surface-2);
  --color-brand: var(--brand);
  --color-brand-foreground: var(--brand-foreground);
  --color-link: var(--link);

  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;
}
```

This enables classes like:

- `bg-background`, `bg-card`, `bg-surface`, `bg-brand`
- `text-foreground`, `text-muted-foreground`, `text-brand`
- `border-border`, `ring-ring`
- `font-mono`

---

## 4. Custom Utilities (`@utility`)

### 4.1 Layout Utilities

#### `.admin-container`

```css
@utility admin-container {
  margin-inline: auto;
  width: 100%;
  max-width: 1680px;
  padding-inline: var(--admin-gutter);
}
```

**Usage:** Wraps the entire app shell to keep it centered and bounded on ultra-wide displays.

```tsx
<div className="admin-container">
  ...
</div>
```

---

#### `.admin-grid`

```css
@utility admin-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--admin-gutter);
  align-items: start;

  @media (width >= 40rem) {
    grid-template-columns: 240px minmax(0, 1fr);
  }

  @media (width >= 64rem) {
    grid-template-columns: var(--admin-sidebar-w) minmax(0, 1fr);
  }
}
```

**Responsive behavior:**

| Breakpoint | Layout |
|------------|--------|
| `< 640px` | Single column stacked |
| `≥ 640px` | 240px sidebar + fluid content |
| `≥ 1024px` | 300px sidebar + fluid content |

**Usage:** The primary layout grid for all Admin Control Plane pages.

```tsx
<div className="admin-grid">
  <AdminSidebar />
  <main>...</main>
</div>
```

---

#### `.admin-panel`

```css
@utility admin-panel {
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--card);
}
```

**Usage:** Shared surface for sidebar and content cards. Gives consistent border radius, border, and background across panels.

```tsx
<aside className="admin-panel">...</aside>
<main className="admin-panel">...</main>
```

---

#### `.admin-pad-x`

```css
@utility admin-pad-x {
  padding-inline: var(--admin-pad-x);
}
```

**Usage:** Horizontal padding inside card headers, toolbars, and table cells. Keeps all internal alignment consistent.

```tsx
<header className="admin-pad-x">...</header>
<div className="admin-row admin-pad-x">...</div>
```

---

#### `.admin-row`

```css
@utility admin-row {
  display: flex;
  align-items: center;
  min-height: var(--admin-row-h);
  border-radius: var(--radius-md);
  white-space: nowrap;
}
```

**Usage:** Standard height for navigation rows, control rows, and list items. `2.25rem` (36px) minimum height.

```tsx
<a className="admin-row admin-pad-x">Nav Item</a>
```

---

### 4.2 Status Pill Utilities

All pills share the `.pill-base` shape and add a color scheme via `.pill-*`.

```css
@utility pill-base {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  border-radius: 9999px;
  border-width: 1px;
  padding: 0.125rem 0.625rem;
  font-size: 0.75rem;
  line-height: 1.25rem;
  font-weight: 500;
  white-space: nowrap;
}
```

#### Color variants

| Utility | Text color | Background | Border | Typical use |
|---------|------------|------------|--------|-------------|
| `.pill-indigo` | indigo-300 | indigo-500/18 | indigo-500/40 | Primary labels |
| `.pill-emerald` | emerald-300 | emerald-500/16 | emerald-500/38 | Active, success |
| `.pill-green` | green-300 | green-500/15 | green-500/35 | Success, valid |
| `.pill-purple` | purple-300 | purple-500/16 | purple-500/38 | AI, premium |
| `.pill-amber` | amber-300 | amber-500/16 | amber-500/38 | Warning, pending |
| `.pill-rose` | rose-300 | rose-500/16 | rose-500/38 | Error, inactive |
| `.pill-cyan` | cyan-300 | cyan-500/16 | cyan-500/38 | Info, brand |
| `.pill-slate` | muted-foreground | slate-500/12 | border | Default, disabled |

**Usage:**

```tsx
<span className="pill-base pill-emerald">Active</span>
<span className="pill-base pill-amber">Pending</span>
<span className="pill-base pill-rose">Inactive</span>
```

Pills are implemented using `color-mix()` in `oklab` color space so they remain transparent and work over any card surface.

---

### 4.3 Scrollbar Utility

```css
@utility scrollbar-thin {
  scrollbar-width: thin;

  &::-webkit-scrollbar {
    height: 6px;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--surface-2);
    border-radius: 9999px;
  }
}
```

**Usage:** Apply to scrollable panels to ensure consistent, subtle dark scrollbars.

```tsx
<div className="overflow-y-auto scrollbar-thin">
  ...scrollable content...
</div>
```

---

## 5. Base Styles (`@layer base`)

```css
@layer base {
  * {
    border-color: var(--color-border);
  }

  body {
    background-color: var(--color-background);
    color: var(--color-foreground);
    -webkit-font-smoothing: antialiased;
  }
}
```

Sets the default dark background and ensures all default borders use the semantic border token.

---

## 6. Recommended Usage Patterns

### 6.1 Admin Control Plane page layout

```tsx
<div className="min-h-screen bg-background">
  <div className="admin-container py-4">
    <div className="admin-grid">
      <aside className="admin-panel h-fit p-3">
        {/* Sidebar content */}
      </aside>

      <main className="admin-panel flex flex-col overflow-hidden">
        <header className="admin-row admin-pad-x border-b border-border">
          <h1 className="text-sm font-semibold">Page Title</h1>
        </header>

        <div className="admin-row admin-pad-x border-b border-border">
          {/* Toolbar */}
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin">
          {/* Table or content */}
        </div>
      </main>
    </div>
  </div>
</div>
```

### 6.2 Table styling convention

```tsx
<table className="w-full text-sm">
  <thead className="bg-surface text-muted-foreground">
    <tr>
      <th className="admin-row admin-pad-x text-left font-medium">Name</th>
      <th className="admin-row admin-pad-x text-left font-medium">Status</th>
    </tr>
  </thead>
  <tbody className="divide-y divide-border">
    <tr>
      <td className="admin-row admin-pad-x">Row content</td>
      <td className="admin-row admin-pad-x">
        <span className="pill-base pill-emerald">Active</span>
      </td>
    </tr>
  </tbody>
</table>
```

### 6.3 Card / form styling

```tsx
<div className="admin-panel p-4 space-y-4">
  <h2 className="text-sm font-semibold text-foreground">Card Title</h2>
  <p className="text-sm text-muted-foreground">Description</p>
</div>
```

### 6.4 Button hierarchy

```tsx
<button className="bg-primary text-primary-foreground hover:bg-primary/90 px-3 py-1.5 rounded-md text-sm font-medium">
  Primary
</button>

<button className="bg-secondary text-secondary-foreground hover:bg-secondary/80 px-3 py-1.5 rounded-md text-sm font-medium">
  Secondary
</button>

<button className="bg-destructive text-destructive-foreground hover:bg-destructive/90 px-3 py-1.5 rounded-md text-sm font-medium">
  Delete
</button>
```

---

## 7. Responsive Reference

| Breakpoint | Tailwind prefix | Sidebar width | Layout |
|------------|-----------------|---------------|--------|
| 0px | default | hidden/stacked | single column |
| 640px | `sm:` | 240px | side-by-side |
| 1024px | `lg:` | 300px | side-by-side |
| 1280px | `xl:` | 300px | side-by-side |
| 1536px | `2xl:` | 300px | side-by-side |

The shell container maxes out at `1680px` via `.admin-container`.

---

## 8. Typography Conventions

| Element | Size | Weight | Color |
|---------|------|--------|-------|
| Page title | `text-sm` | `font-semibold` | `text-foreground` |
| Section header | `text-sm` | `font-medium` | `text-foreground` |
| Body / table | `text-sm` | `font-normal` | `text-foreground` |
| Secondary text | `text-sm` | `font-normal` | `text-muted-foreground` |
| Nav items | `text-[0.8125rem]` | `font-medium` | `text-muted-foreground` / `text-foreground` active |
| Status pills | `text-xs` / `text-[0.75rem]` | `font-medium` | color-scheme dependent |

> Prefer `text-sm` (0.875rem) for primary UI and `text-[0.8125rem]` (13px) for dense navigation.

---

## 9. Do's and Don'ts

### Do

- Use semantic tokens (`bg-card`, `text-muted-foreground`, `border-border`) instead of raw colors.
- Use `.admin-grid`, `.admin-panel`, `.admin-pad-x` for Admin Control Plane layouts.
- Use `.pill-base` + `.pill-*` for status badges.
- Use `.scrollbar-thin` for custom scrollable regions.
- Use `@utility` for new custom utilities in `src/styles.css`.
- Load fonts via `<link>` in `src/routes/__root.tsx`, never `@import` a URL.

### Don't

- Create a `tailwind.config.js` — Tailwind v4 ignores it.
- Use `@tailwind base; @tailwind components; @tailwind utilities;` — they no-op in v4.
- Hardcode hex colors like `bg-[#1E293B]` in components — use `bg-card` or `bg-surface`.
- Use `@apply` outside `src/styles.css` without `@reference`.
- Add custom utilities via `@layer utilities` — use `@utility` instead.

---

## 10. Quick Reference: Common Classes

| Class | Effect |
|-------|--------|
| `bg-background` | Page background (`#0B0F17`) |
| `bg-card` | Card / panel background (`#1E293B`) |
| `bg-surface` | Elevated surface (`#151B29`) |
| `bg-surface-2` | Secondary surface (`#1E293B`) |
| `bg-primary` | Primary indigo background |
| `bg-brand` | Brand cyan/teal background |
| `text-foreground` | Primary text |
| `text-muted-foreground` | Secondary/muted text |
| `text-brand` | Brand cyan text |
| `text-link` | Link text color |
| `border-border` | Standard border |
| `ring-ring` | Focus ring color |
| `admin-container` | Max-width centered shell |
| `admin-grid` | Sidebar + content grid |
| `admin-panel` | Card surface with border |
| `admin-pad-x` | Standard horizontal padding |
| `admin-row` | Standard 36px height row |
| `pill-base` | Base badge shape |
| `pill-emerald` | Active/success badge |
| `pill-amber` | Warning/pending badge |
| `pill-rose` | Error/inactive badge |
| `scrollbar-thin` | Thin dark scrollbar |

---

## 11. File Checklist

When adding new UI, ensure the following files are consistent:

- [ ] `src/styles.css` — tokens, utilities, and base styles updated if needed
- [ ] `src/routes/__root.tsx` — font `<link>` tags if a new font is introduced
- [ ] Component files — use semantic tokens and custom utilities
- [ ] No new `tailwind.config.js` or `postcss.config.js` created

---

*Last updated: 2026-08-13*
