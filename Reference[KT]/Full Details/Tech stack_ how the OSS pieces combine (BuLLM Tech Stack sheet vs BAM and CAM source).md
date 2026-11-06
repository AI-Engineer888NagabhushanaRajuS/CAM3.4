# **Tech stack: how the open-source pieces combine**

*Private working document. Source-only review, nothing was run. Labels: SOURCE = seen in inspected code or config, DOC = stated in a document or sheet, PROPOSAL = a plan, OPEN = unresolved. "Not found" means not found in the files inspected only.*

## **1. Which Excel, and what it is**

The most relevant file is **BuLLM Tech Stack & Tool Factory** (Google Sheet id 11K5JeiFZZyROn32mVlizLJ03DX8LwWfStNmucBtQ_j4, owner srinath.r, last modified 29 Oct). It has seven tabs: Notes, Roadmap (63 features), Tech Stack (33 components), Leaderboard (top 25 repos), Repo Library (240 rows), Skill Library (359 rows), Weekly Top 5.  
Its Notes tab says the current stack came from "BuLLM - Master Tech Stack (31 components)" plus Srinath's notes: Bifrost not LiteLLM, PaddleOCR replaced Docling, the Accomplish middle pane is being replaced. The Roadmap columns "Current stack component / Compatible candidates / Fit status" are an assistant-made mapping dated 29 Oct, marked for Srinath's review (DOC).  
**Other candidate Excels (read, lower priority):** BuLLM_Master_Tech_Stack (srinath.r original 1gO6BVhLLM98j4YBtWmuymoIg1uM8zcQ1NEzWxBkxDJs, 10 Oct; chaithanya.k copy 1f\_\_MnUvbN4ji8hP9hS1JmnZPKFJwd8IWO6V9zrJxgAU); SRI - Tools & Repos (1QAFChCH2kz8R36efzZXekErMUoZ95T_Sl-l6GqrW4xI); SRI 3.1 Tech Stack (1DatE5pDCE3xD7FiXNowjxVn-4AqoOJ6Kp4o8RT4EsVs); BuLLMake Products Tech Stack (1O_0ziBocbB6n0RQ_XGlitIWiefa2jPLCjtzqox_9WGo); Global SRI Skill Stack (11LhyanO23ZHNG2uwWF1yckvrzKz8yFGNCdI6obntZPI). Note the SRI sheets describe an older, different stack (Accomplish, OpenHarness, Dify, ClickHouse, Ollama, Gatus). They are a separate generation from the main sheet.

## **2. Short answer: how to combine**

Treat the 33 components as four layers. Each layer has a different state today.

> 1. **BAM build-time (mostly real in source).** Next.js client with Refine, AG Grid, Tiptap, Xyflow, Uppy and tusd, then a Python API (FastAPI, Alembic, Postgres), Temporal workers, Cognee for context, Jinja2 and AST for codegen, Bifrost as the LLM gateway, Keycloak, Langfuse, ClickHouse, NetBird in compose. SOURCE.  
> 2. **The seam from BAM to the runtime (the missing piece).** BAM writes a manifest and codegen modules exist for a FastMCP skeleton, but the stages after the manifest (codegen, gates, tests, certify) are stubs in the registered workflow, and no manifest-to-runtime importer was found. The 10 manifests in CAM backend/docs already use BAM's manifest shape, but they describe the existing Dify flow and code; they do not generate it. SOURCE.  
> 3. **CAM 3.3 runtime (reported, consistent with code).** Dify (3 calls and a loop), MCP Jungle, FastMCP reports, DuckDB and Postgres, PostHog events, an Accomplish-fork UI. SOURCE + REPORTED.  
> 4. **Target (4.0 / sheet roadmap).** Temporal as the runtime orchestrator, Bifrost as the gateway, Assistant-UI or CopilotKit for the chat pane, Cognee plus OKF for shared memory. PROPOSAL.

The practical combination order, consistent with the earlier 3.3 to 3.4 write-up: (a) keep FastMCP as the shared tool seam between both generations, (b) make the BAM manifest to FastMCP skeleton render actually run end to end on one skill (the existing CAM manifests are the first test input), (c) only then swap Dify for Temporal in the runtime, since Dify only does three calls and a loop, (d) decide Jungle vs Bifrost for the gateway (OPEN), (e) add the chat pane last. "3.4" is not defined in any source; this ordering is a PROPOSAL, not a documented plan.

## **3. All 33 components, mapped**

Columns keep the generations apart. The sheet's own BAM/SRI ticks are DOC claims about intent; the source columns are what was seen in the code. Versions in the sheet differ from compose in several places (marked).

