# CAM 3.4: RFQ automation for Centum

CAM is Digibull's name for the system that turns a customer's bill of materials (BOM) into a costed quote for **Centum Electronics**. CAM 3.3 is live at Centum today. This repository is the work to build **CAM 3.4**: the same product with a real orchestration engine (Temporal instead of Dify), a conversational assistant in the middle of the screen, a manifest-driven pipeline, and the 16 Excel reports fixed and validated.

> **Scope.** CAM 3.3 to 3.4 only. CAM 4.0 changes about 80 % of the tech stack and is a separate project; nothing here builds it.

## What CAM 3.4 does today

| Area | What works | Specification |
|---|---|---|
| Intake | Files are scanned by two engines (BuLL*Sav / ClamAV and Repel Shield), recognised by what is inside them (BOM, volume, QuoteWin), and checked **before** the run for cells that would turn into NaN or errors; a fix dialog edits them in place and downloads the corrected file | SPEC-022, SPEC-023 |
| Assistant | One persistent chat; rules decide first, a model only phrases answers; every answer cites its source cells; actions (create an RFQ, resume a run, change a value) always wait behind a confirmation card | SPEC-006, SPEC-010, SPEC-019, SPEC-020 |
| Pipeline | Temporal workflow with human-in-the-loop signals, the 16 reports with per-tab validation, history of every run with who started it and a plain-words reason when it failed | SPEC-002, SPEC-004, SPEC-005, SPEC-021 |
| Manifests | The ISATVON manifests are editable in the app (Monaco, validation, inline diff of earlier versions); the left pane follows them, and `enabled: false` greys a skill out | SPEC-013, SPEC-020, SPEC-022, SPEC-023 |
| Security | Parameterised SQL, credentials in environment variables, twin-engine file scanning, a user and activity view | SPEC-007, SPEC-012 |
| Feasibility & Risk | A real pipeline step (SKILL_03): every SCRUB BOM line gets a Can build / Cannot build verdict with reasons and a High / Medium / Low risk. Its rules are edited by an admin in **Settings > Feasibility** (lead-time limit, statuses, toggles, machine rules); each RFQ stores the rules it used | SPEC-025 section 8 |
| Reports & Analytics | The delivered workbook is read back (cost per set, price control, lead time, cash out, exceptions, GO / NO-GO) and shown per RFQ and across all RFQs; the Formula Engine re-computes every formula after the export and stores the values where a viewer would show zero | SPEC-025 section 7 |
| Left pane | Follows the run from the database: "Needs your upload" while the run waits for the QuoteWin file, then moves on by itself; a finished run shows Completed | SPEC-025 section 8 |

The state of every specification is in [`SPECS/progress.json`](SPECS/progress.json) and [`SPECS/README.md`](SPECS/README.md). The newest, fullest account of what was built and proven is [`SPECS/handoff/HANDOFF-2026-11-05.md`](SPECS/handoff/HANDOFF-2026-11-05.md) (section 9).

## Where things are

| Folder | What it holds | Start with |
|---|---|---|
| [`CAM-Source/`](CAM-Source) | **The product source.** Python services (`fastapi-router`, `temporal_worker`, `mcp-tools`), the TypeScript app and daemon (`accomplish-ui`), the manifests, the tests, `docker-compose.yml` | its `docs/` folder and `scripts/run-cam34.ps1` |
| [`Eng_Diagram [ Must follow ]/`](Eng_Diagram%20%5B%20Must%20follow%20%5D) | **The architecture diagrams. They win over every other document.** Eight images and one interactive page | its [README](Eng_Diagram%20%5B%20Must%20follow%20%5D/README.md) |
| [`Reference[KT]/`](Reference%5BKT%5D) | The knowledge base: domain knowledge (basic to advanced), encyclopedias, reverse-engineering of CAM 3.3's Excel outputs, the full CAM 1.0 to 4.1 documentation, and the related source snapshots | its [README](Reference%5BKT%5D/README.md) |
| [`SPECS/`](SPECS) | Agile, spec-driven work orders (SPEC-001 to SPEC-024), test logs, and the session handoffs | its [README](SPECS/README.md) |
| [`CAM-Source/sample-inputs/`](CAM-Source/sample-inputs) | The three sample files a golden-path RFQ needs: the SCRUB BOM, the Volume file and the QuoteWin file (the folder name says which is which) | |
| [`acceptance_evidence/playwright/`](acceptance_evidence/playwright) | The Playwright test of the whole flow in the real app, its recorded video, the screenshots and the downloaded report | `golden-path.spec.cjs` |
| [`acceptance_evidence/`](acceptance_evidence) | Proof that the product works: browser recordings, screenshots, logs and the scripts that drove them | its [README](acceptance_evidence/README.md) |
| [`.claude/`](.claude) | The standing instructions and permissions for the coding agent that works in this folder | `CLAUDE.md` |
| `SECRETS.md`, `setup_postgres.ps1` | Service map and the database bootstrap (passwords are environment-variable placeholders, never literal values) | |
| [`GOAL_PROMPT.md`](GOAL_PROMPT.md) | The standing goal and rules given to the agent that finishes the SPEC queue | |

