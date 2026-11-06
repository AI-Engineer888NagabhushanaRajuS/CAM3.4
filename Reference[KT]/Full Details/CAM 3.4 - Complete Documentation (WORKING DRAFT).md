# **CAM 3.4 - Complete Documentation (working draft)**

Compiled 5 November 2026 from source-code reads (solutionsDigibull/CAM, BuLLMQuote_SRIM, BAM), a cell-level measurement of 364 Drive workbooks (8,324,692 formula cells), and the project research archive. Two things are kept apart in plain wording throughout: what exists today (read in code or measured in files, source cited) and what 3.4 will change (the urgent Centum increment as defined by Nagabhushana on 5 Nov 2026 - Part 1; every 3.4 item here is requirement or intended design, not built runtime). The four engineering diagrams and the live app evidence are embedded in the appendix pages of the packaged PDF at readable resolution, and the full-resolution PNGs live in this same private Drive folder.

## **1. What CAM 3.4 is**

CAM 3.3 is what is built and running: the solutionsDigibull/CAM repository inspected live for this document (Parts 2-6), deployed locally in Docker behind NetBird (mesh IP, no domain). CAM 3.4 is the urgent increment for the Centum engagement on top of that baseline, defined by Nagabhushana on 5 Nov 2026. 4.0 / 4.1 is a later, separate track and stays out of this document. He will send further 3.4 material; this document is reviewed against it before finalization.  
The 3.4 requirements, in his terms (spellings resolved against project artifacts - ISATVON, Jinja2, Monaco):  
1\. JSON-editable execution. Harish's agent / skill / sub-skill definitions exist as ISATVON-format JSON files (Part 1.1). The target: put the generated JSON in and the output follows - JSON + ISATVON + Jinja2 + AST combined. The same pipeline is written in the Centum reporting manifest's own architecture note: "ONE manifest -> Jinja2 template -> AST -> FastMCP builds ONE tool for all 16 reports" (cam_isatvon_manifest.json, v0.1.0 DRAFT, 16 Oct 2026).  
2\. A Monaco editor in the app, so that JSON can be viewed and edited in place.  
3\. Complete dynamicness in reporting. When one value changes, it is mirrored and streamed across all Excel sheets and workbooks; near and far dependents show the change in realtime. Editing must work both before output (in the app) and after output is given. The semantics need team decisions (Part 1.3).  
4\. UI layout: left = the workflow (today the 9-stage RFQ wizard (verified live 5 Nov); to carry agent > skill > sub-skill accordions built from the JSON definitions); middle = an Assistant UI for the LLM (reported broken by NRS; tested live 5 Nov - generic prompts return a 'coming soon' stub, the advertised FG query returned an unvalidated answer; being replaced); right = server-side events and output.  
5\. Runtime: Temporal is present; Jungle is kept for 3.4. Bifrost replaced Jungle on the later track; that replacement is not part of 3.4.  
6\. Reporting and processing work in 3.3 but carry bugs; bug evidence with annotated screenshots is part of this document (Part 1.4).  
Boundaries, stated once and respected everywhere in this document:  
CAM vs Centum. CAM is the parent product deployment (private repo solutionsDigibull/CAM, client-facing at cam.digitalbull.ai). Centum is the internal fork (BuLLMQuote-SRIM lineage) for the Centum Electronics engagement. One lineage, two deployments. This document covers CAM for the Centum RFQ work.  
3.4 vs 4.x. Three dated artifact generations exist and are not mixed: the ten v1.4.0 manifests in the CAM repo (8 APPROVED, 2 APPROVED_INACTIVE; describing the as-built Dify + Jungle tools); the v0.1.0 DRAFT Centum 16-report manifest (Dify + Jungle; the Jinja2 + AST one-tool note); the v1.5.0-draft agent and ten skill manifests (labelled CAM 4.0; Temporal + Bifrost). His 3.4 runtime choice - Temporal present, Jungle kept - matches none of the three exactly and is recorded here as his stated requirement, not as implemented fact.  
Evidence labels. A code comment reads "CAM 3.3 report-only change" (backend/reporting_module/exporter.py line 98). Parts 2-6 are the source-tested 3.3 baseline, and every 3.4 statement in this Part is requirement or design.

### **1.1 The agent/skill JSON layer (Harish's manifests, read 5 Nov 2026)**

Located in the Drive folder "JSON Manifest" (original: harish.t, shared; 12 files). The hierarchy the UI accordions are built from:  
1 agent: "CAM 4.0 RFQ Automation Agent" (CAM_4.0_RFQ_AUTOMATION_AGENT), v1.5.0-draft, DRAFT; declares 10 skills and 40 sub-skills.  
10 skills, each v1.5.0-draft DRAFT (owners Nagabhushan / Parvitha / Akshay with Harish): 01 Input Standardization, 02 Feature Extraction, 03 Feasibility & Risk, 04 Distributor & Source Selection, 05 Supplier RFQ/Quoting Tools, 06 SAP/API Cost Extraction, 07 Quote Validation & Comparison, 08 Costed BOM, 09 Reporting via BullMind, 10 Sales Quote.  
Each skill holds exactly 4 sub-skills (40 in total, 46 steps; every step marked Human or Auto; every skill ends in a human review checkpoint) plus the full ISATVON block (I, S, A, T, V, O, N), a runtime definition, input/output contracts and governance.  
The Centum reporting manifest (cam_isatvon_manifest.json, v0.1.0 DRAFT, infra owner Harish T.): "Centum CAM 16-Report Workbook Generator" - one manifest for all 16 reports, carrying the report list and the business-rule variables (quantity propagation, scrap factor rule, sum/count basis, prototype batch defaults).  
These JSONs are design inputs for 3.4, not proof that the ten future skills are implemented or committed to 3.4; manifest prose alone does not prove execution or codegen exists (Part 1.2).

### **1.2 JSON -> tool: what exists, and what the chain must add**

