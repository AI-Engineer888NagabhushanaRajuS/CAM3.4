# SPEC-019 phase D scout: Playwright and MCP (2026-11-05)

## Found (read from source)
- `packages/agent-core/src/opencode/generator-mcp.ts` `buildMcpServers()` is where the agent runtime gets its MCP servers (slack, request-connector-auth, complete-task, start-task, `dev-browser-mcp` at line ~151, gmail/calendar/gws when a manifest exists, connectors).
- Browser automation already exists and is Playwright based: `packages/agent-core/mcp-tools/dev-browser` and `dev-browser-mcp` list `playwright` in their package.json. Mode: `builtin` (HTTP dev-browser server), `remote` (CDP endpoint + headers), `none`; `config-generator.ts` lines ~326-335 read `ACCOMPLISH_BROWSER_MODE`.
- `task-service.ts`: `startTask` and the follow-up path of `resumeSession` short-circuit to the grounded RFQ assistant, so new chat messages never reach the OpenCode agent. `_runTask` (OpenCode) is reachable only from a `resumeSession` call with no existing task.

## Decision
1. Do NOT route chat through the OpenCode agent. Chat stays the grounded assistant plus the deterministic create-RFQ tool (SPEC-019 phase C).
2. Playwright MCP = add the official `@playwright/mcp` as one more entry in `buildMcpServers()` (type local, command `npx @playwright/mcp@<pinned> --allowed-origins <CAM web origin> --headless`), enabled only when `CAM_PLAYWRIGHT_MCP=1`. `--allowed-origins` is the enforcement point named in SPEC-019 section A; the origin comes from the web URL the daemon already serves (default `http://localhost:5181`).
3. UI-only tasks that need it run through `_runTask` with an explicit flag, only after a `confirm_action` card (action `ui_task`, to be added to the contract as an addition), never from plain chat.

## Built (2026-11-05)
`generator-mcp.ts` registers `playwright` when `CAM_PLAYWRIGHT_MCP_ORIGIN` is set: `npx -y @playwright/mcp@0.0.84 --allowed-origins <origin> --isolated --headless --block-service-workers` (version checked on npm, flags checked in the upstream docs via context7). Unit-tested (agent-core `config-generator.test.ts`, 62 pass): absent without the env var, pinned and origin-limited with it, no `--allow-unrestricted-file-access`.

## Correction to SPEC-019 section A (important)
Upstream states `--allowed-origins` "does not serve as a security boundary and does not affect redirects". SPEC-019 asked for the allow-list to be "shown to be enforced"; it can only be shown to be a guardrail (request interception). The actual boundary for UI-driven writes is: the user's confirmation card, the in-memory profile (`--isolated`), file access left at its default (workspace only, no `file://`), and no credentials in the profile. Do not describe the allow-list as isolation in any user-facing text.

## Blocked / not provable today
- Outcome 7 (one UI-only task end to end) needs an agent model with tool use. On this machine only qwen3:8b on an 8 GB Quadro M4000 is available (about 3.6 tokens/s), which is not workable for an agent loop; it needs the OpenRouter key from Harish in Settings. Until then phase D is implemented behind the env flag and unit-tested, but NOT proven live.
