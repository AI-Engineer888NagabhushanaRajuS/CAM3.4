# Executive summary — Centum / CAM platform, 2026-10-27

One page. For the full picture see [SESSION-SUMMARY.md](SESSION-SUMMARY.md).

## What works today

Real BOM/RFQ costing runs execute end to end, right now, on this one Windows
desktop — no cloud deployment. Two flows run: `Standard_BOM_Flow` (through
MCP Jungle) and `RFQ_Flow` (through Bifrost). The CBOM Excel export bug
reported this session (Assembly Summary price not updating live) is fixed
and verified. CAM's code is now safely backed up on GitHub, privately.

## What's broken, and how urgent each one is

| Issue | Urgency | Why |
|---|---|---|
| A "resume" button can report success for an action that has zero effect | **Fix now** | The HITL-approval webhook POSTs to an address nothing has ever listened on. The real resume mechanism works independently, so no data is lost today — but a user is told "success" for something that did nothing, and a future bug ticket could waste real hours chasing it. |
| `Standard_BOM_Flow` tools would fail outright if ever moved onto the newer gateway | **Fix before that migration, not before** | This flow doesn't use the new gateway today, so there's zero live impact. It will break the instant someone migrates it without first fixing a naming mismatch. |
| 5 security gaps: open CORS, an unauthenticated token endpoint, a shared default secret, a hardcoded test password in the UI, a stale port registration | **Should close before wider exposure** | None of these are being actively exploited as far as this review could tell, but all five are real and documented with exact file/line citations in [SECURITY-REPORT.md](SECURITY-REPORT.md). |
| Two Postgres databases are reachable with **unrestricted** direct SQL access through the shared MCP gateway | **Needs a decision** | Any tool connected through that shared gateway can read or write this platform's real business data directly, bypassing the application entirely. |

## What needs a decision from you, specifically

1. **The dead HITL webhook** — remove it now, or just document it and leave it? (Recommendation: remove — it costs nothing to keep broken and risks confusing a future debugging session.)
2. **Is `Standard_BOM_Flow` actually scheduled to move onto Bifrost soon?** That's the only thing that changes the routing bug from "note it" to "fix it this sprint."
3. **Two database-permission claims were never independently re-confirmed** (whether one Postgres role can reach databases it shouldn't) — querying live production credentials to check was declined by this session's own safety controls. Confirming this needs either your own direct check, or an explicit go-ahead to do it carefully.

## What this review did NOT do

It did not touch the live, client-serving system. No file was uploaded through the UI, no service was restarted, no code was edited. Every finding above came from reading real source code and real running-process state, twice, independently — see [FINDINGS-AND-FIXES.md](FINDINGS-AND-FIXES.md) for exactly how each one was checked.