New here? Read [`Start Here.md`](Start%20Here.md).

## Run it

From `CAM-Source` (needs Docker Desktop, Node 24 with pnpm, Ollama with `qwen2.5-coder:7b` and `qwen3:8b`, and a `.env` copied from `.env.example` with `POSTGRES_PASSWORD`, `JWT_SECRET` and `OPENROUTER_API_KEY` filled in):

```powershell
.\scripts\run-cam34.ps1            # start everything and print the URLs
.\scripts\run-cam34.ps1 -Build     # rebuild the service images first
.\scripts\run-cam34.ps1 -Status    # show what is up, change nothing
.\scripts\run-cam34.ps1 -Stop      # stop the UI, the daemon and the containers (volumes are kept)
```

The web app is at http://localhost:5181, the daemon at port 9334, the Temporal UI at http://localhost:8082. All ports, links and login notes are in [`SPECS/handoff/CAM-3.4-RUNNING-STACK.md`](SPECS/handoff/CAM-3.4-RUNNING-STACK.md).

The path contains square brackets, which PowerShell and Python treat as wildcards: use `-LiteralPath` in PowerShell and avoid `glob` on paths under this folder.

## Working rules

1. **Diagrams first.** `Eng_Diagram [ Must follow ]` defines the architecture. If a document and a diagram disagree, the diagram wins and the conflict is logged in the SPEC.
2. **Spec-driven.** One SPEC is one work order with context, scope, acceptance and tests. Write the SPEC before the code.
3. **Proof, not intent.** "Done" means a passing test run or a real browser run with screenshots, never a statement.
4. **Never guess.** A port, table, endpoint or file is only stated if it was opened; otherwise it is marked *unverified*.
5. **3.4 only.** No CAM 4.0 work, no Jinja2/AST code generation, no change of the agreed architecture.

## One RFQ, end to end

1. **Create RFQ** (the card in the left pane): pick the customer and project, drop the SCRUB BOM and the Volume file. Both are scanned by the two engines, sorted by what is inside them, and checked before anything runs.
2. **Standardize the SCRUB BOM** (the intake MCP server). The run then **waits for the QuoteWin file**: the left pane says "Needs your upload".
3. **QuoteWin upload.** A file that shares no part number with the BOM is refused with the numbers; a partial match is accepted and says how many parts stay unpriced. The costing sheet is optional and recorded as skipped when absent.
4. **Feasibility & Risk** (SKILL_03, when its manifest flag is on). One verdict per BOM line with the reasons; the rules come from **Settings > Feasibility**.
5. **CBOM and reports.** The CBOM is built, enriched and resolved (a human reviews only real conflicts); the 16 report tables are generated and validated; the workbook is exported with its tabs (21 to 24, depending on the run).
6. **Formula Engine check.** Every formula of the workbook is re-computed; where the stored value disagrees with the engine, the engine's value is stored, and the export says how many.
7. **Download and Reports & Analytics.** The finished workbook is saved to the computer by the app; the Reports & Analytics page reads it back for one RFQ and across all RFQs.

Every step writes its result to `rfq_step_events` (completed, skipped or warning, with the reason). The left pane and the right-hand progress log both read from there.

## Open-source tools and how they connect

| Tool | Role in CAM 3.4 | Connected to |
|---|---|---|
| React, Vite, TypeScript, Tailwind CSS, Radix UI, Phosphor icons | The web app (`accomplish-ui/apps/web`), served on port 5181 in development | the daemon, over HTTP `/rpc` and an event stream (`/events`) |
| Uppy | The upload dashboard of Create RFQ (drop area, tiles, progress) | the upload server (`fastapi-router/upload_server.py`) |
| Monaco editor | The manifest editor in `#/manifests` | the daemon's manifest API |
| Node.js 24, pnpm, tsup | The daemon (`accomplish-ui/apps/daemon`), built with tsup; listens on port 9334 | PostgreSQL (`pg`), DuckDB, the Python services |
| Express, zod, pino | HTTP routes, input validation and logging inside the daemon | the browser and the database clients |
| Python 3.12, FastAPI | The router (`fastapi-router`): the pipeline order, the routing gate, upload and export endpoints | the MCP tool servers and the daemon |
| FastMCP (`fastmcp`) | The tool servers: intake (`mcp-tools/intake`, `scrub-intake`) and reporting (`mcp-tools/reporting/superset`, port 18105) | the router calls each tool over HTTP |
| DuckDB | Report and analysis tables, read by the reports and by Reports & Analytics | the reporting tools and the bridge |
| openpyxl, pandas | Reading and writing the Excel workbooks | the reporting tools |
| PostgreSQL 18 | Two databases: `logic_db` (registry, routing profiles, currencies, feasibility rules) and `file_metadata_db` (RFQs, progress, step events) | the daemon and the router |
| Temporal (`temporalio/auto-setup`, Temporal UI) | The durable workflow engine for the human review steps (port 7233; UI on port 8082) | the Temporal worker in `temporal_worker` |
| Docker Compose | Starts the services above (`CAM-Source/docker-compose.yml`) | everything |
| ClamAV (BuLL*Sav signatures) and Repel Shield | The two file-scanning engines of the upload; a file is used only when it passes | the upload dialog |
| Ollama (`qwen2.5-coder:7b`, `qwen3:8b`) | Local language models that word the assistant's answers; the rules decide the facts | the assistant in the daemon |
| OpenRouter (hosted gateway, optional) | A hosted model when the local one is not enough | the assistant, when its key is set |
| Playwright (Chrome) | The browser test and its recorded video (`acceptance_evidence/playwright`) | the running app |
| Vitest, Testing Library, pytest | Unit and integration tests (below) | the source code |
| Excel (not open source) | Used only to check the workbook: its full recalculation is the reference the Formula Engine is compared with | `acceptance_evidence/spec019/excel_oracle.py`, `acceptance_evidence/playwright/excel_dynamic_check.ps1` |
| Apache Superset (optional, `@superset-ui/embedded-sdk`) | An optional dashboard embed; the app works without it | the Reports & Analytics page |

