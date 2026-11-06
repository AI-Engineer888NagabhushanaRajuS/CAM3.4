**CAM / Centum architecture companion** 

Snapshot: 28 Oct 2026. Source was read, not executed. Tests were not run and no  deployment was inspected. Nothing here is operational proof. 

Tags: \[S\] in code or a raw document I read; \[S-stub\] registered stub that returns a synthetic  result; \[R\] reported by a person or document, not seen; \[T\] drafted target; \[P\] proposal;  \[OPEN\] unresolved. "Not found" means only in the sources named. 

Each generation stays separate: 3.2/3.3 (runs today, reported), BAM build platform (under  development), CAM 4.0 target (draft). 

**1. Sources (exact)** 

• BAM dev at commit 9e6749d5b61f1c58d4ff53d8015d5160167e2331 (public repo  solutionsDigibull/BAM). Source-backed file links at that commit: 

manifest stage  

https://github.com/solutionsDigibull/BAM/blob/9e6749d5b61f1c58d4ff53d8015d5 160167e2331/server/workers/sbam_workers/build/manifest.py 

build pipeline    
https://github.com/solutionsDigibull/BAM/blob/9e6749d5b61f1c58d4ff53d8015d5 160167e2331/server/workers/sbam_workers/pipeline/sub_skill_build.py manifest design  

https://github.com/solutionsDigibull/BAM/blob/9e6749d5b61f1c58d4ff53d8015d5 160167e2331/docs/design/11-manifest-design.md 

• Private repos read as redacted mirrors: CAM    
0d54fd90f98001b559bf8ace81282342876b352f, BuLLMQuote_SRIM 5409180 (no  public links). 

• Meetings (tl;dv transcripts, read raw from the archive): 3 Sep 2026 standup; 7 Sep  2026 API Discussion; 21 Oct 2026 meeting. 

• Docs (Drive, read raw; open with the nagabhushana.raju.s@digibull.ai account): API Master v0.3, 26 Oct  

https://docs.google.com/document/d/15I_GbEeOo5ewmPHRsmwbB5z2BA1m IfiwYB5W_p34uQ/edit?usp=drivesdk&authuser=nagabhushana.raju.s%40digibull.ai API Governance v0.2, 7 Oct  

https://docs.google.com/document/d/1S88K2tmm_YvALGW_LkVaXirRBOFihK6qwc3 eqwyKA88/edit?usp=drivesdk&authuser=nagabhushana.raju.s%40digibull.ai Skills master, 17/19 Oct  

https://docs.google.com/document/d/1dtHGCBsSeqdvkBffwIEnkR48XT3f yQYmYLwENG9mzY/edit?usp=drivesdk&authuser=nagabhushana.raju.s %40digibull.ai 

CAM Reports doc, 16 Oct, edited 28 Oct    
https://docs.google.com/document/d/18h1_NCA2xxk5VfwviqyJfMVLAsXy a6clFcEBmuzGIo/edit?usp=drivesdk&authuser=nagabhushana.raju.s%40digibull.ai ISATVON 1.5 draft   
https://docs.google.com/document/d/1OmpUUBXCYQfUuiQ5RIAMOWxzz4SQH5Gdb E82GYDjJuk/edit?usp=drivesdk&authuser=nagabhushana.raju.s%40digibull.ai API Proposal for Centum (draft)  

https://docs.google.com/document/d/1iAqC13ln2H0dralWmctm0Ksthb8SiGnWPLaV rQOPJvM/edit?usp=drivesdk&authuser=nagabhushana.raju.s%40digibull.ai ; the final  proposal sent to Centum on 23 Oct was not accessible from the connected accounts, so  it was not read. 

LATEST UPDATES folder    
https://drive.google.com/drive/folders/1k9ZtcjIHKGCET4wCGAOCcW-d9f4XteGm? authuser=nagabhushana.raju.s%40digibull.ai (agent_manifest.json, skill_01..10 JSON,  cam_isatvon_manifest.json). 

**2. What changed (why there are "many updates")** 

1\. Sep 3 decision \[S, raw transcript\]: Dify is replaced for orchestration by Temporal;  LiteLLM is dropped (supply-chain concern) and Bifrost takes the model-routing, API routing and key-management role; MCP Jungle (the MCP tool gateway) is explicitly  held "for now", with an alternative to be considered later. 