Exists today (source-verified): the ISATVON format (public repo solutionsDigibull/ISATVON-prompting, v1.4); ten v1.4.0 manifests in CAM backend/docs (8 APPROVED, 2 APPROVED_INACTIVE) describing the as-built tools (written after the code); BAM's real codegen modules for the manifest-to-tool direction (Jinja2 skeleton render, LLM body slots, AST gate, hashed bundle - Part 7.8); and CAM's working report generator, which today is hand-written Python, not manifest-built.  
Must be added for "edit the JSON and the output follows": an importer/loader that takes a manifest into CAM's runtime (nothing inspected loads backend/docs/\*.json, and system_skills_registry is read but written by nothing inspected); the build-chain wiring (BAM's registered build workflow still calls stub stages); and the edit loop behind the Monaco editor - validate the edited JSON against the schema and governance rules (hashes are still "TO_BE_COMPUTED_ON_SAVE"), rebuild or re-parameterize the affected tool, and route execution through it.  
One decision sits on top: whether the 16 reports stay hand-written Python with the manifest as description (Part 7.2's recommendation), or become the one-manifest-one-tool build the Centum manifest describes. This is the same "six tools vs one" question, now grounded in both artifacts; it stays with the team.  
Where the pieces land in today's code (verified live 5 Nov 2026): the web frontend (frontend/apps/web) carries ag-grid-community and ag-grid-react (^35.3.1) but no Monaco, CodeMirror or Ace dependency - the JSON editor is genuinely new. The RFQ UI lives in components/rfq (create form, upload modals, intake progress panel, progress log, version select); no agent/skill accordion component exists (components/skills holds only the Accomplish-fork CreateSkillModal). The backend's only edit/write API today is the CBOM preview editor and the HITL selection endpoints (Part 1.3).

### **1.3 Dynamic dependency propagation: the requirement and its open semantics**

The requirement (his, 5 Nov 2026): when one value changes, the change is mirrored and streamed across all Excel sheets and workbooks; dependent values - direct, relative and far - update in realtime; this must work for edits made in the app before output, and for changes made after the output is given.  
What 3.3 does today (source): in-app editing before output exists, and it is narrower than the requirement. PUT /api/bom/batch-update/{rfq_id} (backend/duck_db_api.py line 161) applies inline cell edits to nine final\_\* fields on the costed-BOM preview, then recomputes the derived columns (is_costed, scrap_percent, abc_classification) via final_selection.recompute_derived_columns - the same function the HITL router uses for final-selection and alternate-MPN choices (backend/hitl_router.py lines 199 and 494-535). Propagation stops there: nothing re-runs downstream skills, nothing re-exports the workbook, and no event streams on edit - the download endpoints (duck_db_api.py lines 238-296) keep serving the latest already-generated file until export_reports runs again. The generator also writes Excel formula strings into the workbook at build time, so dependent cells recompute when Excel recalculates an open file - within that one file only. RFQ versioning already exists (versioned_key / get_active_version, fail-open to the bare rfq_id), so re-issued workbook versions have a naming and tracking mechanism to build on.  
Open semantics for the team (decisions, recorded here, not answered by this document): (a) the source of truth for a change - application state (DuckDB/PostgreSQL) with workbooks regenerated, or the workbook itself; (b) pre-output editing - which fields are editable in-app, and whether an edit re-runs downstream skills in the routing sequence or only the report builder; (c) post-output - whether delivered workbooks are re-issued as new versioned artifacts or patched (live updates inside an already-downloaded Excel file are not an Excel-native capability; expect regenerate-and-redeliver); (d) what streams over server-side events to the right pane - step status (exists today), value-change events, or regenerated artifacts.  
Design direction that fits the existing pieces (proposal, not decided - not yet his approved choice): treat the database as truth - the batch-update edit path and the versioned export naming already point this way - regenerate the affected sheets and workbooks on change, and stream status plus fresh artifacts over the existing server-side-event channel.

### **1.4 UI layout and bug evidence**

User-supplied photo (5 Nov 2026, RFQ-000232 session): left = RFQ Automation Wizard with 7 steps in this photo (the build inspected live on 5 Nov shows 9 stages) (Upload file, Extract features, Get online pricing, ERP & Quoting tools, Analyze feasibility & Risks, Consolidate Pricing Sources, Finalize price) and Create RFQ; middle = Centum chat landing; right = "Quote Readiness Package" with all eight steps marked DONE (standardize SCRUB BOM workbook; standardize QuoteWin Report; standardize Costing Sheet (optional); Build CBOM structure + QuoteWin Pricing; Enrich CBOM with Costing Sheet Data; Resolve Final Cost Selection (HITL gate); Generate CBOM Reports; Export CBOM Reports to Excel) and an Export All Reports button. The photo is displayed-UI evidence, not proof of backend behavior. An annotated copy mapping the three zones to the 3.4 changes lives in this Drive folder: cam34_user_ui_annotated_5Nov2026.png (private, added 5 Nov 2026). Code-level map of the three panes (verified live 5 Nov 2026): the left pane is WORKFLOW_STAGES in App.tsx (lines 63-74) - a NINE-stage pipeline card column; the photo's seven wizard steps are the mainHeadings of stages 1-7, and stages extraction, pricing and risk carry comingSoon: true (greyed-out placeholder wizards that the navigation code never lands on). The right pane is RfqProgressLog (components/rfq/RfqProgressLog.tsx): one row per executed skill showing the exact backend skillName with \[DONE\]/\[FAILED\]/\[RUNNING\] tags - the photo's eight DONE rows - seeded from rfq.getSkillHistory (DB) on selection or refresh and kept live by rfq:skill-progress SSE events; during intake/erpDataSync it adds RfqIntakeProgressPanel, and at the quoteReadiness stage it adds the Export All Reports button (App.tsx lines 1214-1241), which opens PYTHON_BRIDGE /api/bom/export/{rfq_id}/download - the endpoint that serves the latest already-generated workbook (Part 1.3). SSE wiring, end to end: fastapi_router.py's notify_skill_progress (lines 76-92) POSTs each skill event to the daemon at the hardcoded http://192.168.1.18:9234/api/internal/emit-skill-progress; the daemon (browser-api-server.ts line 2208) validates rfqId/skillCode/macroCategory and broadcasts a raw SSE frame carrying event 'rfq:skill-progress' to that RFQ's bucket via sendToRfq (line 2241); the frontend holds one root-level EventSource on GET /events?rfqId=... (pathname-matched, line 2252) and applyRfqSkillProgress maps backend macro_category 0-9 to stages via MACRO_CATEGORY_TO_STAGE (App.tsx lines 81-92). Daemon comments record two past regressions on this path, both fixed in source: named-channel delivery that reached nobody and broke the right pane's live Workflow Status updates, and /events 404ing authenticated EventSource connections because of the token query string. The hardcoded daemon address couples live progress to one LAN IP - the same hardcoded-hosts cleanup Phase 3 already covers; a frontend comment (StageExecutionOutput.tsx lines 133-134) records that nothing is registered at macro_category=7 in system_skills_registry. Reopen/resume: rfqGetProcessStage maps the tracked stage, an export-existence check forces landing on Quote Readiness when a workbook already exists, and resume fires GET /api/dify/start/{rfq_id}. The 3.4 mapping: the left card column becomes the agent/skill/sub-skill accordions from Part 1.1 (note three of nine stages are placeholders today); the middle pane (broken per his report, not reproduced) is replaced by the Assistant UI; the right pane's SSE channel and progress log already exist and stay.  
Bug evidence splits three ways and is labelled as such: reproduced bugs (verified live on 5 Nov 2026, 4:33-4:58 PM IST - a dedicated task peer, instinct-cam34-doc, was enrolled into the solutions NetBird mesh under NRS's authorization through device sign-in with the vault-saved solutions@digibull.ai Google credential, and a read-only hands-on check of the running app at http://100.121.36.255:5180/#/ was performed; no workflow was run, no data changed, no skill invoked); user-reported issues (his messages and photo, attributed); source-only findings (repo evidence, e.g. backend/Test_fixes/BOM_MATRIX_QTY_ROLLUP_BUG.md and EXCEL_LOAD_PERFORMANCE.md). Screenshots captured live during the check are stored privately in the same Drive folder and referenced by filename; document assets stay private. Results are in 1.4.1.

### **1.4.1 Hands-on verification results (live read-only check, 5 Nov 2026, 4:33-4:58 PM IST)**

\- Three-pane layout reproduced live: left 9-stage RFQ Automation Wizard, middle Centum Assistant, right results/SSE pane (cam34_app03_three_pane.png). The login page is branded "CAM 3.3" (cam34_app02_login.png); the status bar shows SESSION ACTIVE and OFFLINE MODE; the model selector shows Qwen2.5vl:3b.  
\- RFQ-000232 loads the QUOTE READINESS PACKAGE with the same eight \[DONE\] rows as NRS's photo (Standardize SCRUB BOM workbook ... Export CBOM Reports to Excel) plus the Export All Reports button (cam34_app05_rfq232_done.png). The left wizard shows stages 1, 4, 6 checked and 2, 3, 5, 7 locked.  
\- Middle-pane Assistant, two bounded results: a generic free-text prompt returned the canned stub "This capability is coming soon. For now, try asking things like 'How many FGs does RFQ-000167 contain?'..." and then Task Completed (cam34_app07_stub.png); the advertised query "How many FGs does RFQ-000167 contain?" returned "RFQ RFQ-000167 contains 1 FG." (cam34_app12_query.png) - a returned value, not independently validated against the underlying RFQ data. One query shape verified; no generalization to other query types.  
\- Export All Reports verified working in this build: click instrumentation shows the button's handler calls window.open("http://100.121.36.255:3010/api/bom/export/RFQ-000232/download"), matching the repo source (App.tsx L1214-1241); a direct GET of that URL returned HTTP 200 with a valid 256,521-byte xlsx (cam34_app17_fresh.png shows the view). A valid file and HTTP success say nothing about the formula correctness of the contents.  
\- Stage-9 Reports & Analytics is an embedded Apache Superset dashboard served on the same host (port 8088, dashboard id 1, embedded UUID 89c11121-01af-4da7-820d-6f4475796c19); it loads 12 chart slices and displays populated metrics (cam34_app19_superset.png). All dashboard numbers are displayed values, not independently validated aggregates.  
\- Observed navigation limitation (single session, not confirmed as a defect): after the wizard advances to stage 9, stage 8 shows a lock and does not navigate; re-selecting RFQ-000232 in search shows "RFQ ID already exists" and stays on stage 9 (cam34_app14_stage8_locked.png). A fresh page load restores the Quote Readiness view.  
\- Runtime topology evidenced live: Vite dev-mode frontend on :5180 (unminified modules served from the server's C:/Users/ADMIN/Downloads/accomplish-ui tree), daemon RPC on :9234, export service on :3010, embedded Superset on :8088.  
\- Not exercised (outside the authorized read-only scope): live rfq:skill-progress SSE during a skill run, the PUT /api/bom/batch-update/{rfq_id} edit surface, and any workflow or skill invocation. The pre/post-edit export comparison from the earlier checklist therefore remains untested.

### **1.4.2 CAM 3.4 design mapping: left pane becomes agent > skill > subskill (design, not runtime)**

NRS's clarification of 5 Nov 2026, 4:57 PM IST: the left pane's fixed workflow-stage cards become an expandable agent > skill > subskill hierarchy driven by Harish's ISATVON JSON manifests (1 agent, 10 skills, 40 sub-skills, 46 steps; Part 2), and the right pane holds both results and live workflow progress. This is recorded as intended 3.4 design only: the deployed build inspected on 5 Nov still shows the fixed 9-stage wizard (1.4.1), and no JSON-driven skill tree is claimed as implemented runtime. The mapping between the current 9 stages and Harish's 10 skills / 40 sub-skills is one of the points his promised 3.4 material should confirm.

## **2. The system 3.4 builds on (measured from source)**

Sources: solutionsDigibull/CAM at commit 0d54fd9 (API harvest; the harvest copy lacked backend/reporting_module/reports/\* and templates, which were read directly from the live default branch on 5 Nov 2026; frontend subtrees partially read on 5 Nov 2026 (dependencies, App.tsx workflow-stage and SSE wiring, pages, components/rfq including the progress log, components/skills, auth modules)) and BuLLMQuote_SRIM at commit 5409180. Runtime-shape claims (versions, DB counts) come from the 27 Oct 2026 engineering session documents and are attributed to them.

\[Diagram D1 - the current system, measured from source: cam34_d1_runtime.png in this Drive folder, updated 5 Nov 2026\]

### **2.1 One RFQ, end to end**

> 1. **Dify 1.14.2 DMR** (external orchestrator; flow file dify-orchestration/Dify_DMR_RFQ_Flow.yml in BuLLMQuote_SRIM, 575 lines) starts with the RFQ id.  
> 2. Dify calls **GET /pipeline/routing-sequence/{rfq_id}/RFQ_Flow** on the CAM FastAPI service (backend/fastapi_router.py) and receives the skill list and current skill index. The routing sequence is a single jsonb array column on quote_routing_profiles.  
> 3. Dify loops: per skill it calls **POST /tool/execute** (fastapi_router.py line 223). The router checks the routing profile (skills can be toggled off), calls the tool through the MCP gateway (tool_calling.py call_tool, blocking, up to 300 s), updates the skill index, and posts progress to the UI (notify_skill_progress to emit-skill-progress).  
> 4. An if-else node decides whether to continue. A final HTTP node triggers the human-in-the-loop step (port 9234, trigger-hitl).  
> 5. The tools are FastMCP servers. The reporting server (backend/reporting_module/mcp_server.py) exposes **six tools**: cbom, enrich_erp, enrich_costing_sheet, resolve_final_selection (the human gate), generate_reports, export_reports. Intake is separate: scrub_mcp_server.py plus the quote-win, ERP and costing-sheet processors.  
> 6. Data: **DuckDB** holds CBOM and report tables; **PostgreSQL** holds routing and the system_skills_registry table.  
> 7. export_reports builds one workbook by calling a fixed sequence of build\_\*\_sheet functions (exporter.py, 388 lines): the 76-column CBOM tab plus the 16 report sheets (Part 5).

### **2.2 Component inventory**

| Component | Role | Evidence |
| :---- | :---- | :---- |
| Frontend (fork of Accomplish) | Chat/agent UI shell and report views; progress via emit-skill-progress | Harvest note; backend posts progress events |
| Dify 1.14.2 DMR | RFQ orchestration loop; HITL trigger | Dify_DMR_RFQ_Flow.yml, 575 lines |
| FastAPI backend | Routing-sequence API, tool execution, upload/start, run tracking | fastapi_router.py; upload_server.py (GET /api/dify/start/{rfq_id} L230; rfq_process_tracking writer L274-315) |
| MCP Jungle v0.4.5 | Gateway for Standard_BOM_Flow | 27 Oct 2026 session documents |
| Bifrost v2.2.3 | Gateway for RFQ_Flow (moved from Jungle on 28 Sep 2026, per the same session documents) | 27 Oct 2026 session documents |
| FastMCP reporting server | The six reporting tools | reporting_module/mcp_server.py |
| FastMCP intake servers | Scrub BOM, QuoteWin, ERP, costing-sheet ingestion | scrub_mcp_server.py and processors |
| DuckDB | CBOM and 16 report tables | SRIM mcp-tools/shared/db_config.py (hardcoded C:\\SRIM-DB-SETUP\\Databases\\bom_storage.duckdb, intake side; CAM's reporting_module uses REPORTING\_\* env vars over 3 DuckDB files - verified live 5 Nov 2026) |
| PostgreSQL 18 | quote_routing_profiles.routing_sequence (jsonb), system_skills_registry; 6 databases reported | db.py; 27 Oct 2026 session documents |
| PostHog | Observability | July 2026 blueprint |

### **2.3 Defects found in the source, with file and line**

> * **Routing gate fails open.** fastapi_router.py L266-271 (verified live 5 Nov 2026): if the routing_sequence lookup itself errors, execution proceeds ungated; the code comment says so verbatim. The gate checks membership against the union of every profile's routing_sequence (db.py L353-367), so it is not order enforcement.  
> * **A skipped tool still returns success**, increments the skill index (L289), clears hitl_required (L294) and returns HTTP 200 with skipped:true (L311-314).  
> * **HITL router hardcodes** the distributor\_\_detect_alternates tool name (hitl_router.py L345) and its own comments (L338-341) admit HITL state is not version/profile-scoped.  
> * **Hardcoded hosts: progress listener 192.168.1.18:9234 (fastapi_router.py L89); reporting server 192.168.1.27:8005 (mcp_server.py L19); host.docker.internal:5000 and :9234 in the Dify flow (lines 207, 348, 518); a Windows-only DuckDB path in SRIM's mcp-tools/shared/db_config.py. All re-verified live 5 Nov 2026.**  
> * **Registry writers absent:** the inspected CAM and SRIM source contains no code that writes quote_routing_profiles.routing_sequence or the system_skills_registry. How routing rows and skills are created today is with the team (question sent).  
> * **Credential hygiene: committed defaults were found in source: a default Postgres connection string with a literal password in CAM backend/db.py (verified live 5 Nov, lines 27-34) and fixed dev/test credentials in the daemon test-login bypass frontend/apps/daemon/src/test-login.ts (verified live 5 Nov; auto-disabled in production builds, overridable via environment variables). The harvest-era findings of a hardcoded password in LoginPage.tsx and a default JWT secret were not re-confirmed in the live files checked 5 Nov (LoginPage.tsx and the daemon auth modules carry neither). There is no evidence any default is a valid live credential; rotation is a precaution. Research copies are redacted; originals untouched.**

## **3. The RFQ domain the reports serve**

\[Diagram D4 - the RFQ domain: cam34_d4_domain.png in this Drive folder\]

### **3.1 The business pipeline**

Centum Electronics (defence/EMS manufacturer, Bengaluru) engaged the vendor to automate the Enquiry-to-Quote (E2Q) sourcing workflow (origin: face-to-face sessions 21-22 Nov 2024, formalized 23 Dec 2024; project documents). A customer sends a BOM; sourcing prices every line, chooses suppliers, and returns a quotation. The legacy toolchain being replaced: **Scrub BOM** (BOM cleaning), **QuoteWin** (supplier quotes and awards), **SupplyWin**, **Drills** (BOM conversion), **PCN via Accuris**; ERP is **InforLN**; mail is Outlook SMTP. The computation CAM reproduces: **Scrub BOM -> QuoteWin awards -> CBOM (costed BOM) -> 16 reports**. The hand-assembled "Internal" workbook remains the deliverable that backs the LOA (Letter of Award) numbers.

### **3.2 Every project folder tells the same story (all 22 folders censused)**

| # | File pattern | What it is | Role |
| :---- | :---- | :---- | :---- |
| 1 | CE-00XXXX-\<customer\> - SCRUB BOM \<date\> Rev N.xlsx | Cleaned customer BOM | INPUT |
| 2 | AWARDS_PART_NUMBER_LISTING\_\<proj\>\_FLOAT\_\<date\>.xlsx / ...\_QW File.xlsx | QuoteWin awards export | PRICING INPUT |
| 3 | 00XXXX costing sheet.xlsx | Buyer's manual price entry for non-QuoteWin parts (21 columns, one tab per volume) | MANUAL PRICING INPUT |
| 4 | CE-00XXXX-...\_Internal\_\<date\>.xlsx | The full costed workbook shipped internally; basis of the LOA | MAIN OUTPUT |
| 5 | \<id\>-BOM Matrix.xlsx / BOM_Matrix\_\<runid\>\_\<timestamp\>.xlsx | The CAM tool's 21-tab report, often renamed by hand | AUTOMATED OUTPUT |
| 6 | CBOM_Report_RFQ-XXXXXX\_\<timestamp\>.xlsx | Newest (2026) CAM report generation; adds the 76-column database CBOM tab | AUTOMATED OUTPUT |

Version control is by filename: "Copy of", "(1)", "Fixed", "amended" duplicates exist in most folders. (Source: RE 1, INSTINCT BRAIN > Domain Knowledge.)

### **3.3 The settings tables every formula reads (measured in the master sample workbook, CE-005405)**

> * **Currency:** to-USD rates (sample: EUR 0.93, INR 83.5, USD 1).  
> * **Scrap factor by unit-value class:** A (\>= $1.25):1%;B($0.25-1.25): 2%; C (\< $0.25): 5%.  
> * **Batch Qty:** requirement qty, batch qty, batch count, per assembly per volume.  
> * **Supplier master:** currency, type, RFQ method. Payment terms are not mapped, which is why the Batchwise Cashflow tabs ship all-zero (Part 6).

### **3.4 The 2026 CBOM provenance model (the good foundation to keep)**

The 2026 CBOM_Report generation adds a 76-column CBOM tab that exposes the underlying database: bom_item_id (UUID); a four-way provenance model per attribute (\<attr\>\_costing, \<attr\>\_erp, \<attr\>\_qw, final\_\<attr\> for manufacturer, UOM, price, currency, supplier, package qty, MOQ, lead time); validation flags as data columns (is_costed, moq_qty_present, pkg_qty_present, pkg_qty_lte_moq, is_price_same, is_mpn_same, is_data, is_assembly); plus batch_qty, volume_qty, scrap_percent, abc_classification, recurring_count, parent_line_no. What used to live in helper formulas is now data. Real example (RFQ-000016 row 2): capacitor 1080636434 - customer BOM says "Murata", QuoteWin awarded "MURATA", price 0.144 USD, supplier Future Electronics, pkg 1000, MOQ 1000, lead time 25, scrap 5% (C-class), batch 2850; alternates (Kyocera, SEM, Vishay, Yageo) appear as separate rows for the same CPN. (Source: RE 1.)

## **4. The formula system, measured**

This part answers the question that started the reverse engineering: "where are the 50k formulas written?" Sources: (1) CAM formula extraction folder - every authored formula string from the SRIM and CAM repos and every formula cell from 364 Drive workbooks; (2) Analytics folder - function mix, crosswalk, generation-logic proof; (3) INSTINCT BRAIN > Domain Knowledge, Domain 4.

\[Diagram D2 - the formula layer: cam34_d2_formulas.png in this Drive folder, updated 5 Nov 2026\]

### **4.1 Authored vs generated: the real numbers**

> * **Authored logic is about 300 templates, not 50,000 formulas.** 298 formula-string write sites producing 210 distinct strings live in BuLLMQuote_SRIM at mcp-tools/reporting/superset/reports/\*.py (16 report modules, commit 5409180) plus templates/formula_templates.py. The Drive mirror of SRIM lacks reports/ and templates/ - only the live GitHub repo has them. Update, 5 Nov 2026 (direct reads of the live CAM repo): the CAM repo does hold the authored report formulas - backend/reporting_module/reports/ has 20 modules, the same 16 families plus 4 EXPERIMENTAL A-class PivotTable variants (\*\_aclass). A literal-tokenizer count run on both repos with one method gives CAM 195 formula-string sites / 169 distinct templates versus SRIM 171 / 156 for the shared modules (counting methods differ, so use this pair for the CAM-vs-SRIM comparison, not the 298/210 grep figure). 13 of the 16 shared modules differ; only mech_em_nre, part_num_vs_mfg_num and pcb_nre_fai_charge are byte-identical. CAM's package is the newer evolution of SRIM's.  
> * **The "50k" are generated cells.** 364 workbooks scanned, 187 contain formulas: 8,324,692 formula cells raw, 6,575,191 after removing duplicate copies. 36 workbooks exceed 50,000 formula cells each; the largest single output is 167,858 (5673 LAM Node Board Internal). Each builder writes one formula string per cell per row, so one template expands into thousands of cells.  
> * **The 20 sheets in "Synthetic Scrub & QW Files" contain zero formulas** (58 sheets, 4,323,125 cells, all static values; checked by XML scan and by live formula render). Test fixtures therefore never exercise formula correctness; regression tests need golden outputs from the real project workbooks.

### **4.2 Where the cells concentrate (unique cells, by workbook class)**

| Class | Workbooks (unique) | Formula cells (unique) | Style fingerprint |
| :---- | :---- | :---- | :---- |
| Internal workbook (human-built) | 48 (45) | 3,227,417 | VLOOKUP-led (353,748 cells); 4,706 volatile-function cells; 14 #REF! cells |
| BOM Matrix (tool output) | 32 (29) | 1,524,972 | INDEX/MATCH inside IFERROR; UPPER/TRIM-wrapped keys; zero VLOOKUP, zero #REF! |
| CBOM Report (tool output) | 20 (20) | 731,891 | Same tool fingerprint |
| Other | 37 (27) | 1,085,795 | Mixed |
| QuoteWin / awards | 9 (2) | 3,346 | VLOOKUP into external workbooks |
| Scrub BOM | 41 (25) | 1,770 | SUM / COUNT / SUMPRODUCT only |

A file's function histogram identifies its maker: humans use VLOOKUP; the tool uses INDEX/MATCH + IFERROR + UPPER/TRIM (the UPPER/TRIM survives booleans stored as the string 'TRUE'). Tool outputs contain no volatile functions and no #REF! formulas in the measured set.

### **4.3 The twelve formula families (the whole computational contract)**

Measured in the master sample workbook (CE-005405, 422,645 formula cells across 43 tabs). Roughly a dozen patterns, repeated per row, per volume, per assembly - which is exactly why one wrong pattern can amplify into a 3.45x wrong total (Part 6).

| # | Family | What it computes | Real formula from the file |
| :---- | :---- | :---- | :---- |
| F1 | Currency conversion | FX rate per line; converted price = original x rate | =INDEX(Currency!$B$2:$B$4, MATCH('CBOM Proto'!$J3,Currency!$A$2:$A$4, 0)) |
| F2 | Extended cost (line roll-up) | qty x unit price; per-unit from extended; Ext Vol Qty = Part Qty x volume | ='CBOM Proto'!$F10*'CBOMProto'!$E10 |
| F3 | Volume/batch pull | Each CBOM VL tab pulls its volume column from Batch Qty by assembly name | =INDEX('Batch Qty'!$C$2:$C$12, MATCH('7.0 CBOM VL-1'!$C10,'BatchQty'!$A$2:$A$12, 0)) |
| F4 | Shared-CPN conditional roll-up | Sums extended prices only for lines of this assembly; the AE=AH guard prevents double-counting shared CPNs | =SUMPRODUCT('CBOM Proto'!$N$25:$N$1754, --($B$25:$B$1754=$C10),--($AE$25:$AE$1754=$AH$25:$AH$1754)) |
| F5 | Validation counters (QA block on every CBOM tab) | Total/unique/shared CPNs, uncosted lines, price/MPN mismatches vs Scrub BOM, missing MOQ/SPQ/commodity, Pkg>MOQ violations | =COUNTIFS('CBOM Proto'!$AO$25:$AO$1754, "=1", 'CBOM Proto'!$AF$25:$AF$1754, TRUE) |
| F6 | Excess inventory | First-match identity lookup (assembly lines excluded), SUMIFS requirement totals, MAX(demand,stock) arithmetic: excess, shortage, net buy, net excess cost | =SUMIFS('7.0 CBOM VL-1'!$AW$25:$AW$1754, '7.0 CBOM VL-1'!$C$25:$C$1754, 'Ex Inv VL-1'!$A5,'7.0CBOMVL-1'!$AH$25:$AH$1754, FALSE) |
| F7 | A-Class parts (spend concentration) | The few parts carrying \~80% of cost; MOQ turns and over-buy exposure | =IFERROR({ext_vol}/{moq},"-") and share-of-spend ratios |
| F8 | Revision history | Same CPN pulled from current CBOM; OLD vs NEW columns; delta and % delta per part and volume | =VLOOKUP($D6,'7.0CBOMVL-4'!$C$24:$AW$1080, 2..5, 0) |
| F9 | BOM Matrix (customer-facing matrix) | \~6,900 part x assembly lookups per tab; SUMPRODUCT grand totals; cross-check row vs CBOM Summary | =VLOOKUP(T$4,'CBOMProto'!$C$1:$G$22, 3, FALSE) |
| F10 | Sum & Count (structural reconciliation) | Per assembly: does the Scrub BOM sum/count equal the Proto and VL sums/counts; Is Sum Same / Is Count Same flags | =IFERROR(AVERAGEIFS('Scrub BOM (1)'!$G$2:$G$4920, ...A..., $A2, ...B..., $B2), 0) |
| F11 | Part Num vs Mfg Num (identity check) | Does each Part Number + MPN pair exist in the Scrub BOM; TEXT() both sides to survive number-vs-text drift | =SUM(INDEX((TEXT('Scrub BOM (1)'!$B$2:$B$4920,0)=TEXT($A2,0))*(TEXT($E$2:$E$4920,0)=TEXT($B2,0)),0,1)) > 0 |
| F12 | Cashflow, lead-time, price control | Payment-term days parsed from text x buy value; share of parts per lead-time bucket; pivot-driven spend split (Centum/TNP/CNP) | =$B4*IFERROR(NUMBERVALUE(LEFT($A4, FIND(" ", $A4))), 0) |

F5, F9, F10 and F11 are already tests - they just live in Excel, where they can silently rot (the shipped #REF! errors and "Not Matching" cross-check grids are the proof). Moving the twelve families into code with the validation block intact is the lowest-risk migration path, and it is what the 3.4 report fixes amount to. (Source: Domain 4.)

### **4.4 How the generator writes formulas (seven rules read in the SRIM code)**

> 1. **One f-string per cell per row.** No Excel-level fill-down: every row receives its own written string, row number substituted per data row (A{r}, H{r}).  
> 2. **Row anchoring:** current row = len(rows)+1 (ex_inv_vl_rows) or data_start + index; the part-number key cell is always column A of the same row.  
> 3. **Every lookup wrapped in IFERROR:** numeric columns fall back to 0, text columns to "" (commented in \_index_lookup). This is why tool outputs ship no #REF!/#N/A in the measured set.  
> 4. **Bounded ranges, not full columns:** \_bounded() builds INDEX(sheet!$C:$C,$AL$1):INDEX(sheet!$C:$C,$AK$1) with AL1/AK1 literal integers computed in Python; Mech & EM NRE and PCB use fixed $27:$282.  
> 5. **Volume loop:** one sheet per volume, proto first; Volume 1 references Ex Inv VL-proto only when has_proto is true (code comment: avoids a latent #REF!).  
> 6. **Lookup shapes:** attribute =IFERROR(INDEX(bounded col, MATCH(cpn, bounded C, 0)),0); duplicate-CPN sums =SUMIFS(value, C, cpn, AH, "\<\>TRUE"); two-key lookup MATCH(1, INDEX((A=fg)\*(C=cpn)\*(UPPER(TRIM(AF))="TRUE"),0),0); delta vs previous volume =IFERROR(ABS(INDEX(prev!O$5:O$1029, MATCH(...)) - O{r}),0).  
> 7. **Not formulas:** Price Validity and Effective Date in BOM Matrix are written as values; conditional-format rules (for example =NOT(AND($X2=TRUE,$Y2=TRUE)) in Sum & Count) are FormulaRule objects, never cell formulas.

Each of the 16 report modules is a Python port of a named Laravel PHP exporter (module docstrings name BomMatrixFormatExportExcelFormula.php, CBOMVolumeSheetExcelFormula::generateRows, ExcessInventoryVolumeSheetExcelFormula, SummaryExportExcelFormula = Tab8Context + Tab8Computer + Tab8Merger, and the BlockthreeController / MissingNotesController / PriceControlController methods). The PHP source itself is not reachable, so the port claim rests on the docstrings. (Source: 4_generation_logic_overview.md and the 16 logic\_\*.md files in the Analytics folder.)

### **4.5 Proof by re-execution**

Method: for real CBOM_Report workbooks, rebuild each builder's input from the workbook's static cells, call the real builder from the repository file, and compare every generated formula string with the actual cell string. (Currency/DB helper imports stubbed - they affect values, not formula text.)

| Report | Cells compared | Exact | Mismatch | One-sided |
| :---- | :---- | :---- | :---- | :---- |
| BOM MATRIX (4 workbooks, data rows + row-7 header SUMs) | 13,586 | 13,586 | 0 | 0 |
| A CLASS PARTS (11 workbooks) | 39,281 | 38,805 | 0 | 476 (two extra formula columns in one older workbook, CE_005603) |
| PCB NRE & FAI Charge (4 workbooks) | 20 | 20 | 0 | 0 |
| Ex Inv VL-n (Test_05, Aug 25) | 11,253 | 11,253 | 0 | 0 |
| Ex Inv VL-n (Sep 21, Sep 22, Oct 5 workbooks) | 15,872 | 14,848 | 1,024 | 0 |
| **Total** | **80,012** | **78,512 (98.1%)** | **1,024** | **476** |

Two measured details matter for 3.4:

> * The row-7 header SUMs in BOM MATRIX (for example =SUM(R9:R128)) are produced by the builder at reports/bom_matrix.py line 329 in SRIM (verified at mcp-tools/reporting/superset/reports/bom_matrix.py) and line 358 in CAM's newer copy (backend/reporting_module/reports/bom_matrix.py); including them is what takes the BOM Matrix proof to 13,586/13,586. Scope note, 5 Nov 2026: this proof ran against the SRIM-era builder; since CAM's reporting_module differs in 13 of the 16 shared modules, re-running this proof against CAM's reporting_module is the right Phase-1 test-base step.  
> * All 1,024 Ex Inv mismatches sit in columns L and N. Measured facts: the Aug 25 workbook matches SRIM main exactly (at both main and the pinned commit, ex_inv_vl.py line 156 reads ROUNDUP(J{r}\*(1+K{r}),0)); the Sep 21, Sep 22 and Oct 5 workbooks carry a blank-scrap guard, IF(K="",0,K). Update, 5 Nov 2026 (direct read of the live GitHub repos): the guard is present in CAM's own generator, backend/reporting_module/reports/ex_inv_vl.py lines 182 and 185 (ROUNDUP(J{r}\*(1+IF(K{r}="",0,K{r})),0), with a comment at line 175 describing it), and absent from SRIM main's copy (lines 156-158). The four \*\_aclass report modules the CAM exporter imports (lead_time_fg_aclass, price_control_aclass, lead_time_consolidated_aclass, batchwise_cashflow_aclass) also exist in the CAM repo, each marked EXPERIMENTAL (A-class PivotTable variants); earlier notes said they were missing because the harvest zip never included CAM's reports package. Family-by-family check, 5 Nov 2026 (templates from both repos matched against five shipped workbooks, 28 Jul to 5 Oct): the Ex Inv guard switches from the SRIM form to the CAM form between 15 Sep and 21 Sep (28 Jul: 1,364 SRIM-form cells and 0 CAM-form; 21 Sep: 116 CAM-form and 0 SRIM-form; same pattern on 22 Sep and 5 Oct). CAM's Lead Time FG / Consolidated cross-sheet SUMPRODUCT links (absent from SRIM entirely) first appear in the 21 Sep workbook. CAM's CBOM boolean form ($AF=TRUE instead of LOWER(TRIM(AF))="true") and SUMIFS-based patterns are present in every workbook tested, including 28 Jul, so CAM's generator was already newer than SRIM main for those families by late July. Still not established: whether CAM's reporting_module is the exact generator production runs today, and any line-level history (both repos are single squashed commits). 3.4 consequence: Phase 1 must fix the generator that actually produces today's workbooks; the measured evidence now identifies CAM's reporting_module as a newer variant than SRIM main for at least the Ex Inv family.  
> * Mech & EM NRE could not be proven: the sheet is named "Mech &EM NRE" in the workbooks and the sample set showed 0 data rows under the name used. The remaining untested builders (cbom_vl, summary, price_control, batchwise_cashflow, revision_history, sum_and_count(+detailed), lead_time(+consolidated), missing_notes, part_num_vs_mfg_num) take payloads from database queries that cannot be rebuilt from sheet cells alone.

### **4.6 Evolution and anomalies (measured)**

> * **Style switch:** Sep 2025 workbooks are VLOOKUP-only; from Dec 2025 onward outputs are INDEX/MATCH. IFERROR's share of formula cells rose from \~35% (Dec 2025) to 55-65% (Jul 2026) and has stayed flat; UPPER rose 10% to 16%.  
> * **Anomalies in shipped files:** 14 #REF! cells inside formulas (Internal workbooks only; tool outputs have 0); 4,706 volatile-function cells (Internal only; largest CE-005673 with 762); whole-column references in 813,476 BOM Matrix + 309,928 CBOM Report cells (slow recalculation on large files); 71,036 Internal + 52,308 BOM Matrix + 31,766 CBOM formulas longer than 500 characters; 39 of 187 formula workbooks are duplicate copies.

## **5. The 16 reports**

constants.py SHEET_NAMES lists the CBOM tab plus these 16 report sheets. generate_reports writes the 16 report tables; export_reports assembles the workbook through a fixed sequence of build\_\*\_sheet calls. Builder modules live in BuLLMQuote_SRIM mcp-tools/reporting/superset/reports/; each has a full per-report logic document in the Analytics > Generation Logic folder (docstring, constants, function list, every authored formula site with line number).

| Report sheet | What it answers | Builder module | Proof status (Part 4.5) |
| :---- | :---- | :---- | :---- |
| BOM Matrix | Customer-facing part x assembly matrix with grand totals and summary cross-check | reports_bom_matrix.py | Proven 13,586/13,586 exact |
| Ex Inv VL (proto..n) | Excess inventory, shortage, net buy and net excess cost per volume | ex_inv_vl.py | 26,101/27,125 exact; all mismatches in cols L/N from the generator variant above |
| A Class Parts | Spend concentration (A-class) and MOQ turns | aclass_parts.py | 38,805 exact, 476 one-sided (one older workbook) |
| PCB NRE & FAI Charge | Non-recurring engineering and first-article-inspection charges | pcb_nre_fai_charge.py | Proven 20/20 exact |
| Mech & EM NRE | Mechanical and electro-mechanical NRE | mech_em_nre.py | Not proven (sheet-name mismatch in test set) |
| CBOM VL | Costed BOM per volume | cbom_vl.py | Not tested (DB-derived payload) |
| Summary | Rollup with SUBTOTALs and revision compare | summary.py | Not tested (DB-derived payload) |
| Price Control | Spend split Centum/TNP/CNP, pivot-driven | price_control.py | Not tested |
| Batchwise Cashflow | Payment-term days x buy value per batch | batchwise_cashflow.py | Not tested |
| Revision History | Old vs new quote per part and volume, deltas | revision_history.py | Not tested |
| Sum and Count / Sum and Count Detailed | Scrub vs CBOM structural reconciliation per assembly | sum_and_count.py / sum_and_count_detailed.py | Not tested |
| Lead Time FG / Lead Time Consolidated | Lead-time distribution per FG and overall | lead_time_fg.py / lead_time_consolidated.py | Not tested |
| Missing Notes | Notes and gaps the buyer must resolve | missing_notes.py | Not tested |
| Part Num vs Mfg Num | Identity check of Part Number + MPN pairs vs Scrub BOM | part_num_vs_mfg_num.py | Not tested |

Two defect notes already exist in the repo (backend/Test_fixes/): **BOM_MATRIX_QTY_ROLLUP_BUG.md** (BOM Matrix quantity ignores the parent sub-assembly quantity, proven from output data) and **EXCEL_LOAD_PERFORMANCE.md** (slow Excel open; structural analysis, never timed). The harvested CAM copy lacked the reports package, so the builder modules named above are SRIM's; CAM's own backend/reporting_module/reports/ was read live on 5 Nov 2026 (20 modules: the same 16 families plus 4 EXPERIMENTAL \*\_aclass variants) and differs from SRIM in 13 of the 16 shared modules (Part 4.1), so CAM's copies are the ones Phase 1 must fix.

## **6. Quality: what actually shipped, and the rules 3.4 must encode**

### **6.1 Measured in the shipped corpus (all 22 project folders, 19 Internal workbooks, 18 CAM reports)**

> * Only 5 of 19 Internal workbooks shipped error-free. CAM matrices ship thousands of #N/A cells (lookup misses = parts the matrix could not resolve) and hundreds of #REF! cells. Worst single case: CBOM_Report_RFQ_000016 'Ex Inv VL-1' with 8,840 #REF! cells (entire Scrap columns broken) - a CAM-generated report shipped with broken references.  
> * Clone-and-edit assembly is proven: the 5615 Internal carries stray tabs from two other projects ('CE-005399', 'CE-005078\_ 1883'); scratch tabs (Sheet1/Sheet3/'%') survive in several deliverables.  
> * Dead reports shipped: Batchwise Cashflow all-zero with supplier type "(unspecified)" (payment terms never joined); Revision History OLD columns all "-" (no baseline loaded); A CLASS PARTS full of "-" placeholder rows.  
> * Type inconsistency: booleans appear both as real booleans and as the string 'TRUE' (mfg_part_num_in_scrub_bom); the BOM Matrix formulas compensate with UPPER(TRIM(...))="TRUE" - one export quirk away from silently blank columns.  
> * Fixed-range anchors in human workbooks (='Ex Inv Proto'!$V$219, $27:$282): insert rows past the anchor and totals go stale silently.  
> * Guard cells that guard nothing: =K3=K4 volume-check booleans sit unread in row 2; nothing aggregates or alerts on FALSE.  
> * Matrix uniqueness hazard: BOM Matrix INDEX/MATCH takes the first match on a duplicated CPN - the exact bug the project's own Matrix BOM issue deck warns about.  
> * Manual price entry without provenance: Non-QuoteWin Matrix values are typed literals with no author or time.

### **6.2 The documented incident and the expert guardrails**

1 Nov 2025, project CE-005570: costed BOM output Rs 20.0 lakh vs LOA Rs 5.8 lakh (+245%). Root causes traced to MOQ misapplication (MOQ cost was 84.68% of the wrong total vs 5.25% expected), BOM-level roll-up, currency/FX handling, and row-count drift. The expert fix patterns from the feedback documents - the rules any fixed generator must encode:

> * MPN normalization: mpn_norm = UPPER(TRIM(strip non-alphanumerics)); join order (mpn_norm+mfr_norm) -> mpn_norm -> fuzzy-with-flag.  
> * buy_qty = MAX(MOQ, CEILING(required_qty / pack_size) \* pack_size); effective unit = lot_price / pack_size when quoted per pack.  
> * FX rate from the LOA/contract date, never "today"; no double conversion.  
> * rolled_qty(child) = product of all parent qty-per x top-level build qty; scrap = CEIL(rolled_qty x (1 + scrap%)).  
> * Ext = ROUND(qty_final x unit_price_foreign x FX x (1 + scrap%), 2); grand total = sum(lines) + NRE + freight + duty + packaging + testing.  
> * Award precedence: the QuoteWin-awarded supplier, never the cheapest or first match; check IF(ISBLANK(Award_UnitPrice), "NO_AWARD", "OK").

### **6.3 The gates to add while fixing (from RE 2, ordered by impact)**

> 1. **Export-time error sweep:** scan every cell for #REF!/#VALUE!/#N/A/#DIV/0!/#NAME?/#NUM!/#NULL! and fail the export. About 10 lines in openpyxl; would have caught both the 8,840-cell case and the 5677 Internal's 13 error cells.  
> 2. **Dead-report detection:** a tab with >90% placeholder content is fixed or stamped "NO DATA - reason" before shipping.  
> 3. **GO/NO-GO reconciliation panel:** aggregate the existing checks (Sum & Count flags, volume guards, validation counters, error-cell count) into one green/red health panel on the Introduction tab.  
> 4. **Unique-CPN enforcement at ingest:** scrub validation rejects duplicate CPNs per matrix scope; the matrix generator COUNTIFs the key column and refuses to build on duplicates.  
> 5. **Boolean type discipline at export** plus per-column type checks.  
> 6. **Manifest tab in every output:** generator + version, run id, timestamp, input file names + hashes, settings snapshot (currency rates, scrap table, batch quantities), per-tab row counts. Kills "which inputs made this file?" forever.  
> 7. **One naming convention:** \<Project\>\_\<Artifact\>\_\<Rev\>\_\<YYYYMMDD\>; CAM writes it, humans never rename.  
> 8. **Manual prices need provenance:** Priced By / Priced On / Source-ref columns on the Non-QuoteWin side.  
> 9. **Supplier master gains payment terms** (one source of truth) so Batchwise Cashflow stops shipping zeros.  
> 10. **Uncosted-parts KPI:** 546/1,474 uncosted lines in the sample run; track per run, distinguish No Bid from not-yet-quoted.  
> 11. **Revision-delta alarm:** flag any assembly whose cost moved more than a threshold (for example 15%) between revisions without a logged reason - the automated lesson of the +245% incident.  
> 12. **Golden-file regression testing:** the 22 project folders are a complete test corpus (known inputs, known shipped outputs). Every generator change re-runs all 22 and diffs cell-level; unexpected diffs block release.

## **7. The CAM 3.4 implementation plan**

Everything in this part is the plan - intended design, not built runtime. The order is deliberate: each phase de-risks the next.

\[Diagram D3 - the 3.4 migration plan: cam34_d3_migration.png in this Drive folder, updated 5 Nov 2026\]

### **7.1 Phase 0 - Pin the baseline**

Both repos are single squashed commits (CAM 0d54fd9, SRIM 5409180), so "what changed" cannot be computed from git today. That does not block this document: the verified live default-branch snapshot (read 5 Nov 2026) anchors the current baseline, and every 3.4 change is a diff from it. If the team shares the real history, tag the 3.3 commit for provenance; until then the 5 Nov snapshot is the reference point used throughout this document.

### **7.2 Phase 1 - Fix the 16 reports (in place)**

> * **Use the generator that actually produces today's workbooks. The measured version drift (Part 4.5) now has a source: the CAM repo's own reporting_module carries the guarded formulas that SRIM main lacks, and the four EXPERIMENTAL \*\_aclass modules live there too (found 5 Nov 2026 by direct read of solutionsDigibull/CAM). Still with the team: confirmation that this module is what production runs, and whether Harish shared any newer copy.**  
> * **Start from the written defects:** BOM_MATRIX_QTY_ROLLUP_BUG.md, then EXCEL_LOAD_PERFORMANCE.md, then the shipped-error evidence in Part 6.1.  
> * **Build the per-tab contract:** for each of the 16 tabs, a written spec of formulas, layout and expected values, plus one expected-output test against a designated production reference workbook (proposal: CBOM_Report_RFQ-000016; confirmation with the team). The existing validator.py and batch_validate_all_tests.py are the base.  
> * **Add the gates from Part 6.3** as pipeline stages, starting with the export-time error sweep and the GO/NO-GO panel.  
> * **Keep tool names and inputs unchanged** so routing and manifests stay valid through the fixes.

### **7.3 Phase 2 - Align the manifests with the code**

Ten manifests exist in CAM backend/docs: four intake (scrub BOM, quote win, ERP, costing sheet) and six reporting (cbom, enrich ERP, enrich costing sheet, resolve final selection, generate reports, export reports). They already use the BAM contract shape (skill_metadata, isatvon_definition, srim_runtime_definitionat version 1.4.0 (8 APPROVED, 2 APPROVED_INACTIVE), and their text APPROVED, and their text describes the current Dify flow - they were written after the code, to describe it. Three work items:

> 1. **Settle the count: code and files say six reporting tools with six manifests; a team note says "one manifest and one tool" for the 16 reports. Team decision (with the team; both positions now have an artifact - the six v1.4.0 reporting manifests in the CAM repo, and the one v0.1.0 DRAFT manifest covering all 16 reports in Harish's JSON Manifest folder).**  
> 2. **Compute the real governance hashes** (currently "TO_BE_COMPUTED_ON_SAVE").  
> 3. **Run the ten manifests through BAM's strict validator** (sbam_contracts/manifest.py). This is a document fix; no generation is involved.

### **7.4 Phase 3 - Replace Dify with Temporal, behind the same API**

Nagabhushana states Temporal is present (5 Nov 2026); what that covers in the running system - already orchestrating, partially wired, or available to use - is unresolved until his material or runtime access settles it, so this phase is written as the remaining work under either reading. In the inspected CAM source the orchestrator is still Dify (Part 2.1), whose whole job is three calls and a loop; the control logic mostly lives in CAM's FastAPI router. If replacement is still needed, the Temporal workflow mirrors it exactly:

> * One activity for GET /pipeline/routing-sequence.  
> * A loop of execute-tool activities with timeouts and retries, replacing the blocking 300 s call.  
> * A signal (or wait) for the human gate, resolve_final_selection.

Keep POST /tool/execute unchanged at first so tools and routing are untouched. Move hardcoded hosts (192.168.1.18, host.docker.internal) to configuration. Parallel-run both orchestrators on one test RFQ and compare skill index, status transitions and HITL behavior before retiring Dify. Then update the manifests' srim_runtime_definition (router "Dify_Dynamic_Master_Router") to the new value. Gateways are settled for 3.4 per Nagabhushana (5 Nov 2026): Jungle is kept, Bifrost belongs to the later track (the 1.5.0-DRAFT manifest that names Temporal + Bifrost is that generation). Note: BAM contains real Temporal code, but it is the build-time engine of a different system - a source of patterns, not the CAM replacement.

### **7.5 Phase 4 - Assistant chat pane (middle of the UI)**

Build after Phase 3. Per Nagabhushana (5 Nov 2026) the current middle pane is broken and is replaced by an Assistant UI for the LLM. Live check the same day: the pane renders and responds - generic prompts return a 'coming soon' stub, and the advertised FG query returned an answer (returned value, not independently validated). The backend already pushes progress events (notify_skill_progress), so the pane needs: a stable event and message API defined first, then the Assistant UI panel, then an explicit team decision on which tools it may call. The chat calls the same router as the workflow - no second execution path.

### **7.6 Phase 5 - JSON-editable execution and the Monaco edit loop**

Build on the settled manifests (Phase 2): the runtime importer/loader for manifests, the registry writer for system_skills_registry, and the edit loop behind a Monaco editor panel - validate edited JSON (schema, governance, computed hashes), rebuild or re-parameterize the affected tool through the BAM codegen modules once their stubs are replaced, and route execution through it. What exists and what is missing is measured in Part 1.2. Until the importer exists, the JSON files are documentation of intent, not inputs that drive runtime.

### **7.7 Phase 6 - Dynamic dependency propagation**

Implement after the team settles the semantics in Part 1.3. The proposal there (database as truth, regenerate affected sheets/workbooks, stream status and fresh artifacts over the existing server-side-event channel) reuses the progress push that already exists (notify_skill_progress) and the report builder fixed in Phase 1. Needs: an edit API for the pre-output fields the team marks editable, a dependency map from the formula families (Part 4.3) so affected sheets are known, and re-issue/versioning of delivered workbooks.

### **7.8 The separate 4.x track (boundary, for reference only)**

BAM's manifest-to-tool pipeline: build_manifest, render_skeleton (Jinja2, sandboxed, templates/fastmcp-loopy/1.0.0), generate_bodies (an LLM fills four slots: helpers, action_body, check_body, state_queries), AST pre-check, assemble (Black + ast + bundle_sha256 + deterministic tar), correct loop. Measured state: the real codegen modules exist, but the registered build workflow still calls stub stages, and no code anywhere loads a certified manifest into CAM's runtime registry (system_skills_registry is read by CAM but written by nothing inspected). The template produces one FastMCP server per Sub-Skill for the ISATVON do/check/hand-off loop - not a 16-sheet workbook assembler. 4.x's first pilot should be one small new skill, never the 16 reports. The BAM build pipeline itself stays on the 4.x track; 3.4 needs only the runtime-side pieces (importer, registry writer, edit loop) in Phase 5.

## **8. Sources**

> * Reverse Engineering folder (formula extraction, CAM Internal copies, internal-sheet extraction, analytics, running insights log): https://drive.google.com/drive/folders/11Vq5dvfDiYQk-O0BfDqkzvPeiXrf8Guh  
> * (1) CAM formula extraction (cell-level and authored-string CSVs): https://drive.google.com/drive/folders/1AlBpdgostkXm0ZQTP45gjaiFfWfNg6bF  
> * (4) Analytics (generation-logic overview + 16 per-report logic docs, crosswalk, function usage): https://drive.google.com/drive/folders/1iDzcDEfEaFaRowlzm3AtTydtcMUhBqCW  
> * INSTINCT BRAIN (Domain Knowledge: RE 1, RE 2, Domain 0-4, Encyclopedias E1-E4; Architecture and project archive: version map, project facts, decisions, existing diagrams): https://drive.google.com/drive/folders/1EXsYMNlqikC6wTUAQ4YCwtsIreucHlD3  
> * Research project home (START HERE, MAP, per-source archives 1-11): https://drive.google.com/drive/folders/1swkoE4E6RClGyCO-dLVuKsIjG6sY46D9  
> * Code: github.com/solutionsDigibull/CAM @0d54fd9; github.com/solutionsDigibull/BuLLMQuote_SRIM @5409180 (reports builders + Dify flow); github.com/solutionsDigibull BAM @9e6749d (codegen, ADR 0010, templates/fastmcp-loopy/1.0.0). Re-read 5 Nov 2026 from the live default branches: CAM backend/reporting_module/ (exporter.py, reports/\*.py including the 4 \*\_aclass variants, templates/excel_mappings.py, mcp_server.py) and SRIM mcp-tools/reporting/superset/reports/\*.py. ISATVON format: github.com/solutionsDigibull/ISATVON-prompting (public, v1.4). Harish's JSONs: Drive folder "JSON Manifest" (id 1d6_fIUU-HEPJ879v1zgxq-KPlOzh1YVU; original: harish.t, shared) - agent manifest + 10 skill manifests v1.5.0-draft + Centum 16-report manifest v0.1.0 DRAFT, read 5 Nov 2026.  
> * Runtime-shape claims: 27 Oct 2026 engineering session documents (archived in folder 7 of the research home).

## **9. Glossary**

| Term | Meaning |
| :---- | :---- |
| RFQ | Request for Quotation - the customer's pricing request that drives the whole pipeline |
| BOM / CBOM / SBOM | Bill of Materials / costed BOM (with prices and suppliers) / sales BOM |
| CPN | Centum Part Number - the internal part key every lookup matches on |
| MPN / MFG | Manufacturer Part Number / manufacturer |
| FG | Finished Good - the top-level assembly being quoted |
| MOQ / SPQ (pkg qty) | Minimum Order Quantity / Standard Package Quantity |
| NRE / FAI | Non-Recurring Engineering charge / First Article Inspection |
| EAU / Volume | Estimated Annual Usage; each volume tier gets its own CBOM VL and Ex Inv VL sheets |
| LOA | Letter of Award - the customer contract the quote feeds |
| Ex Inv | Excess Inventory report (excess, shortage, net buy) |
| A Class | The few parts carrying \~80% of spend (ABC classification) |
| TNP / CNP | Centum-controlled vs customer-nominated part sourcing splits used in Price Control (as recorded in the domain docs) |
| QuoteWin / SupplyWin / Drills | Legacy tools being replaced (quotes/awards, supply, BOM conversion) |
| Dify / DMR | Current external orchestrator / Dynamic Master Router workflow inside it |
| Temporal | The orchestrator 3.4 moves to (durable workflows: activities, signals, retries) |
| MCP Jungle / Bifrost | The two live tool gateways; FastMCP = the Python tool-server framework |
| HITL | Human-in-the-loop gate (resolve_final_selection) |
| ISATVON / BAM / SRIM | The manifest schema (I,S,A,T,V,O,N) / Build Acceleration Manager / Skills Runtime Implementation - the 4.0 generation's pieces |

## **Change log**

> * 5 Nov 2026 - first issue. Diagrams: cam34_d1_runtime.png, cam34_d2_formulas.png, cam34_d3_migration.png, cam34_d4_domain.png (same folder). Six questions sent to the owner (newer generator location, tool/manifest count, reference workbook, baseline commit, registry writer, gateway scope under Temporal); the doc will be updated as answers land. 5 Nov 2026, later - direct reads of the live CAM repo (GitHub default branch) found the four \*\_aclass modules in CAM backend/reporting_module/reports/ (marked EXPERIMENTAL) and the blank-scrap guard in CAM's ex_inv_vl.py lines 182/185, which largely answers the newer-generator question from source; confirmation that this module is what production runs stays with the team. 5 Nov 2026, later still - full CAM-vs-SRIM package comparison done: CAM's reporting_module is the newer evolution (13 of 16 shared report modules differ; CAM 195 formula-string sites / 169 distinct vs SRIM 171 / 156 under one tokenizer count); the row-7 SUM citation was corrected to both repos; the two RFQ-000016 workbook copies were hash-compared (sha256 3d0491af3b73905d9776a2e68a9bd1ace0299a116676a539cb82e8376c4c3d41, byte-identical). The intro's 3.4-absence wording was bounded to the inspected sources. 5 Nov 2026, latest - auth-surface read on the live CAM frontend: the daemon's dev/test login bypass is frontend/apps/daemon/src/test-login.ts (fixed default credentials, overridable via environment variables, auto-disabled in production builds); LoginPage.tsx and the daemon auth modules carry no hardcoded password or JWT secret, so the credential-hygiene paragraph was re-scoped to what the live read confirms. 5 Nov 2026, 1:33 PM IST - scope correction applied from Nagabhushana's 5 Nov definition: Part 1 rewritten (3.3 = the built CAM repo baseline; 3.4 = the urgent Centum increment - JSON-editable execution via Harish's ISATVON JSONs + Jinja2 + AST with a Monaco editor, dynamic dependency propagation across sheets/workbooks before and after output, left workflow accordions / Assistant UI middle / server-side events + output right, Temporal present with Jungle kept for 3.4, 3.3 bugs to fix with annotated screenshot evidence). New Parts 1.1-1.4 (the JSON layer measured from the 12 files in the JSON Manifest folder; the JSON-to-tool gap analysis; the propagation semantics decisions; UI + bug-evidence plan). Phases 5 (importer + Monaco edit loop) and 6 (dependency propagation) added to the plan; the 4.x boundary moved to 7.8. Harish's JSONs are treated as design inputs, not implemented runtime. The hands-on app check is blocked: the deployment's NetBird mesh IP is unreachable from this environment (direct and cloud-browser timeouts, 5 Nov); a private access route was requested via main. 5 Nov 2026, 1:38 PM IST - deepening revision: grounded the edit/propagation baseline in source (duck_db_api.py batch-update over nine final\_\* fields plus recompute_derived_columns; downloads serve the pre-edit workbook until export_reports re-runs; hitl_router.py selection edits; RFQ versioning already exists), recorded that the frontend carries AG Grid but no Monaco/CodeMirror/Ace and no accordion component, bounded Phase 0 (the live 5 Nov snapshot anchors the baseline; git history is not a blocker), bounded Phase 3 (his "Temporal is there" does not establish the replacement is still future; runtime state to confirm), re-affirmed the propagation design as a proposal and not his choice, and added the annotated UI zone map (cam34_user_ui_annotated_5Nov2026.png, private). D3 updated (Temporal state-to-confirm label).5 Nov 2026, 1:41 PM IST - Visual corrections from review: D3 Phase 0 box now anchors the baseline on the verified 5 Nov 2026 live snapshot (full git history helps provenance but is not a blocker) and Phase 6 carries the grounded batch-update edit baseline (9 final\_\* fields, one-table derived-column recompute). Annotated UI photo: right-zone box extended to the actual pane edge; 'broken' attributed to NRS's report, not reproduction. Both images updated in place in the Drive folder (same file ids); owner-only permissions re-verified.  
> * 5 Nov 2026, 1:44 PM IST - Part 1.4 gained the code-level pane map: left = WORKFLOW_STAGES 9-stage cards in App.tsx (3 stages comingSoon placeholders), right = RfqProgressLog skill rows (\[DONE\]/\[FAILED\]/\[RUNNING\], seeded from rfq.getSkillHistory + live rfq:skill-progress SSE) with the Export All Reports button at the quoteReadiness stage downloading the pre-generated workbook; SSE channel, macro_category-to-stage mapping, resume-via-/api/dify/start behavior documented; Part 2 source note updated (pane components now located).  
> * 5 Nov 2026, 1:46 PM IST - Part 1.4 SSE path now grounded end to end: fastapi_router.py notify_skill_progress POSTs to the daemon's POST /api/internal/emit-skill-progress (hardcoded 192.168.1.18:9234); daemon browser-api-server.ts broadcasts raw rfq:skill-progress frames per-RFQ via sendToRfq; frontend root EventSource on GET /events?rfqId= receives them. Two fixed historical regressions on this path noted from daemon comments (named-channel delivery reaching nobody; /events 404 on token query).  
* 5 Nov 2026, 4:58 PM IST - NetBird app access established: task peer instinct-cam34-doc enrolled in the solutions mesh via device sign-in with the vault-saved solutions@digibull.ai credential (the earlier blockage cleared when the credential save completed at 4:30 PM). Read-only hands-on verification performed 4:33-4:58 PM IST; Part 1.4 access wording and 1.4.1 rewritten to the verified results. Export All Reports verified working (window.open to the :3010 export endpoint, valid 256 KB xlsx); the transient analytics-pane attribution was retracted after click instrumentation. NRS's 4:57 PM pane clarification folded in as 1.4.2 (agent > skill > subskill design mapping). Doc stays a private working draft pending his promised 3.4 material.

