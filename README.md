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

The state of every specification is in [`SPECS/progress.json`](SPECS/progress.json) and [`SPECS/README.md`](SPECS/README.md). The newest, fullest account of what was built and proven is [`SPECS/handoff/HANDOFF-2026-11-05.md`](SPECS/handoff/HANDOFF-2026-11-05.md) (section 9).

## Where things are

| Folder | What it holds | Start with |
|---|---|---|
| [`CAM-Source/`](CAM-Source) | **The product source.** Python services (`fastapi-router`, `temporal_worker`, `mcp-tools`), the TypeScript app and daemon (`accomplish-ui`), the manifests, the tests, `docker-compose.yml` | its `docs/` folder and `scripts/run-cam34.ps1` |
| [`Eng_Diagram [ Must follow ]/`](Eng_Diagram%20%5B%20Must%20follow%20%5D) | **The architecture diagrams. They win over every other document.** Eight images and one interactive page | its [README](Eng_Diagram%20%5B%20Must%20follow%20%5D/README.md) |
| [`Reference[KT]/`](Reference%5BKT%5D) | The knowledge base: domain knowledge (basic to advanced), encyclopedias, reverse-engineering of CAM 3.3's Excel outputs, the full CAM 1.0 to 4.1 documentation, and the related source snapshots | its [README](Reference%5BKT%5D/README.md) |
| [`SPECS/`](SPECS) | Agile, spec-driven work orders (SPEC-001 to SPEC-024), test logs, and the session handoffs | its [README](SPECS/README.md) |
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

## Publishing note

This repository is published from the working folder as it is. Only `node_modules/`, the bundled Node runtime and `.env` files are ignored; client-data rules that already existed inside `CAM-Source/.gitignore` stay in force. How the folder was tidied for publication is documented in [`SPECS/SPEC-024-repository-rearrangement-and-publication.md`](SPECS/SPEC-024-repository-rearrangement-and-publication.md), with a log of every moved or merged file.