2\. The ISATVON 1.5 draft says Bifrost replaces MCP Jungle \[T\]. That is a different claim  from the 3 Sep decision. LiteLLM-to-Bifrost (model router) and Jungle (tool gateway)  are different layers. Whether Bifrost also replaces the tool gateway is \[OPEN\]. The 27  Oct agent manifest has a field "gateway: Bifrost_Gateway" without saying which. 

3\. Across the LATEST UPDATES folder and the latest BAM source there are three  generations: the 16 Oct report manifest (old runtime), the 27 Oct agent manifest 1.5.0- draft (Temporal, Bifrost), and BAM's manifest stage, which hardcodes the old runtime  in source. Folder membership and modified dates do not show approval or  deployment. 

4\. BAM is an existing, larger build-time platform; on 28 Oct it gained a real manifest stage (section 4), its newest addition. 

5\. 17 Oct: scope fitted to 10 skills x 4 sub-skills \[P\]; API became its own track; 26 Oct: a  draft API contract in the API Master (section 6). 

6\. Owner statement (28 Oct): all architectures are under development; Accomplish is  removed. 

**3. Generation A: 3.2 / 3.3 runtime (as inspected)** 

\[S in the CAM and SRIM repos read; deployed state \[R\]. The owner says the live backend  runs from disk outside git, so deployed behavior may differ; do not assume every 3.2/3.3  deployment matches these repos.\] 

Flow: upload_server /api/dify/start/{rfq_id} -> Dify master router -> routing-sequence  HTTP node (profile RFQ_Flow) -> slice by skill_index -> per tool POST /tool/execute  {tool_name, arguments{rfq_id}} -> gate (union membership; fails open on lookup error) ->  MCP Jungle -> FastMCP tool -> Postgres / DuckDB. Result {status, hitl}; hitl or failed holds  the index; unknown tool returns 200 {"skipped": true, "hitl": 0} and advances.  
HITL: router sets hitl -> Dify calls trigger-hitl then raises, ending the run; a person resolves  in the UI; resume is a fresh Dify run from the current skill_index. Disabling a tool in  routing_sequence is not a safe rollback; use pinned versions and a drain policy \[P\]. State: quote_routing_profiles.routing_sequence (jsonb) and system_skills_registry rows. A  writer of those rows was not found in the inspected sources. 

Reports: 16 reports = 16 CBOM tabs (Laravel ProcessTab1..16Job in the CAM repo), with  live Excel formulas (generated workbook about 58,651 formulas; reference about 99,019,  89% cached; CAM backend/Test_fixes/EXCEL_LOAD_PERFORMANCE.md). Per-tab logic is  not implemented in the 16 Oct reports doc; production scripts pending GitHub access. 

**4. Generation B: BAM build platform (28 Oct, 9e6749d) \[S\]** 

Three different "registry" ideas must stay apart:   
(a) Workflow registration: the Temporal registry workflow_for maps names to workflows;  it is not a skill store. 

(b) Dependency library registry: a registry of Python package dependencies used by  check_libraries. 

(c) Runtime skill registry: the runtime's system_skills_registry/routing rows in SRIM. No  BAM-to-runtime writer for (c) was found. 

Layers: Next.js FDE client; FastAPI routers (ingest, scan with ClamAV, sow, knowledge,  masters, isatvon, workflows, builds, manifests, pipeline, audit); Postgres with  tenant/project columns per design docs (enforcement not verified); Temporal workflows  ProjectPipeline, SubSkillBuild, IsatvonRegenerate, SowRegenerate, DocumentIngestion,  KnowledgeRebuild; Bifrost aliases to OpenRouter for LLM calls; Cognee 1.6.2 library with  OKF (hash-verified, write-once); Langfuse. 

Pipeline order: ingest \[stub in pipeline; a separate real DocumentIngestion workflow exists, link to the pipeline stage not established\] -> knowledge -> okf -> sow -> wait approve ->  create workflow -> extract macros/sub-skills -> wait generate -> SubSkillBuild children (4  at a time) -> certify and freeze \[stubs\]. 