## Folder tree

```
CAM[3.4]-RFQ_centum/
├── README.md                       this file
├── Start Here.md, GOAL_PROMPT.md   where to begin, and the standing goal
├── Eng_Diagram [ Must follow ]/    architecture diagrams (they win over every other document)
├── Reference[KT]/                  knowledge base: domain notes, CAM 1.0 to 4.1 documents, source snapshots
├── SPECS/                          SPEC-001 to SPEC-025, the handoffs, progress.json
├── acceptance_evidence/
│   ├── spec019/                    live Chrome scripts, screenshots, the Excel oracle
│   └── playwright/                 golden-path.spec.cjs, videos/, screenshots/, downloads/
└── CAM-Source/
    ├── docker-compose.yml          all services
    ├── .env.example                the variable names (the real .env is git-ignored)
    ├── SECRETS.md                  service map: names only, no values
    ├── setup_postgres.ps1          creates the databases
    ├── sample-inputs/              the three files of a golden-path RFQ
    ├── accomplish-ui/
    │   ├── apps/web                React app (Create RFQ, pipeline pane, Settings, Reports)
    │   ├── apps/daemon             Node daemon (RPC, events, manifests, Settings data)
    │   └── packages/agent-core     shared agent code and the dev-browser MCP
    ├── fastapi-router/             router, upload server, DuckDB API, edit and chat evidence
    ├── mcp-tools/
    │   ├── intake/, scrub-intake/  intake tools: standardize BOM, QuoteWin, costing sheet
    │   ├── reporting/superset/     reporting tools: CBOM, enrich, final selection, 16 reports, export,
    │   │                           Feasibility & Risk (reports/feasibility_risk.py)
    │   ├── distributor-pricing/, gerber-integration/, rfq-memory/
    │   └── shared/                 formula_engine/ (the Formula Engine), formula_verify.py,
    │                               rfq_analytics.py (Reports & Analytics)
    ├── manifests/                  the ISATVON manifests: skills, agent sequence, reporting tools
    ├── temporal_worker/            the durable workflow worker
    ├── testing/                    pytest suites (run from CAM-Source)
    └── docs/                       user guide and technical notes
```

## Tests and proof

```powershell
cd CAM-Source
python -m pytest -q                                              # Python: 520 passed, 8 skipped (last full run)
cd accomplish-ui/apps/daemon; npx vitest run                     # daemon: 538 passed
cd ../web; npx vitest run --config vitest.unit.config.ts         # web unit: 557 passed
npx vitest run --config vitest.integration.config.ts             # web integration: 185 passed, 1 skipped
cd ../../../acceptance_evidence/playwright
node golden-path.spec.cjs                                        # the whole flow in Chrome, recorded (needs the stack running)
```

The Playwright run checks each step of the flow and records a video of the whole session. The downloaded report is kept in `downloads/`. `excel_dynamic_check.ps1` opens that report in Excel, changes one typed price, and reads the Summary again: the assembly that uses the part changes, the others do not.

## Credentials

No password, token or key is written in this repository. Names only:

| Credential | Where it lives |
|---|---|
| Postgres password, JWT secret, OpenRouter key | `CAM-Source/.env` (git-ignored); the names are in `CAM-Source/.env.example` |
| Test login | the development flag `ACCOMPLISH_TEST_LOGIN=1` (development only) |
| GitHub access for pushing | the Windows credential store, or a token passed for a single command; never saved into the repository's configuration |

`CAM-Source/SECRETS.md` lists which service uses which credential, with no values.

## Publishing note

This repository is published from the working folder as it is. Only `node_modules/`, the bundled Node runtime and `.env` files are ignored; client-data rules that already existed inside `CAM-Source/.gitignore` stay in force. How the folder was tidied for publication is documented in [`SPECS/SPEC-024-repository-rearrangement-and-publication.md`](SPECS/SPEC-024-repository-rearrangement-and-publication.md), with a log of every moved or merged file.