| Component | Sheet: in v0.1 / version / layer | Repo (sheet) | Sheet BAM / SRI tick | BAM source (9e6749d) | CAM 3.3 runtime (source) | 3.4 plan | Note |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| **React (Vite)** | Yes / 19.3.1 / 8.3.5 / Frontend | react/react \| vitejs/vite | yes / yes | Not used as Vite; BAM client is Next.js (client/package.json: next, react) | Not found | - | Sheet says Vite, source says Next.js: OPEN which is intended |
| **TypeScript** | Yes / 7.0.2 / Frontend | microsoft/TypeScript | yes / yes | Yes, client dev dependency | Not found (frontend subtree not inspected) | - | - |
| **Refine.dev** | Yes / 5.0.12 / Frontend | refinedev/refine | yes / yes | Yes: @refinedev/core, @refinedev/antd, nextjs-router | Not found | Chat panel sits beside it | Admin UI of BAM |
| **Uppy** | Yes / 6.3.0 / Frontend | transloadit/uppy | yes / no | Yes: @uppy/core, dashboard, tus | Not found | - | Pairs with tusd for BAM uploads |
| **Tusd** | Yes / 2.10.1 / Frontend | tus/tusd | yes / no | Yes: compose image tusproject/tusd v2.10.1 (matches sheet) | Not found | - | Resumable upload |
| **Xyflow (React Flow)** | Yes / 12.12.0 / Frontend | xyflow/xyflow | yes / no | Yes: @xyflow/react | Not found | - | Graph/flow canvas in BAM UI |
| **AG Grid** | Yes / 36.2.0 / Frontend | ag-grid/ag-grid | yes / yes | Yes: ag-grid-community, ag-grid-react | Not found | Likely for report/queue grids (PROPOSAL) | - |
| **Monaco Editor** | Yes / 0.57.0 / Frontend | microsoft/monaco-editor | yes / no | Design doc only (docs/design/09-frontend-design.md); not in client dependencies | Not found | - | Planned manifest/code viewer |
| **Tiptap** | Yes / 3.32.0 / Frontend | ueberdosis/tiptap | yes / yes | Yes: @tiptap/react, starter-kit | Not found | - | SOW editor |
| **File Robot** | Yes / 5.0.0-beta.159 (npm) / 4.9.1 (latest GitHub release) / Frontend | scaleflex/filerobot-image-editor | no / no | Not found | Not found | - | Sheet-only |
| **Assistant-UI** | Yes / 0.15.31 / Frontend | assistant-ui/assistant-ui | no / no | Not found in BAM code or deps | Not found | The middle-chat candidate named in Roadmap #18 (with CopilotKit as alternate) | Absent today |
| **Cognee** | Yes / 1.6.5 / RAG/Context | topoteretes/cognee | yes / yes | Yes: workers dependency; knowledge/cognee_backend.py | Not found | - | Context layer in BAM |
| **Google Open Knowledge Format** | Yes / 0.2 (spec) / RAG/Context | GoogleCloudPlatform/open-knowledge-format | yes / no | BAM stores its own OKF bundle (JSON, hashed); whether it conforms to the Google spec v0.2 is OPEN | Not found | - | See OKF note in the BRAIN comparison doc |
| **Pydantic AI** | Yes / 2.61.0 / RAG/Context | pydantic/pydantic-ai | yes / yes | Planned in docs (TEAM_PLAN E6.1 LLM layer wrapper); not in workers dependencies | Not found | - | Planned, not installed |
| **Jev** | Yes / 0.1.0 / RAG/Context | internal/jev | yes / yes | Open item O-21 in plan docs, not implemented | Not found | - | Internal; repo not seen |
| **Laya** | Yes / 0.4.15 / RAG/Context | NandhaKishorM/laya | yes / no | Open item O-21 in plan docs, not implemented | Not found | - | 'accuracy untested' per BAM plan |
| **ISATVON Compiler** | Yes / 1.0.x / Compiler Engine | Internal Repository | yes / no | BAM contracts implement ISATVON 1.4 (sbam_contracts); sheet says 1.0.x | The 10 CAM manifests use the same shape (describe code, do not build it) | Manifest alignment (step 3 of the 3.4 order) | Version mismatch 1.0.x vs 1.4 |
| **Promptfoo** | Yes / 0.125.1 / Compiler Engine | promptfoo/promptfoo | yes / no | Referenced in 60 files; build_promptfoo_suite is a stub stage | Not found | - | Build-time test, unwired |
| **Jinja2** | Yes / 3.1.6 / Compiler Engine | pallets/jinja | yes / no | Yes: workers dependency; build/codegen/render.py | Not found | - | Real module, unwired in the registered workflow |
| **Abstract Syntax Tree (AST)** | Yes / Python 3.12+ Stdlib / Compiler Engine | python/cpython | yes / no | Yes: stdlib ast in codegen/bodies.py and bundle.py; ast_gate is a stub stage | Not found | - | Real checks, gate stage not wired |
| **Temporal** | Yes / 1.32.1 / Backend/LLM Gateway | temporalio/temporal | yes / yes | Yes: compose temporalio/server 1.31.3 (sheet says 1.32.1), temporalio worker dependency | Not found | Replaces Dify as orchestrator (user plan) | BAM's Temporal is build-time; CAM runtime has none |
| **Bifrost Proxy** | Yes / 2.3.2 (gateway) / core 1.11.3 / Backend/LLM Gateway | maximhq/bifrost | yes / yes | Yes: compose maximhq/bifrost v2.2.6 (sheet says 2.3.2) | Not found; 3.3 manifests name MCP Jungle gateway | Whether 3.4 swaps Jungle for Bifrost: OPEN | Gateway generation differs |
| **OpenConnector** | Planned / pilot (created 29 Jun 2026) / Backend/LLM Gateway | oomol-lab/open-connector | no / yes | Not found | Not found | - | Sheet status: Planned/pilot |
| **FastMCP** | Yes / 4.1.4 / Backend/LLM Gateway | PrefectHQ/fastmcp | yes / yes | Generated-code target: build/codegen renders a fastmcp-loopy 1.0.0 skeleton (render stage unwired) | Yes: reporting_module/mcp_server.py, requirement fastmcp>=3.4.2 (sheet says 4.1.4) | Stays; 16 reports keep their tool | Shared seam between generations |
| **Cube Sandbox** | Yes / 1.8.2 / Testing | cube-js/cube | yes / yes | AGENTS.md names CubeSandbox as a service; sandbox-local profile is non-certifying | Not found | - | Sheet repo column says cube-js/cube (the Cube data layer), owner says Tencent: OPEN, check the repo |
| **e2e (TesterArmy)** | Yes / 0.18.0 / Testing | tester-army/e2e | no / no | Not found; BAM uses @playwright/test | Not found | - | Sheet-only |
| **Docker** | Yes / 29.9.2 / Testing | moby/moby | yes / yes | Yes: compose files | Yes: host.docker.internal in the Dify flow | - | - |
| **NetBird** | Yes / 0.81.5 / Testing | netbirdio/netbird | yes / yes | Yes: compose/netbird/policies.json | Not found | - | Also in SRI 3.0 stack |
| **Alembic** | Yes / 1.20.1 / Database | sqlalchemy/alembic | yes / yes | Yes: api dependency | Not found | - | - |
| **PostgreSQL** | Yes / 18.6 / Database | postgres/postgres | yes / yes | Yes: compose postgres 16.15 (sheet says 18.6) | Yes: psycopg2, system_skills_registry, logic_db | - | Version differs |
| **DBHub** | Yes / 1.5.0 / Database | bytebase/dbhub | yes / yes | Only a question in the plan (J1 dependency registry) | Not found | - | Absent in code |
| **Apache Superset** | Yes / 6.1.0 / Analytics | apache/superset | no / no | Only a question in the plan (J1); no code | Not in CAM harvest. SRIM repo docs (CLAUDE.md) show DuckDB feeding Superset and database/README.md mentions a mcp-tools/reporting/superset path: DOC only | - | Reporting-side tool in the SRIM line, not in BAM |
| **PostHog** | Yes / posthog-js 1.438.24 / Analytics | PostHog/posthog | yes / yes | Referenced in compose/grafana files; not read further | Yes: analytics_posthog_client.py, analytics_events.py | - | - |

