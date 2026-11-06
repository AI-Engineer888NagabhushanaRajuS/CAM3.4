# SPEC-016 — Chat pane audit + fixes (RFQ assistant)

**Status:** completed for the chat pane; live browser run NOT done (services not running). **Branch:** feat/spec-016-ui (from feat/spec-015-cutover). **Depends on:** SPEC-015.

## Scope
`accomplish-ui/apps/web/src/client/components/rfq/RFQChatPane.tsx` only (CAM 3.4 RFQ assistant pane). No other UI touched.

## Audit (impeccable audit, technical checks)
No PRODUCT.md exists, so the audit ran on the incumbent implementation (allowed for refinement; `init` offered as follow-up).

| Dimension | Finding (file:line before fix) | Action |
|---|---|---|
| Implementation | `ThreadPrimitive.Suggestion` given `asChild`, not in its props (TS2322 at :288). Only TS error in this file. | Fixed: plain button appends via `runtime.thread.append`. |
| Responsive | Fixed `w-[400px] h-[580px]` overflows phones and short viewports (:237). | Fixed: `min()` sizes. |
| A11y | No live region for replies (:258); composer input has placeholder only (:303). | Fixed: `role="log"`, `aria-live="polite"`, `aria-label`. |
| Motion | Typing dots `animate-bounce` ignore reduced motion (:270). | Fixed: `motion-reduce:animate-none`. |
| Contrast | `text-muted-foreground` on `bg-muted/60` at 10–11px (:143, :293). | NOT verified: needs rendered theme values. Open. |
| Touch | Suggestion chips ~22px tall (:293); close button 24px. | Not changed. Open (below 24px AA target). |
| Glass | `backdrop-blur-sm` on header (:240). | Not changed (refinement preserves incumbent). Open for critique. |

## Verified
- `npx tsc -p tsconfig.client.json --noEmit` (accomplish-ui/apps/web): 16 errors before, 15 after; **0 in RFQChatPane.tsx**. The 15 remaining are pre-existing in other files (e.g. `window.accomplish` possibly undefined).
- Design hook scan on the edited file: no deterministic issues.

## Not verified
- Browser run and screenshot (needs daemon + router). Not done.
- `/code-review` on this diff: not run.

## Review-driven
Verified in one `code-review` pass on SPEC-015 only; SPEC-016 diff not reviewed.

## Browser run (this round)
Harness: a page outside the repo (scratchpad/chat-harness) renders RFQChatPane with the app's own globals.css, served by Vite from the web app's own config and PostCSS. Driven by Playwright (Python) on the existing Chromium 1234 build. Run: `python browser_check.py` against localhost:5201.
Results:
- composer labelled "Ask about this RFQ": PASS
- live log (role=log) present: PASS
- suggestion chip sends its prompt into the log: PASS
- chat API unreachable -> fallback reply "Couldn't reach the chat service" shown: PASS
- phone width 375px: horizontal overflow 0px: PASS
- screenshots: chat-desktop.png and chat-mobile.png (pane styled, fits at 375px)
- console: 2 expected 404s (chat endpoint absent in the harness; favicon)
NOT covered: the full app (Electron/daemon IPC, window.accomplish), the real chat backend (rfq-memory), a real RFQ. Visual design audit beyond the functional check: not re-run.

## Close-out 2026-11-02 (open items resolved with defaults, per GOAL §5)
Default taken for the browser scope: browser run of RFQChatPane in the harness against the app's own source and CSS (scratchpad/chat-harness, Chromium 1234). Full Electron/daemon app run is NOT in scope for this spec; it is recorded as OPEN, not done.
Measured (scratchpad/chat-harness/measure_a11y.py, real browser):
- Suggestion chip: 95x27px (above the 24px AA target). The earlier "~22px" estimate was wrong; no change needed.
- Close button: 24x24px (meets 24px). No change.
- Suggestion chip text contrast: 4.35:1 before, FAILED AA 4.5:1 for 11px text. Fixed: text-muted-foreground -> text-foreground/80 on the chip. After: 5.4:1 PASS.
- Badges at RFQChatPane.tsx lines ~141 (10px) and ~247 (11px) got the same token change. They do not render in the harness state, so their ratio is inferred from the same change, not measured.
- Glass header (backdrop-blur-sm, line ~240): unchanged (refinement preserves incumbent). Open for a critique pass.
- Functional browser check (scratchpad/chat-harness/browser_check.py): composer labelled PASS, live log PASS, chip sends prompt PASS, fallback reply PASS, mobile overflow 0px PASS. 2 console 404s (chat endpoint and favicon absent in the harness).
- Component test: vitest run RFQChatPane.unit.test.tsx: 3 passed.
- Typecheck: tsc -p tsconfig.client.json: 15 errors, all pre-existing in other files; 0 in RFQChatPane.tsx.
- /code-review on this diff: still not run (OPEN; the check was done by hand as above).
Open: full app run (Electron/daemon/real chat backend); glass header critique; the two badges' contrast measured in a real render.

## /code-review (medium) on commit 06db640 — done 2026-11-02
- Correctness: no bugs found. Contrast rechecked in light, dim and dark: changed chip 5.39:1 light / 10.53:1 dark; header badge 5.29:1 light / 9.46:1 dark; dim 8.3:1. `text-foreground/80` resolves through `hsl(var(--foreground) / <alpha-value>)`.
- Altitude finding (OPEN, not changed): the light-theme `--muted-foreground` token (accomplish-ui/apps/web/src/client/styles/globals.css:95, #697586) still measures ~4.28:1 on muted surfaces. Any other small muted text on a muted surface in the app still fails AA. Fixing the token changes every screen that uses it, which is outside SPEC-016; left as a design-system decision.

## Scope decision 2026-11-03 (user)
The Electron shell and the daemon are NOT part of CAM 3.4. accomplish-ui is used only for the web UI and the streaming chat pane. The full Electron/daemon app run is therefore removed from SPEC-016's acceptance, not left open. Verification = the web UI in a real browser (scratchpad/chat-harness, Chromium) plus the component test.