SubSkillBuild: build_manifest \[REAL: 409 lines, PR #101, migration 0033,  sub_skill_manifests, stage-key idempotent\] -> check_libraries, render_skeleton,  generate_bodies, assemble, ast_gate, static_gate, generate_tests, sandbox/promptfoo,  certify \[all stubs\]. Real classes Assemble, GenerateBodies, Correct exist; non-test call sites  not found. 

build_manifest hardcodes PLATFORM_SRIM (Dify_Dynamic_Master_Router,  MCP_Jungle_Gateway_Reverse_Proxy, SRIM_UI_Canvas; lines 86-98); design doc 11 says  per-tenant configuration is pending. So BAM's newest manifests name the 3.2-era runtime. The manifest is the OUTPUT of a validated Sub-Skill, then the INPUT to codegen. A JSON  manifest alone does not make a tool: codegen, gates, tests, certification, packaging,  deployment to a FastMCP server, gateway registration and a registry/routing row come  after, and within the registered SubSkillBuild path only manifest creation is a real stage  (the project-level pipeline has its own real and stub stages, listed above). Handover to SRIM is future scope \[design\].  
**5. Generation C: CAM 4.0 target \[T\]** 

Temporal workflow (replaces Dify), Bifrost (model routing; tool gateway \[OPEN\]), FastMCP tools, Pydantic AI contracts, PostgreSQL + DuckDB, BullMind/OpenPyXL/Superset  reporting, PostHog audit, Refine.dev/AG Grid UI, REPEL policy gate (planned; expansion  differs between docs: "Rule-based" in v0.3, "Runtime" in v0.2). 

Caveats for the 27 Oct agent manifest 1.5.0-draft: status DRAFT; governance hash is the  placeholder "sha256:COMPUTED_ON_SAVE"; 10 skills / 40 sub-skills; skills 2, 6, 10 are  tagged "not required for CAM" in the 17 Oct doc (skill 6 scope open). 

Caveat for the report manifest (cam_isatvon_manifest.json, v0.1.0, 16 Oct, DRAFT): its  governance says not to approve until unconfirmed and conflicting v_variables are resolved  (25 of 33 edge-case variables unconfirmed per the skills doc). Its runtime block names Dify  and MCP Jungle, and an a_automation field "BuLLM_DMR". 

**6. Draft API contract; implementation and deployment not verified** 

Source: API Master v0.3 (26 Oct) and Governance v0.2 (7 Oct). Both label it a proposal: the  evidence they cite supplied no live endpoint, passing test or tracker entry. I did not test or  find an implementation. The final CAM 4.0 API proposal was sent to Centum on 23 Oct and  awaits their go-ahead; CAM 3.3 continues meanwhile. 

Request modes \[S, doc\]: push, pull, polling, email (confirmed 26 Oct); conversation (voice,  WhatsApp, Teams, email bot) is a front door to the same workflows. 

Operations in the draft OpenAPI 3.1 appendix \[S, doc\]: seven REST operations:  createIngestion POST /v1/ingestions; getBom GET /v1/boms/{bomId}; createReport POST /v1/reports; getReport GET /v1/reports/{reportId}; downloadReport GET  /v1/reports/{reportId}/output; getWorkflow GET /v1/workflows/{workflowId};  acceptIngestionEvent POST /v1/ingestion-events. Plus one webhook specification,  receiveWorkflowCompletion, a receiver contract on the client side (headers X-BuLLM Timestamp and X-BuLLM-Signature; responses 204, 400, 401, 503). POST /v1/rfq-intakes  for raw files is a proposed extension in the text, not in the appendix paths. Payloads in the draft schema \[S, doc\]: 

• createIngestion body BomInput: projectId, revision, currency (3 capitals), items (1 to  50,000) of {itemId, partNumber, quantity, unit, optional description, optional  unitCost}. Required header Idempotency-Key (1 to 128 characters). Bearer JWT  security (proposed OAuth2 client-credentials; issuer and audience not approved). 

• createReport body ReportRequest: bomId, reportType (engineering, sow_quote,  bom_payload), format (xlsx or json), templateId (required for xlsx), optional  callbackId. These three report types do not map to the 16 CBOM tabs; the mapping is  \[OPEN\]. 

• 202 response Accepted: workflowId, state "queued", statusUrl, optional reportId,  execution {capabilityId, skillVersion, configVersion, policyDecisionId}; headers  Location and Retry-After.  
• Workflow states in the schema: queued, running, succeeded, failed, cancelled; fields  queuedAt, startedAt, completedAt, resultId, failure. 

• Errors: application/problem+json for 400, 401, 403 (code approval_required when  policy needs approval; nothing enqueued), 404, 409, 413, 415, 422, 429 (rate  headers), 503. 

Draft rules in prose \[S, doc, all proposed\]: tenant comes from the server-side authenticated  binding and never from a caller header; same Idempotency-Key and body returns the  original ids, a changed body returns 409; proposed seven-day key retention; proposed caps 10 MiB and 50,000 items; success requires a persisted artifact with checksum plus  independent acceptance; the doc proposes adding a clarification/review state; a mock  fixture adapter stands in until a real BAM skill exists. 

My added design advice, not source schema \[P\]: a unique key plus a transactional dedup  record in the implementation (the draft's key rule does not say how); a checksum proves  integrity, not authenticity; my plain-words summary of the request fields (workspace,  version, reply path) maps to the draft's tenant binding, execution binding and callbackId. 

**7. Reports: single tool is feasible; the gap is the contract** 

One FastMCP tool can generate all 16 tabs (the report manifest and Skill 9 both describe  this). What is missing in the sources is a per-tab contract: formula transcription, layout,  schema, and tests/acceptance for 16 tabs with live formulas (the reference workbook has  about 99K). Treat the "one manifest, one tool" design as a stop-gap that needs those per-tab specifications, not as insufficient because of tool count. 

**How the report JSON is meant to become a deployed tool, and where it stops** 

Intended path (16 Oct report manifest and Skill 9 \[S, doc\]): one manifest (16 report  definitions with variables and acceptance checks) -> Jinja2 template -> AST check ->  FastMCP builds one tool (Skill 9 names it OpenPyXL_Superset_BullMind_MCP) ->  orchestration (Temporal for Skill 9; Dify DMR in the 16 Oct manifest) -> tool run writes the  workbook -> acceptance (Skill 9: 16 reports render without errors and Superset  registration returns 200) -> hook to Skill 10. 

What exists in source today \[S\]: BAM build_manifest (real) and the fastmcp-loopy/1.0.0  template reference. Stubs or no call site in BAM's registered build path: generate_bodies,  assemble, ast_gate, static_gate, generate_tests, sandbox and certify. Not found in inspected  sources: a package/importer that deploys generated source to a FastMCP server, gateway  registration, and a registry/routing row writer. The report manifest stays DRAFT  (unresolved variables, placeholder hash) and its runtime block names the old generation. I  did not write a runnable sample because compiler order and variable bindings are  unverified. 

**8. Keep / replace / connect - proposed rebuild plan** 

Keep: Postgres and DuckDB; FastMCP tools; BAM's manifest hashing and stage  idempotency; Temporal/Bifrost in BAM; report scripts as the formula reference.  
Replace (target): Dify master router with Temporal and LiteLLM with Bifrost (3 Sep  decision); Accomplish UI with Refine.dev/AG Grid remains a target \[T\]. The role of MCP  Jungle is unresolved: 3 Sep keeps it for now, the 1.5 draft says Bifrost replaces it; it requires a confirmed target role before implementation. 

Connect (missing links): BAM output to a runtime importer and registry writer;  PLATFORM_SRIM per-tenant so manifests name the real runtime; API operations to real  backend operations (open items for Akshay in the API docs); report manifest into BAM  once its variables are resolved. 

**9. Open conflicts** 

Jungle kept (3 Sep) vs replaced (1.5 draft); timeline 2 / 3 / 4 weeks (deck, 7 Sep, proposal);  REPEL expansion; ISATVON 1.4 / 1.4.2 / 1.5 and 4.0 / 4.1 / 4.2 numbering; identity Cognito / Keycloak / EntraID; approval of the 7 Sep proposal is reported, not read; hardcoded  PLATFORM_SRIM vs 27 Oct agent manifest. 

Not inspected: other late meetings, ClickUp, Claude/ChatGPT/Gemini histories, a line-by line diff of the 1.5 draft vs the JSON files.