## **4. Integration seams: wired vs proposed vs absent**

| Seam | State | Evidence |
| :---- | :---- | :---- |
| Browser to BAM API (Refine, Uppy/tusd, Xyflow, Tiptap, AG Grid to FastAPI) | Wired (SOURCE) | client dependencies and compose; e2e specs call the panels |
| BAM API to Temporal workers (Postgres, Alembic) | Wired (SOURCE); operations unverified | workers/pipeline, compose temporal 1.31.3 |
| Workers to Cognee and the OKF bundle | Wired in source (SOURCE) | knowledge/cognee_backend.py, bundle.py, compose storage/okf |
| Workers to LLM via Bifrost, then Pydantic AI wrapper | Bifrost in compose (SOURCE); Pydantic AI planned only (DOC) | compose maximhq/bifrost v2.2.6; TEAM_PLAN E6.1 |
| Manifest to Jinja2 render to AST checks to Black | Modules real, not wired into the registered workflow (SOURCE) | build/codegen/render.py, bodies.py, bundle.py; stub stages after manifest |
| Generated skill to CubeSandbox test, Promptfoo suite, certify | Stubs (SOURCE); CubeSandbox named in AGENTS.md only | test/stubs.py; sandbox-local profile is non-certifying |
| BAM output to CAM 3.3 runtime (Dify, Jungle, FastMCP) | Absent: no importer found (SOURCE, partial CAM read) | build/manifest.py hardcodes Dify and Jungle defaults |
| CAM runtime: Dify to MCP Jungle to FastMCP tools to DuckDB/Postgres, PostHog | Wired (SOURCE + REPORTED) | CAM backend, SRIM Dify flow yml, reporting_module |
| Temporal and Bifrost in the CAM runtime | Absent in CAM harvest; present only in the 1.5.0-draft agent manifest (DOC, origin unverified) | JSON Manifest folder |
| Chat pane (Assistant-UI / CopilotKit) to Refine admin | Absent (Roadmap #18 PROPOSAL) | no dependency in the BAM client |
| Superset and DBHub reporting layer | Absent in BAM; Superset appears only in SRIM docs (DOC) | BAM plan J1 asks who owns the dependency registry |

## **5. Open-source repos beyond the 33: Repo Library and Leaderboard**

The Repo Library has 55 repo-level rows (OSS repo and Mapping rows) plus 94 MCP servers, 58 "50k+ classics" and 32 MCP references. Verdicts are the sheet's (DOC).

> * **Adopted:** PaddleOCR (replaced Docling for ingestion, Docling now Watch). Used in no inspected code (not found in BAM or CAM).  
> * **Candidate to pilot:** agentgateway (could partly replace Bifrost's MCP/agent traffic governance), CopilotKit (could replace the Accomplish middle pane), Ollama (FDE local models).  
> * **Pilot (BAM/SRI side):** Stirling-PDF, crawl4ai, Paperless-ngx, OCRmyPDF, FreeCAD, ezdxf, KiBot (quote intake and ingestion); Strapi, Cal.com, Umami, Chatwoot, Postiz, Dub, listmonk, react-email, Mautic, Typebot, WAHA (content, outreach and engagement).  
> * **Complements to the stack:** PageIndex and okf-agent-memory beside Cognee and OKF; context-mode and magpie beside Bifrost; agent-memory and mem0 as Cognee alternates; moli for bulk fetching; codebase-memory-mcp as a dev-tool gap filler.  
> * **Skip or reference only:** Odoo, ERPNext, InvenTree, frePPLe, Twenty, Krayin (ERP/CRM, the sheet says skip); harness-sdk, openrig, loop-engineering (reference).  
> * **Leaderboard top 5:** PageIndex, solidcraft, modelcontextprotocol/servers, codebase-memory-mcp, getzep/graphiti (new, company context). onyx is new at rank 10 (company search).

Most of these are tools for BAM's GTM, quote intake and marketing work, or for dev tooling. Only a few touch the combine question: agentgateway, CopilotKit, PageIndex, graphiti and the Cognee alternates.

## **6. What is missing from the list**

> * **Dify and MCP Jungle.** The CAM 3.3 runtime depends on them (SOURCE), yet neither is among the 33 components. The SRI sheets list Dify but not Jungle. This is the biggest gap if the list is meant to describe what runs today.  
> * **DuckDB.** CAM reporting queries it directly (SOURCE). Not in the list.  
> * **Components BAM already uses that the list omits:** FastAPI, Keycloak, Langfuse, ClickHouse, Caddy, ClamAV, MinIO, Redis, Black, pydantic (as contracts), OpenTelemetry and Grafana, Playwright, Next.js and Ant Design (the sheet says React/Vite). All SOURCE in BAM compose or dependency files.  
> * **Manifest-to-runtime importer and registry.** Not a component but a missing link: nothing reads a certified manifest into CAM's system_skills_registry (what populates it is unverified).  
> * **Audit trail, certified bundle format.** The Roadmap itself marks these as gaps (rows 2 and 45).  
> * **Older-generation items in the SRI sheets not in the main list:** Accomplish AI, OpenHarness, Ollama, ClickHouse as the audit store, Gatus, Docstrange, pgvector, OpenTelemetry, Chrome DevTools MCP, Playwright.  
> * **Version drift:** sheet vs compose: Temporal 1.32.1 vs 1.31.3, Bifrost 2.3.2 vs 2.2.6, PostgreSQL 18.6 vs 16.15, FastMCP 4.1.4 vs CAM requirement 3.4.2, ISATVON 1.0.x vs 1.4. OPEN which is the target.  
> * **Cube Sandbox row looks mixed.** The row's repo is cube-js/cube with a Cube REST/SQL API and Tencent Cloud contacts, while BAM's AGENTS.md uses "CubeSandbox" as a code-testing sandbox. Check which project is meant. OPEN.

## **7. Limits of this review**

Source-only. CAM was a partial read (reporting_module/reports and the frontend were not read), so "not found in CAM" is weaker for frontend components. BAM was inspected at commit 9e6749d, CAM at 0d54fd90, SRIM at 5409180. Tests and the manifest validator were not run. Greps were by name, so a component can be present under another name.