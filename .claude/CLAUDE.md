# CAM 3.4 — RFQ Automation for Centum
> Digibull internal. Client: Centum. Project lead: Harish (harish.t@digibull.ai)

## What This Is

CAM is Digibull's name for the RFQ automation it builds for Centum. This is version **3.4** — an incremental upgrade on CAM 3.3 (currently live).

**Do NOT build CAM 4.** CAM 4 changes ~80% of the tech stack. That's a separate project. Focus: understand 3.3, build 3.4 delta.

## Folder Map

```
C:\CAM[3.4]-RFQ_centum\
├── README.md, Start Here.md      <- front door and reading order
├── GOAL_PROMPT.md                <- standing goal and rules for the SPEC queue
├── .claude\CLAUDE.md             <- This file
├── Eng_Diagram [ Must follow ]\  <- Engineering diagrams. MUST follow these (README inside)
├── Reference[KT]\                <- knowledge base (README inside)
│   ├── DOMAIN KNOWLEDGE\         <- basic (teaching series) and adv (working knowledge)
│   ├── Extras\                   <- 4 encyclopedias + reverse engineering of CAM 3.3 outputs
│   ├── Full Details\             <- full CAM 1.0 -> 4.1 evolution, APIs, features, MAP
│   └── Source Code\              <- CAM 3.3 reference snapshot + BAM UI (read-only; README inside)
├── SPECS\                        <- SPEC-001..024, progress.json, TODO, handoff\ (session history)
├── acceptance_evidence\          <- browser proofs: videos, screenshots, logs, scripts
├── CAM-Source\                   <- THE product source: build here
└── SECRETS.md, setup_postgres.ps1 <- service map and DB bootstrap (env-var placeholders only)
```

## CAM 3.3 Stack (what we're building on)

| Layer | Tech |
|-------|------|
| Desktop app | Electron (`accomplish-ui`) |
| Frontend | React + TypeScript |
| Agent core | `packages/agent-core` — MCP tools, providers, services |
| Orchestration | Dify (`dify-orchestration/`) |
| MCP router | FastMCP router |
| MCP servers | calendar, gmail, whatsapp, gerber-integration, bom-processing, distributor-pricing, rfq-memory, reporting |
| DB | PostgreSQL |
| Deploy | Docker + Kubernetes |

## Auto-Triggers — do these yourself, never wait to be asked

| When | What to do |
|------|-----------|
| **Every session start** | Call `memory` MCP → `search_nodes("CAM 3.4")` to load stored context |
| **Before touching any library code** | Call `context7` MCP to pull live docs for that exact library version |
| **Navigating unfamiliar code** | Use `serena` (`find_symbol`, `search_symbols`) — don't manually grep large trees |
| **Any UI file edit** | Impeccable hooks fire automatically; run `/impeccable audit` before marking done |
| **After key architectural decision** | Write to `memory` MCP (`create_entities` / `add_observations`) |

## How to Start Work

1. Read `Start Here.md`, then `Eng_Diagram\` — the source of truth for architecture (its text transcription is `SPECS\handoff\CAM-3.4-HANDOFF.md`)
2. Read `Reference[KT]\Full Details\` to understand what changed between versions
3. Map the 3.3→3.4 delta before writing a single line

## Installed Tools & Why

### MCP Servers (in `~/.claude/settings.json`)

| Server | Purpose |
|--------|---------|
| `@modelcontextprotocol/server-memory` | Persistent knowledge graph — remembers architecture decisions, patterns, and context across sessions |
| `@upstash/context7-mcp` | Live docs — pulls current React/FastMCP/Dify API docs on demand |
| Serena (uvx) | Semantic code intelligence — navigates the large BuLLMQuote-SRIM codebase without reading every file |
| `nagabhushana-personas` (HTTP) | 8 thinking-framework personas + 5 orchestration panels. Use `explain-codebase` when mapping CAM 3.3, `bug-hunt` for debugging, `full-council` for hard architecture calls |

### Claude Code Plugins

| Plugin | Purpose |
|--------|---------|
| **Impeccable** | UI design skill — 23+ commands, enforces production-grade design. Run `/impeccable init` per project. |
| **ponytail** | Lazy senior dev mode — YAGNI, stdlib-first, shortest diff wins |
| **context7** | Up-to-date library docs pulled into context |
| **serena** | Semantic code analysis |
| **desktop-commander** | Reads PDFs, images, Excel/DOCX without full token burn |
| **feature-dev** | Multi-agent feature development workflow |
| **code-review** | Automated PR review |
| **claude-md-management** | Keeps CLAUDE.md files current |

## Working Rules

- **Eng_Diagram first** — never guess architecture, the diagrams define it
- **UI = Impeccable** — no generic AI UI. Research competitors, exceed their design
- **Memory MCP** — use it. Store architectural insights, API patterns, decisions
- **Context7** — when touching any library API, pull live docs first
- **Ponytail always on** — no speculative abstractions, no boilerplate for later

## Key Reference Commands

```
/impeccable init       # Set design baseline (run once per project)
/impeccable audit      # Review UI against design rules
/impeccable polish     # Final UI pass before shipping
/ponytail              # Force laziest working solution
```

## DO NOT

- Build CAM 4 features
- Guess at architecture without reading Eng_Diagram
- Ship generic-looking UI
- Add abstractions not needed by 3.4
