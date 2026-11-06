# **BuLLM API Master Doc** 

## ***Version 0.3 \| 26 October 2026 \| Private working document*** 

One living master for the BuLLM API: how client systems talk to BuLLM, the contract we are building to, the first client proposal, and what is proposal versus real. In the evidence checked for this revision (mail threads, design docs and meeting write-ups), no live endpoint, passing test log or task-tracker entry was supplied. Anything marked proposed still needs build and evidence.

# **The short version** 

* **What the API is.** The BuLLM API lets a client's own software talk to BuLLM directly, with no login screen. Same workflows, same permissions, same results as the login and chat routes.  
* **Four ways in.** Requests reach the API four ways: push, pull, polling, and email - Srinath confirmed this list on 26 October. The deep section below explains each mode, its stack pieces, risks and effort.  
* **The working standard.** The ten-point checklist Srinath emailed Akshay on 18 September. Item 10 is Reports and Analytics, not licensing or monetization.  
* **First client.** The CAM 4.0 API proposal went to Centum on 23 October. We are waiting on Centum's go-ahead.  
* **The contract.** Proposed OpenAPI 3.1 with eight operations, asynchronous jobs, and policy checks before work starts. The full draft is in the appendix.  
* **One master.** The v0.2 review notes and the 10 October RFQ API master are folded in fully. The originals stay in Drive untouched as archival references. The change log says what moved and why.

# **What changed in v0.3, and why** 

* Srinath's instruction on 26 October: the doc felt like cut-and-paste and was missing things. Bundle the Akshay checklist email, the Centum proposal, the internal docs and the Gemini design sessions, and go deeper on the four API modes.  
* **Folded in:** the 18 September checklist email; the CAM 4.0 API proposal sent to Centum on 23 October; the 30 September workflow-team access doc (three access modes, four request routes); the 10 October RFQ intake doc (channel mechanics and effort); the 10 October RFQ API master (in full - see the next bullet); the Gemini architecture session on ingestion channels.  
* **Folded in fully:** the 10 October RFQ Automation API - Master Document now lives here end to end - business boundary, fast-build gates, acceptance evidence, test-lane detail, egress and codegen notes, decisions list and source ledger. The original stays in Drive untouched as an archival reference; nothing was deleted or moved.  
* **Fixed:** REPEL now reads Rule-based Enterprise Policy Enforcement Lock, the owner's 10 October decision. The Runtime expansion used in v0.2 was a superseded choice.  
* **Confirmed:** on 26 October Srinath confirmed the four API request modes are push, pull, polling and email; the 'phone on demand' item from his 29 September note is dropped at his direction.  
* **Condensed:** the pasted 7 October plan and review notes are now summaries with the substance kept. Originals remain in the linked sources and in this doc's version history.  
* **Kept unchanged:** the OpenAPI 3.1 review draft (appendix) and the references section after it.

# **How clients reach BuLLM: login, API, conversation** 

From the 30 September workflow doc. Three ways in, same product behind all three: same workflows, same permissions, same results.

* **Login.** The user opens BuLLM and logs in. FDEs build and set up workflows; client teams run them and pull reports.  
* **API.** The client's own software talks to BuLLM directly. Example: their system sends a BOM, BuLLM returns a job ID, they use that ID to get the result. Requests arrive four ways - push, pull, polling, or email - detailed in the next section.  
* **Conversation.** The user asks in plain words: a voice note, WhatsApp, Teams, or an email bot. Speech is transcribed and checked before it becomes a job. A conversation request runs the same approved workflows; it is a front door, not a separate engine.

# **The four ways API requests arrive** 

Plain definitions from the 30 September doc. Push: one system sends data or an event to another. Pull: one system asks another for data. Polling: repeating pull requests on a schedule to check whether something changed. Email: a transport - a receiver turns a message and its attachment into a workflow request. A webhook is a message sent to a web address when an event happens.

Rule of thumb from the 29 September discussion: push for triggers, pull on demand for data, polling as the fallback when a client cannot push, email as the universal lowest-friction path.

Figures in this section - latency, client IT effort and build days - come from the 30 September write-up, the 10 October intake doc and the Gemini design sessions. They are planning estimates and design assumptions, not measurements. The build-day figures assume a first tested route with codegen and an existing shared core; they exclude client approvals, licensing, procurement, security review and production rollout; they overlap and must not be added together. Verify each against the real deployment.

Choosing a route (from the 10 October master): thin authenticated REST push when the source application can call it; source cloud notifications when files already land in an approved S3 or SharePoint location; email fallback only within the security and file-size policy; browser upload for manual large-file exceptions; the on-prem watcher for local restricted exports; scheduled batch pull where only batch read access exists. These are independent transport choices into the same pipeline.

## **1. Push: the client's system or cloud tells us something happened** 

* **How it works.** The client drops a file in their own cloud (SharePoint, OneDrive, or S3), or their application calls our thin REST intake endpoint directly. Their system sends a lightweight event with a file reference to the Bifrost/FastMCP gateway. A worker then fetches the actual file with scoped, read-only keys and starts the workflow.  
* **Data loss: designed controls, unverified.** The design relies on provider event retries and dead-letter queues (DLQs) when our side is down, but DLQ behavior differs per provider and Microsoft Graph has no generic DLQ, so the design adds our own durable queue, subscription renewal and missed-change reconciliation. Failure mode to test: events lost when our receiver is down past the provider's retry window.  
* **Privacy: design assumption, unreviewed.** Client IT grants service-account permissions (OAuth scopes) to read specific SharePoint or S3 locations; real exposure depends on the scopes a client actually grants.  
* **Speed and effort: design estimates.** Intended as instant and event-driven. Client IT effort estimated medium (configure the webhook or Graph subscription). Build estimate: 3-4 days for the event route, 4-6 days with queue, DLQ and replay handling; the thin REST receiver alone is 3-5 days. Estimates, not commitments.  
* **Watch out.** Events can arrive twice or out of order. Deduplicate on stable RFQ/event/version keys; a retry must never create a second job. Do not assume a product named Bifrost natively accepts arbitrary cloud events; verify the route in the real deployment.

## **2. Pull: we ask the client's system for data when a job needs it** 

* **How it works.** Mid-job, BuLLM calls the client's API for exactly the data it needs. Example: component risk, lifecycle and pricing data from the client's Accuris subscription, which offers a real REST Parts API.  
* **Best when** the client exposes an API and we need fresh data at the moment of work. Nothing sits waiting outside their walls.  
* **Where there is no API:** QuoteWin is closed, with no public API and only five licenses; Drills is a legacy login-only app with unlimited logins. Integration platforms (Nango, Pipedream, Composio) wrap existing APIs; they cannot create one. Options, in order: a vendor or client-approved export or read-only database view; controlled browser automation with session pooling, off-hours runs and a human recovery path, with the client's explicit sign-off; or a human runs that step and drops the output where BuLLM picks it up.  
* **Effort** depends on the client's API. Confirm Accuris entitlements, auth, rates and sample responses before promising integration.

## **3. Polling: we check on a schedule** 

* **How it works.** A Temporal Schedule starts a pull workflow at agreed intervals (for example every 30 minutes, or nightly at 2 AM). A FastMCP worker uses read-only credentials to list the client's SFTP, S3 or SharePoint location, detects new or unprocessed files, downloads them, and passes them to Cognee for parsing. Checkpoints and file hashes make restarts and catch-up safe.  
* **Data loss: designed controls, unverified.** The design relies on Temporal's durable state to track batch markers and retry crashed jobs without skipping files, plus a complete-file convention (a manifest or atomic rename) so half-written batches are never read. Verify restart and catch-up behavior in a real run.  
* **Privacy: design assumption.** Client IT provides restricted, read-only credentials and no inbound ports need to open on the client network; real exposure depends on the credential scope granted.  
* **Speed and effort: design estimates.** Scheduled, not real-time; files wait for the next run. Client IT effort estimated low. Build estimate: 2-4 days when the Temporal/FastMCP base exists. Estimate, not a commitment.  
* **Best when** client IT prefers passive read access over webhooks or local scripts.

## **4. Email: the client's team mails a dedicated address** 

* **How it works.** Assign one address per engagement (for example ingest-acme@platform.bullm.ai). An inbound mail provider receives the mail and posts an authenticated HTTPS webhook to our intake adapter. The adapter validates the provider signature, stores the original message and attachments, records durable receipt, and only then queues parsing through the FastMCP boundary. An email webhook is not automatically an MCP call; the adapter translates it.  
* **Data loss: the weak mode by design.** Mail size caps (plan around 25 MB; verify the actual provider's limits) can reject or drop oversized attachments without a clear signal, and spam filtering can fail delivery silently. Controls: durable receipt before parsing; oversized files move through browser upload or cloud push with a reference in the email.  
* **Privacy: high concern.** Email is not end-to-end encrypted by default; sensitive files pass through mail servers. Use it only where the client permits it.  
* **Speed and effort: design estimates, unverified.** The intended design queues parsing roughly 30 seconds after send; verify against the real provider. Client IT effort near zero; people use the email workflow they already have. Build estimate: 3-5 days plus parser upkeep. Estimate, not a commitment.  
* **Watch out.** Keep sender, subject, thread and attachments together; a reply or forward is not a new RFQ; the same email arriving twice must not run a second job.

## **Two related intake paths that are not API calls** 

* **Browser upload (manual).** A signed-in user uploads through a Refine.dev screen; Uppy sends the file with the tus protocol to a tusd server, resuming interrupted uploads from the exact byte. A completion hook creates the intake record only after the full file is stored and checked. Build estimate: 3-5 days if the UI, auth and storage exist. This is the large-file exception path; it still needs a person and a login.  
* **On-prem folder watcher.** A small Python watchdog service runs inside the client's firewall and watches a shared folder. The producing app writes a temporary file and atomically renames it when complete; the watcher processes only completed files, with a startup recovery scan for missed events. Build estimate: 2-4 days, plus an approved transfer route if processing happens outside the boundary. A true air gap has no cloud route; do not quietly forward its documents to a hosted service.

## **Rules every mode follows** 

* Store the complete file first; acknowledge only durable receipt. Receipt is not successful extraction.  
* Deduplicate by client, RFQ or job, version, and file hash. Validate type and size; virus-scan (ClamAV is the planned gate) and quarantine failures.  
* Keep original files with source IDs and checksums in access-controlled storage, and keep an audit trail from request to result.  
* REPEL (Rule-based Enterprise Policy Enforcement Lock) is the planned policy gate, not yet evidenced in a running system: before work runs it must check actor, tenant, role, resource and action - allow, require approval, mask, or deny, with a logged decision.  
* Credentials live in the approved secret store; never in prompts, chat, logs, or this document.  
* Treat file contents and email text as untrusted data, never as instructions.

## **What every API request must carry** 

* Client or workspace ID: whose data and rules apply. It comes from the authenticated context, never a caller-chosen header.  
* Workflow ID and approved version: which job should run.  
* Inputs: the file or reference, quantities, currency, and other required facts.  
* Request ID and a duplicate key: so a retry returns the same job instead of creating a second one.  
* Reply path: where status and result go.

## **After the job: status and delivery** 

* Long jobs return a job ID with 202 Accepted and a status URL. 202 means durably accepted, not finished.  
* The client's system polls the status URL or receives a signed webhook callback; the agreed contract decides which. Callback delivery is separate from job success.  
* Results go only to permitted people: an authenticated download link, not confidential content pushed into a group channel.

# **The ten-point API checklist** 

Srinath's 18 September email to Akshay (cc Sriniketh); the working standard for the API build. Item 10 changed on Srinath's instruction (restated 27 September): it is now Reports and Analytics. The old item 10, licensing and monetization, is out. Why switched: reporting is the client-facing deliverable; monetization is out of scope, and rate limits stay purely operational protection.

* **1. API specification standard and source of truth.** OpenAPI 3.1 as the contract before code (design-first), with schema linting (for example Spectral) for consistent naming and structure.  
* **2. Endpoints and resource naming.** Resource-oriented URIs (POST /v1/workflows, GET /v1/workflows/{id}/status) and standard verbs and status codes (200, 201, 202 for async, 400, 422).  
* **3. Data ingestion and input pipeline.** Payload limits (for example 10 MB JSON), accepted content types, and tracked intake triggers: direct upload, presigned URLs, or webhooks.  
* **4. Response contracts and output.** Strict typed responses (Pydantic AI or Zod) and a global error envelope. The requested envelope is RFC 7807 Problem Details; RFC 9457 now supersedes 7807, so pick the current standard at review without silently changing the requested shape.  
* **5. SDK and tooling generation.** Choose the generator (Speakeasy, Fern, or FastMCP-native) and auto-build and publish SDKs from openapi.json in CI. MCP is optional and separately approved.  
* **6. Authentication, authorization and security.** One auth scheme across endpoints (Bearer keys, OAuth2 or JWT) with role-based scopes (for example read:workflows versus admin:deploy).  
* **7. Automated testing and validation.** Contract tests (Schemathesis or Dredd) proving the running service matches the spec, plus mock servers (Prism) so client and frontend work can start early. Mocks do not prove the backend.  
* **8. Rate limits, throttling and usage management.** Clear limits (for example 60 requests per minute per key) with standard X-RateLimit headers and 429 + Retry-After. Operational protection only; no monetization tiers.  
* **9. Versioning and backward compatibility.** Explicit versions (/v1/ prefix or headers) and a proposed 90-day deprecation notice with Sunset headers. Sample dates are not real deadlines.  
* **10. Reports and Analytics.** Automated report generation with openpyxl, xlsxtpl (Jinja2 inside client Excel templates) and XlsxWriter; HubDB for private tabular report hubs; Apache Superset for BI dashboards; DuckDB for in-memory transforms of normalized BOM JSON. Engineering reports, SOW quotes and BOM payloads are delivered through API endpoints.

# **First client: the Centum CAM 4.0 API proposal** 

Status: sent by Sriniketh on 23 October 2026 with an explainer video; waiting on Centum's go-ahead. Until the API is ready, CAM 3.3 continues with fixes and better validation. Proposal doc: [https://docs.google.com/document/d/1-FU776fV2qtg1jgcZ6mn-3ttCMAoUXv-d6FYAc_KzzY/edit](https://docs.google.com/document/d/1-FU776fV2qtg1jgcZ6mn-3ttCMAoUXv-d6FYAc_KzzY/edit)

* **What Centum asked:** move RFQ work off portal logins; their IT and Menaka asked urgently for API intake. CAM 4.0 needs one common backend for both the UI login and the API.  
* **What we proposed:** a headless, API-driven CAM 4.0 that works through Centum's own Microsoft channels: OneDrive, SharePoint, Outlook 365 and Teams (Microsoft Graph integrations, four channels). Their team drops BOM files at end of day and returns to finished, checked RFQ reports. Heavy calculation runs in cloud sandboxes, so no laptop upgrades.  
* **Intelligence layer in the proposal:** an Intelligence Hub that turns natural-language questions into read-only SQL on the execution database; GraphRAG for root-cause answers linking contracts and vendor notes to cost changes; and a sales-quote generator using FastMCP tools and xlsxtpl templates. A human-review micro-app and thumbs up/down feedback are included.  
* **Delivery plan in the proposal:** four weeks: API architecture, workflow changes, reports and insights testing, go-live. Treat this as the proposal's commitment to manage, not a verified capability. Earlier review flagged proposal claims like zero training, zero waiting and zero calculation errors as things not to repeat as fact.  
* **Commercials as proposed (internal record):** INR 2,50,000 one-time build (50 percent advance, 50 percent after week 4); INR 25,000 per month upkeep retainer; per-BOM processing of INR 350 (up to 500 line items), INR 750 (501 to 4,999), INR 1,050 (5,000 and above). GST extra.  
* **What this means for the API:** Centum is the first real consumer of the four request modes. Their SharePoint/OneDrive drops are push or polling, Outlook is email, and Teams is the conversational front door. Build the API contract once for this case; do not fork a per-client backend.

# **The proposed API contract** 

Condensed from the v0.2 governance review of the 7 October plan. The full OpenAPI 3.1 draft is in the appendix; it is a review draft, not a deployed API.

## **Architecture alignment** 

* **One backend, governed components.** BAM builds and certifies skills and configurations; SRI runs the approved versions. Temporal owns durable workflow state, Pydantic AI the typed contracts, FastMCP the tool boundary, Bifrost model routing. BuLLML is intelligence; BuLLMind is reporting. REPEL is designed to gate every action (planned; enforcement evidence still open - see Open items for Akshay).  
* **Reuse first.** Map the contract to real operation IDs before implementing; reuse the existing backend, schemas, approved manifests, auth, review screens and report jobs. No generic run-anything endpoint, no per-client fork, no parallel reporting backend.  
* **Two pilot tracks.** Track 1 is the ten-day engineering pilot: internal report generation plus authenticated API delivery. Track 2 is a first assistant-facing pilot: read-only RFQ status or an existing report with approved or synthetic data. A report API existing does not make it callable from a personal assistant by default.

## **Operations in the draft contract** 

* POST /v1/ingestions (202; normalized BOM JSON); GET /v1/boms/{bomId}; POST /v1/reports (202); GET /v1/reports/{reportId}; GET /v1/reports/{reportId}/output; GET /v1/workflows/{workflowId}; POST /v1/ingestion-events (registered-source events only); plus signed completion callbacks to admin-registered destinations.  
* **Proposed raw-file extension:** POST /v1/rfq-intakes for RFQ metadata plus completed upload or object references, feeding the same workflow and dedup ledger. The normalized-JSON endpoint alone does not meet raw-file intake; the client sends BOMs, drawings and Gerbers.

## **Async, dedup and error rules** 

* 202 means durably accepted, with a Location status URL. Succeeded requires a persisted artifact with checksum plus independent acceptance.  
* Idempotency-Key binds tenant + operation + business key; same key and body returns the original IDs, changed body returns 409. Proposed seven-day key retention; durable business uniqueness must survive expiry.  
* Errors use application/problem+json with a safe code and correlation ID; no secrets or stack traces. Status codes: 400, 401, 403, 404, 409, 413, 415, 422, 429 (with Retry-After and rate headers), 503. Proposed caps: 10 MiB decompressed JSON, 50,000 BOM items, depth 20; validate against real samples.

## **Identity, tenant and approval rules** 

* Resolve a verified user, current membership, selected firm, allowed workflow and approved version before SRI runs. Tenant comes from the server-side authenticated binding; never from a phone number, subdomain or caller header.  
* If policy requires approval before a POST, return 403 with code approval_required and a correlation ID, and enqueue nothing. Approval binds the named reviewer, firm, exact object and version, input hash, and expiry; at commit, re-check identity, role, revocation and one-time use. A WhatsApp yes or a held link is not blanket consent.  
* Execution responses carry a proposed binding: capabilityId, skillVersion, configVersion and policyDecisionId.

## **Ingestion and reporting rules** 

* PDFs and SOWs go through the documented Cognee context pipeline (not LightRAG), after malware, type and size checks. Extracted content is untrusted data; deterministic validation and human review resolve ambiguous quantities, units, currency or pricing. Never invent a quote price.  
* Reporting uses approved Excel templates verified for totals, formulas, styles, currency and provenance before delivery. HubDB is a proposed private reporting adapter, not operational storage. Superset needs a verified SQL source with tenant and row-level access. DuckDB is scoped transformation, not durable state.  
* Channel boundary: a permitted channel adapter verifies provider signatures, deduplicates provider events, and resolves authenticated bindings before routing intent. Default outbound content is minimal status plus an authenticated review link. Magic links open a scoped review and never mutate on GET. Instinct access remains unconfirmed; if unsupported, keep the web pilot.

## **RFQ business boundary (CAM/EMS)** 

* The RFQ skills sheet defines 13 business steps from input standardization to quote. The API is the delivery boundary, not a substitute for those steps.  
* Missing input becomes a clarification list, never invented values. Add and approve a clarification/review state before production; the draft states are queued, running, succeeded, failed and cancelled.  
* Order matters: finalize the BOM pricing report before the sales quote; quote cost build-up uses approved client rules.  
* Reports consume an immutable approved BOM revision, template version and pricing rules; persist checksum and source revision for reproducibility.  
* Until the real BAM skill is ready, a deterministic fixture adapter stands in, marked as mock and never customer-ready.

# **Security: the OWASP API Top 10 plan** 

Added 17 October from the OWASP API Security Top 10 (2023), as an implementable plan against this contract. Owners are roles, to be assigned. Source: Google AI Mode summary shared by Srinath ([https://share.google/aimode/Y1D3X92cL0ltwuPes).](https://share.google/aimode/Y1D3X92cL0ltwuPes).)

* **The ten risks to design against:** broken object-level authorization (BOLA); broken authentication; broken object property-level authorization; unrestricted resource consumption; broken function-level authorization; unrestricted access to sensitive business flows; server-side request forgery (SSRF); security misconfiguration; improper inventory management; unsafe consumption of third-party APIs.  
* **Object and tenant authorization on every request (API1, API5).** Enforce tenant and object-level checks inside each endpoint handler, not only at the gateway; extend the check to every object ID (bomId, reportId, workflowId). Owner: backend engineer. Evidence: negative tests returning 403 or 404 across tenants.  
* **Authentication hardening (API2).** Short-lived signed JWTs with explicit expiry and audience checks. Issuer, audience and token endpoint still need approval. Evidence: expired or wrong-audience tokens rejected with 401.  
* **Rate limits and size caps on every endpoint (API4, API6).** Set and enforce concrete limit values (still proposals), including on report generation. Evidence: load test showing 429 and 413 behavior.  
* **Strict input and output validation (API3, API10).** Validate every request against the schemas (additionalProperties: false is set) and filter every response; apply the same validation to data coming back from third-party APIs and ingestion sources. Evidence: contract tests rejecting extra or malformed fields.  
* **Error handling and configuration (API8).** Return the generic Problem envelope outward; keep stack traces in internal logs; review CORS; remove default credentials before deployment. Evidence: error responses contain no internals.  
* **SSRF guard (API7).** No endpoint may fetch an arbitrary user-supplied URL. The ingestion-events endpoint already requires a source allowlist and replay check. Evidence: test showing arbitrary URLs are rejected.  
* **Endpoint inventory (API9).** Keep one live list of deployed endpoints and versions, starting from the OpenAPI appendix; retire or protect old versions when the contract changes. Evidence: inventory reviewed at each contract revision.  
* **Security verification gate.** Add an OWASP API Top 10 pass to the Day 9 and Day 10 evidence gates: an automated scan (for example OWASP ZAP) plus manual checks before acceptance. Owner: security reviewer. Evidence: scan report and signed-off checklist.  
* **Already covered in the draft contract:** tenant derived from server-side binding; approval_required flow with correlation ID; 429 and 413 on every endpoint (limit values still proposals); problem+json envelope; source allowlist on ingestion events.

# **Build plan and evidence gates** 

## **The ten-day pilot (proposed sequence)** 

From the 7 October plan. Day 1 correct the checklist; Day 2 set up tracking; Days 3-4 API contract; Days 5-6 reporting; Days 7-8 async; Day 9 tests and mocks; Day 10 working output. Calendar versus working days is unresolved. This sequence is a plan, not a record of completed work.

* **Day 1:** correct item 10 everywhere; keep item 8 operational only; confirm the named reporting tools.  
* **Day 2:** prepare the ten checklist tasks for ClickUp with named owners and dates. Sriniketh is the requested tracker. No tasks have been created yet.  
* **Days 3-4:** OpenAPI 3.1 spec: endpoints, errors, auth, ingestion limits and triggers.  
* **Days 5-6:** reporting design: inputs and outputs, Excel templates, HubDB model, Superset datasets, DuckDB transforms, output API. One selected pilot template.  
* **Days 7-8:** async: 202 + workflow ID, business-key idempotency, separate workers, retry policy, polling and callbacks.  
* **Day 9:** Schemathesis contract tests against a running service, plus Prism mocks. Record pinned versions, exact commands, environment, commit, coverage and failures. Schema validation alone is not a contract test.  
* **Day 10:** the demo: reviewed spec, real test results, a report request returning 202, poll to succeeded, download the Excel through the API, open it and check sheets, values and formatting. No slides; a mock is not a pass.

## **Fast-build gates (from the 10 October master)** 

Two lanes, one reviewed interface. The API lane builds acceptance, status, dedup, auth, file checks and report delivery while the BAM lane readies certified RFQ skills. They join through a versioned processing adapter: mock first, real adapter second, same contract tests throughout. Start testing with Gate B rather than deferring all testing to Day 9, while retaining the full checklist acceptance gate.

* **Gate A - agree the slice:** meeting and demo scope, source route, data boundary, approved sample RFQ, one Excel template, accountable roles. Publish the mock contract immediately for parallel work.  
* **Gate B - tested receipt:** thin push + durable storage/queue + status + idempotency. Show a valid submission, duplicate replay, invalid input and wrong-client denial.  
* **Gate C - tested report delivery:** a deterministic approved fixture generates one Excel report; 202, poll, authenticated download. Label mocked business processing while BAM is unfinished.  
* **Gate D - BAM join:** replace the fixture with certified skills; validate raw-file normalization, clarification behavior, report-before-quote order, worker restart and retry/replay against real approved samples.  
* **Gate E - meeting evidence:** frozen reviewed spec and commit, sanitized passing logs, workflow and report IDs, artifact checksum, and a workbook that has been opened and checked. A successful narrow demo is not full RFQ acceptance.

## Test lane and acceptance detail (from the 10 October master)

* **Runner and collections:** version one primary collection (Postman or Bruno) alongside the OpenAPI contract and pick one primary runner for CI; export another format only if useful. Inject secrets through approved CI secret storage; never commit them. Pin installed versions and commands.  
* **Acceptance cases:** happy path (approved file to durable receipt, status lifecycle, report request, artifact download with MIME, checksum and workbook checks); contract negatives (missing fields, wrong content type, unknown IDs, 202 plus Location, safe problem details); security (expired or wrong-audience tokens, cross-client access, arbitrary-source SSRF, bad email signatures, callback replay, secret leakage in logs); files and parsing (oversized or malformed files, scan quarantine, incomplete uploads, formula injection); idempotency (same key and body returns the original IDs; duplicate or out-of-order events never create second jobs); recovery (kill and restart after durable acceptance; exhausted retries go to DLQ replay); business (approved golden samples; the BOM pricing report precedes the quote; missing detail returns clarification); isolation and performance (realistic file and BOM samples, concurrency and rate-limit behavior; record actual latency and memory - do not infer capacity from synthetic mocks).  
* **Per-run evidence:** record environment, commit, tool versions, timestamp, coverage, pass and fail counts and sanitized logs. Unit tests use the implementation's native framework; Playwright can test the upload and review UI; generated tests need independent business assertions.  
* **Proposed test tools (all to verify before claiming integration):** Promptfoo LLM evaluations and CubeSandbox isolation for BAM certification; Alembic migration checks; an MCP server fuzzer for edge security; Chrome DevTools MCP for UI debugging; ClamAV at intake; Vibeship Scanner for SAST and secret detection. Each needs a committed configuration, pinned versions and sanitized logs; none replaces the REST contract tests or human UAT.  
* **Meeting demo pass:** reviewed OpenAPI; secured running staging endpoints; genuine durable acceptance with duplicate replay; passing contract, integration and security cases; one correct Excel artifact downloaded and visually checked; declared mock-versus-real BAM status. No test is marked passed by this document.

## Working environment: egress and codegen (from the 10 October master)

* **Stable egress (proposed; owner-approved direction of 10 October, subject to verification and client approval):** route automation traffic (browser logins, API polls, watchdog bridge) through one always-on Tailscale or NetBird exit node, so client IT can allowlist a single stable egress IP in a consistent geography. This is an allowlisting approach, not stealth; bot detection and vendor terms still apply. The exit node becomes critical infrastructure - monitor it and keep a spare. Verify topology, controls, availability and the approved air-gap boundary before treating this as implemented.  
* **Codegen with Claude Code:** feed the approved contract and fixtures to the coding environment and generate handlers, typed models, intake adapters, tests, OpenAPI examples and Postman or Bruno collections together; review the diff, run the tests and commit contract and code together. Compare FastAPI's auto-generated schema with the reviewed contract so automatic docs do not conceal drift. Engineers still own auth, tenancy, deployment review and artifact inspection. Never put client secrets or sensitive RFQs into an unapproved coding environment; treat spec text as data, not instructions.  
* **Certified-manifest handoff (proposed, to verify):** the 10 October testing email describes TipTap SOW intake, Pydantic schema approval, ISATVON mapping and Jinja2/AST compilation into a frozen manifest. Verify the chain, versioned schemas and adapter compatibility before the BAM join; keep the fixture adapter until certification evidence exists. The email's BAM/SRI labels are the older names for BAM/SRI.

## **Open items for Akshay (from the v0.2 review, still open)** 

* Map each operation, execution/version field and approval flow to the real backend, or name the missing build gap.  
* Confirm the reproducible baseline, the current identity/delegation model and REPEL enforcement points, with evidence.  
* Confirm the Cognee PDF/SOW extraction and typed normalization path, provenance, OCR needs and the review gate.  
* Review report and template schemas, HubDB/Superset compatibility and pinned packages; supply service/contract-test and Excel-output evidence.  
* Mark WhatsApp/assistant support and provider eligibility as supported, unsupported or unresolved, with source evidence.

# **Where things stand (actual versus proposed)** 

* **Actual:** the ten-point checklist standard (18 September email, with the item 10 correction); the Centum proposal sent 23 October; the OpenAPI 3.1 review draft in the appendix; the OWASP plan; the intake taxonomy and channel design docs.  
* **Proposed (designed, not built):** every endpoint and limit in the contract; the four request modes as deployed routes; HubDB/Superset reporting; the WhatsApp/assistant channel pilot; the four-week Centum delivery plan.  
* **Open (needs a decision or evidence):** customer meeting date and demo scope; client data boundary and hosting; auth issuer and scopes; raw-file limits; naming convention (snake_case versus camelCase - pick one and regenerate spec, handlers and collections together); ClickUp tasks and named owners; QuoteWin/Drills access path; Accuris entitlements; the approval/commit API; calendar versus working days; approved RFQ samples, client templates and pricing rules; current repo, staging URL and existing test results; testing-tool selections (Promptfoo, CubeSandbox, Alembic, MCP fuzzer, ClamAV, Vibeship) with committed configurations.  
* **Not verified anywhere in this doc:** a running endpoint, a passing contract test, a generated Excel report through the API, a deployed channel connector. The Day 9 and Day 10 gates exist to produce exactly that evidence.

# **Sources** 

* **Checklist thread:** Gmail, srinath.r@digibull.ai, "API checklist - add in clickup" - original 18 September checklist, Akshay's 23 September sprint plan (superseded), corrections of 23, 29 September and 2, 6 October, and Akshay's 7 October revised plan (the canonical proposed specification).  
* **Centum:** proposal doc (sent 23 October by Sriniketh to centumelectronics.com): [https://docs.google.com/document/d/1-FU776fV2qtg1jgcZ6mn-3ttCMAoUXv-d6FYAc_KzzY/edit](https://docs.google.com/document/d/1-FU776fV2qtg1jgcZ6mn-3ttCMAoUXv-d6FYAc_KzzY/edit) . Srinath's related 19 October meeting-summary email is still an unsent draft.  
* **Internal docs:** Workflow team meeting - three access modes (30 September): [https://docs.google.com/document/d/1v-aRTB4Bp476adjJexrNUQz-K1GDxT5C6wn7hYm-VGk/edit](https://docs.google.com/document/d/1v-aRTB4Bp476adjJexrNUQz-K1GDxT5C6wn7hYm-VGk/edit) ; RFQ intake and tool connections for the EMS client (10 October): [https://docs.google.com/document/d/1cQ6ZPUzr0xDQ_0I1Owj4nBBlcbCPREjQDymQcjKin28/edit](https://docs.google.com/document/d/1cQ6ZPUzr0xDQ_0I1Owj4nBBlcbCPREjQDymQcjKin28/edit) ; BuLLM - Data Ingestion: [https://docs.google.com/document/d/1Kjbox8VMdlY9iUIVbwSQyOoyMYxtELZAI7V_ksVmRZM/edit](https://docs.google.com/document/d/1Kjbox8VMdlY9iUIVbwSQyOoyMYxtELZAI7V_ksVmRZM/edit) ; BuLLM Wiki: Bifrost Gateway: [https://docs.google.com/document/d/1CNmQj-Qqv0v6xyeLZtahkOrqn1CyOwHjSc0DntIcFI8/edit](https://docs.google.com/document/d/1CNmQj-Qqv0v6xyeLZtahkOrqn1CyOwHjSc0DntIcFI8/edit)  
* **Gemini design session:** \[Gemini Conversation\] BuLLM - Architecture Components (ingestion channel mechanics and the selection matrix): [https://gemini.google.com/share/d/11Mktfnus27aBRjS7pDK63p97x-KoMAkE](https://gemini.google.com/share/d/11Mktfnus27aBRjS7pDK63p97x-KoMAkE)  
* **Folded in fully:** RFQ Automation API - Master Document (10 October): [https://docs.google.com/document/d/16R8ls_01ttaA36pZpfx4iypcitoAjD7lRzWGzWELMls/edit](https://docs.google.com/document/d/16R8ls_01ttaA36pZpfx4iypcitoAjD7lRzWGzWELMls/edit) . All of its content is carried in this doc; the original remains in Drive as an archival reference.  
* **From the 10 October master (archival source list):** Akshay's 23 September sprint plan (superseded history) and his 7 October revised plan; RFQ Intake Options and Tool Integration Plan - EMS Client; BuLLM Wiki: Orchestration (FastAPI, Temporal, Prefect); API Proposal for Centum - Draft; BuLLMQuote skills sheet 2 (the 13-step EMS process); the Gemini RFQ design conversation (older unverified research); FastAPI automatic OpenAPI/docs; Bruno and Postman collection runners; the Claude Code security/review boundary; Temporal Schedules; the FastMCP HTTP/custom-route boundary; the 10 October 'BuLLM api & ui testing' email (srinath.r to Sriniketh, Gmail thread 1a125600a2611b5c); the MASTER TESTING DOCUMENT and the RFQ Automation SRI UI Responsibility Matrix A & C (concepts only; their example identities, quotas and zero-dev claims are not adopted).  
* **Owner voice notes:** 29 September (four API modes; privacy and channel discussion) and 26 October (this restructure). WhatsApp records in the assistant's history.  
* **Change log:** v0.2 (16 October) added the OWASP plan and governance review. v0.3 (26 October) bundled the checklist email, Centum proposal, internal docs and Gemini sessions; deepened the four request modes; corrected the REPEL expansion; folded the 10 October RFQ API master into this one living document.

# Appendix: OpenAPI 3.1 review draft

Complete proposed YAML contract below. The Google Doc is the delivered review artifact; copy the embedded YAML for engineering review. No deployed server or test pass is claimed. This draft needs owner review, runtime implementation and contract-test execution before acceptance.

# openapi: 3.1.0

# info: {title: BuLLM API - proposed review contract, version: 0.2.0-draft, description: 'Proposed review contract v0.2, not a deployed API. Reuse current BuLLM contracts before building. REPEL enforcement, approved skill/config versions and tenant binding are required. No server, Instinct connector, combined SSO or white-label rights verified. Numeric limits remain proposals.'}

# paths:

#   /v1/ingestions:

#     post:

#       operationId: createIngestion

#       summary: Normalize BOM revision asynchronously; business key projectId/revision.

#       x-required-scopes:

#       - boms:write

#       responses:

#         '202':

#           description: Accepted for durable asynchronous processing.

#           content:

#             application/json:

#               schema: {$ref: '#/components/schemas/Accepted'}

#           headers:

#             Location:

#               description: Workflow status resource.

#               schema: {type: string, format: uri-reference}

#             Retry-After:

#               description: Proposed polling delay in seconds.

#               schema: {type: string, example: '3'}

#         '400': {$ref: '#/components/responses/Problem'}

#         '401': {$ref: '#/components/responses/Problem'}

#         '403': {$ref: '#/components/responses/Problem', description: Forbidden or policy requires approval before acceptance. code=approval_required denotes no work was enqueued; this is not a bypass token.}

#         '404': {$ref: '#/components/responses/Problem'}

#         '409': {$ref: '#/components/responses/Problem'}

#         '413': {$ref: '#/components/responses/Problem'}

#         '415': {$ref: '#/components/responses/Problem'}

#         '422': {$ref: '#/components/responses/Problem'}

#         '429':

#           description: Operational throttle only, no monetization tier.

#           headers:

#             Retry-After:

#               schema: {type: string}

#             X-RateLimit-Limit:

#               schema: {type: integer}

#             X-RateLimit-Remaining:

#               schema: {type: integer}

#             X-RateLimit-Reset:

#               schema: {type: integer}

#           content:

#             application/problem+json:

#               schema: {$ref: '#/components/schemas/Problem'}

#         '503': {$ref: '#/components/responses/Problem'}

#       parameters:

#       - name: Idempotency-Key

#         in: header

#         required: true

#         schema: {type: string, minLength: 1, maxLength: 128}

#         description: Tenant + operation + business-key deduplication; same request returns original IDs. Reuse with different body returns 409. Proposed retention 7 days.

#       requestBody:

#         required: true

#         content:

#           application/json:

#             schema: {$ref: '#/components/schemas/BomInput'}

#       x-bullm-policy:

#         actor: validated subject + current membership

#         tenant: derived from server-side authenticated binding

#         checks:

#         - execution

#         - artifact disclosure

#         effect: internal draft generation; no external send, pricing acceptance or production commit

#         require-approval: return approval_required with correlationId if policy requires consent; create no workflow until approved through existing reviewed approval flow

#   /v1/boms/{bomId}:

#     get:

#       operationId: getBom

#       summary: Read normalized BOM, tenant-scoped.

#       x-required-scopes:

#       - boms:read

#       responses:

#         '200':

#           description: Successful response.

#           content:

#             application/json:

#               schema: {$ref: '#/components/schemas/Bom'}

#         '400': {$ref: '#/components/responses/Problem'}

#         '401': {$ref: '#/components/responses/Problem'}

#         '403': {$ref: '#/components/responses/Problem'}

#         '404': {$ref: '#/components/responses/Problem'}

#         '409': {$ref: '#/components/responses/Problem'}

#         '413': {$ref: '#/components/responses/Problem'}

#         '415': {$ref: '#/components/responses/Problem'}

#         '422': {$ref: '#/components/responses/Problem'}

#         '429':

#           description: Operational throttle only, no monetization tier.

#           headers:

#             Retry-After:

#               schema: {type: string}

#             X-RateLimit-Limit:

#               schema: {type: integer}

#             X-RateLimit-Remaining:

#               schema: {type: integer}

#             X-RateLimit-Reset:

#               schema: {type: integer}

#           content:

#             application/problem+json:

#               schema: {$ref: '#/components/schemas/Problem'}

#         '503': {$ref: '#/components/responses/Problem'}

#       parameters:

#       - name: bomId

#         in: path

#         required: true

#         schema: {type: string, minLength: 1, maxLength: 128}

#       x-bullm-policy:

#         actor: validated subject + current membership

#         tenant: derived from server-side authenticated binding

#         checks:

#         - execution

#         - disclosure

#         effect: read-only

#         require-approval: return approval_required with correlationId if policy requires consent; create no workflow until approved through existing reviewed approval flow

#   /v1/reports:

#     post:

#       operationId: createReport

#       summary: Generate engineering or SOW XLSX, or BOM JSON. Business key bomId/reportType/templateId/format.

#       x-required-scopes:

#       - reports:write

#       responses:

#         '202':

#           description: Accepted for durable asynchronous processing.

#           content:

#             application/json:

#               schema: {$ref: '#/components/schemas/ReportAccepted'}

#           headers:

#             Location:

#               description: Workflow status resource.

#               schema: {type: string, format: uri-reference}

#             Retry-After:

#               description: Proposed polling delay in seconds.

#               schema: {type: string, example: '3'}

#         '400': {$ref: '#/components/responses/Problem'}

#         '401': {$ref: '#/components/responses/Problem'}

#         '403': {$ref: '#/components/responses/Problem', description: Forbidden or policy requires approval before acceptance. code=approval_required denotes no work was enqueued; this is not a bypass token.}

#         '404': {$ref: '#/components/responses/Problem'}

#         '409': {$ref: '#/components/responses/Problem'}

#         '413': {$ref: '#/components/responses/Problem'}

#         '415': {$ref: '#/components/responses/Problem'}

#         '422': {$ref: '#/components/responses/Problem'}

#         '429':

#           description: Operational throttle only, no monetization tier.

#           headers:

#             Retry-After:

#               schema: {type: string}

#             X-RateLimit-Limit:

#               schema: {type: integer}

#             X-RateLimit-Remaining:

#               schema: {type: integer}

#             X-RateLimit-Reset:

#               schema: {type: integer}

#           content:

#             application/problem+json:

#               schema: {$ref: '#/components/schemas/Problem'}

#         '503': {$ref: '#/components/responses/Problem'}

#       parameters:

#       - name: Idempotency-Key

#         in: header

#         required: true

#         schema: {type: string, minLength: 1, maxLength: 128}

#         description: Tenant + operation + business-key deduplication; same request returns original IDs. Reuse with different body returns 409. Proposed retention 7 days.

#       requestBody:

#         required: true

#         content:

#           application/json:

#             schema: {$ref: '#/components/schemas/ReportRequest'}

#       x-bullm-policy:

#         actor: validated subject + current membership

#         tenant: derived from server-side authenticated binding

#         checks:

#         - execution

#         - artifact disclosure

#         effect: internal draft generation; no external send, pricing acceptance or production commit

#         require-approval: return approval_required with correlationId if policy requires consent; create no workflow until approved through existing reviewed approval flow

#   /v1/reports/{reportId}:

#     get:

#       operationId: getReport

#       summary: Read report metadata.

#       x-required-scopes:

#       - reports:read

#       responses:

#         '200':

#           description: Successful response.

#           content:

#             application/json:

#               schema: {$ref: '#/components/schemas/Report'}

#         '400': {$ref: '#/components/responses/Problem'}

#         '401': {$ref: '#/components/responses/Problem'}

#         '403': {$ref: '#/components/responses/Problem'}

#         '404': {$ref: '#/components/responses/Problem'}

#         '409': {$ref: '#/components/responses/Problem'}

#         '413': {$ref: '#/components/responses/Problem'}

#         '415': {$ref: '#/components/responses/Problem'}

#         '422': {$ref: '#/components/responses/Problem'}

#         '429':

#           description: Operational throttle only, no monetization tier.

#           headers:

#             Retry-After:

#               schema: {type: string}

#             X-RateLimit-Limit:

#               schema: {type: integer}

#             X-RateLimit-Remaining:

#               schema: {type: integer}

#             X-RateLimit-Reset:

#               schema: {type: integer}

#           content:

#             application/problem+json:

#               schema: {$ref: '#/components/schemas/Problem'}

#         '503': {$ref: '#/components/responses/Problem'}

#       parameters:

#       - name: reportId

#         in: path

#         required: true

#         schema: {type: string, minLength: 1, maxLength: 128}

#       x-bullm-policy:

#         actor: validated subject + current membership

#         tenant: derived from server-side authenticated binding

#         checks:

#         - execution

#         - disclosure

#         effect: read-only

#         require-approval: return approval_required with correlationId if policy requires consent; create no workflow until approved through existing reviewed approval flow

#   /v1/reports/{reportId}/output:

#     get:

#       operationId: downloadReport

#       summary: Download ready artifact; return 409 until ready.

#       x-required-scopes:

#       - reports:read

#       responses:

#         '200':

#           description: Ready report artifact.

#           headers:

#             Content-Disposition:

#               schema: {type: string}

#             X-Checksum-SHA256:

#               schema: {type: string}

#           content:

#             application/vnd.openxmlformats-officedocument.spreadsheetml.sheet:

#               schema: {type: string, format: binary}

#             application/json:

#               schema: {$ref: '#/components/schemas/BomInput'}

#         '400': {$ref: '#/components/responses/Problem'}

#         '401': {$ref: '#/components/responses/Problem'}

#         '403': {$ref: '#/components/responses/Problem'}

#         '404': {$ref: '#/components/responses/Problem'}

#         '409': {$ref: '#/components/responses/Problem'}

#         '413': {$ref: '#/components/responses/Problem'}

#         '415': {$ref: '#/components/responses/Problem'}

#         '422': {$ref: '#/components/responses/Problem'}

#         '429':

#           description: Operational throttle only, no monetization tier.

#           headers:

#             Retry-After:

#               schema: {type: string}

#             X-RateLimit-Limit:

#               schema: {type: integer}

#             X-RateLimit-Remaining:

#               schema: {type: integer}

#             X-RateLimit-Reset:

#               schema: {type: integer}

#           content:

#             application/problem+json:

#               schema: {$ref: '#/components/schemas/Problem'}

#         '503': {$ref: '#/components/responses/Problem'}

#       parameters:

#       - name: reportId

#         in: path

#         required: true

#         schema: {type: string, minLength: 1, maxLength: 128}

#       x-bullm-policy:

#         actor: validated subject + current membership

#         tenant: derived from server-side authenticated binding

#         checks:

#         - execution

#         - disclosure

#         effect: read-only

#         require-approval: return approval_required with correlationId if policy requires consent; create no workflow until approved through existing reviewed approval flow

#   /v1/workflows/{workflowId}:

#     get:

#       operationId: getWorkflow

#       summary: Poll durable workflow state. Callback delivery status is separate.

#       x-required-scopes:

#       - workflows:read

#       responses:

#         '200':

#           description: Successful response.

#           content:

#             application/json:

#               schema: {$ref: '#/components/schemas/Workflow'}

#         '400': {$ref: '#/components/responses/Problem'}

#         '401': {$ref: '#/components/responses/Problem'}

#         '403': {$ref: '#/components/responses/Problem'}

#         '404': {$ref: '#/components/responses/Problem'}

#         '409': {$ref: '#/components/responses/Problem'}

#         '413': {$ref: '#/components/responses/Problem'}

#         '415': {$ref: '#/components/responses/Problem'}

#         '422': {$ref: '#/components/responses/Problem'}

#         '429':

#           description: Operational throttle only, no monetization tier.

#           headers:

#             Retry-After:

#               schema: {type: string}

#             X-RateLimit-Limit:

#               schema: {type: integer}

#             X-RateLimit-Remaining:

#               schema: {type: integer}

#             X-RateLimit-Reset:

#               schema: {type: integer}

#           content:

#             application/problem+json:

#               schema: {$ref: '#/components/schemas/Problem'}

#         '503': {$ref: '#/components/responses/Problem'}

#       parameters:

#       - name: workflowId

#         in: path

#         required: true

#         schema: {type: string, minLength: 1, maxLength: 128}

#       x-bullm-policy:

#         actor: validated subject + current membership

#         tenant: derived from server-side authenticated binding

#         checks:

#         - execution

#         - disclosure

#         effect: read-only

#         require-approval: return approval_required with correlationId if policy requires consent; create no workflow until approved through existing reviewed approval flow

#   /v1/ingestion-events:

#     post:

#       operationId: acceptIngestionEvent

#       summary: Accept registered-source event. Requires source allowlist and replay check; arbitrary URLs are rejected.

#       x-required-scopes:

#       - boms:write

#       responses:

#         '202':

#           description: Accepted for durable asynchronous processing.

#           content:

#             application/json:

#               schema: {$ref: '#/components/schemas/Accepted'}

#           headers:

#             Location:

#               description: Workflow status resource.

#               schema: {type: string, format: uri-reference}

#             Retry-After:

#               description: Proposed polling delay in seconds.

#               schema: {type: string, example: '3'}

#         '400': {$ref: '#/components/responses/Problem'}

#         '401': {$ref: '#/components/responses/Problem'}

#         '403': {$ref: '#/components/responses/Problem', description: Forbidden or policy requires approval before acceptance. code=approval_required denotes no work was enqueued; this is not a bypass token.}

#         '404': {$ref: '#/components/responses/Problem'}

#         '409': {$ref: '#/components/responses/Problem'}

#         '413': {$ref: '#/components/responses/Problem'}

#         '415': {$ref: '#/components/responses/Problem'}

#         '422': {$ref: '#/components/responses/Problem'}

#         '429':

#           description: Operational throttle only, no monetization tier.

#           headers:

#             Retry-After:

#               schema: {type: string}

#             X-RateLimit-Limit:

#               schema: {type: integer}

#             X-RateLimit-Remaining:

#               schema: {type: integer}

#             X-RateLimit-Reset:

#               schema: {type: integer}

#           content:

#             application/problem+json:

#               schema: {$ref: '#/components/schemas/Problem'}

#         '503': {$ref: '#/components/responses/Problem'}

#       parameters:

#       - name: Idempotency-Key

#         in: header

#         required: true

#         schema: {type: string, minLength: 1, maxLength: 128}

#         description: Tenant + operation + business-key deduplication; same request returns original IDs. Reuse with different body returns 409. Proposed retention 7 days.

#       requestBody:

#         required: true

#         content:

#           application/json:

#             schema: {$ref: '#/components/schemas/IngestionEvent'}

#       x-bullm-policy:

#         actor: validated subject + current membership

#         tenant: derived from server-side authenticated binding

#         checks:

#         - execution

#         - artifact disclosure

#         effect: internal draft generation; no external send, pricing acceptance or production commit

#         require-approval: return approval_required with correlationId if policy requires consent; create no workflow until approved through existing reviewed approval flow

# components:

#   securitySchemes:

#     bearerAuth: {type: http, scheme: bearer, bearerFormat: JWT, description: 'Proposed OAuth2 client-credentials-issued access token. Issuer, audience and token endpoint must be approved. Operation x-required-scopes are gateway-enforced.'}

#   schemas:

#     BomItem:

#       type: object

#       additionalProperties: false

#       required:

#       - itemId

#       - partNumber

#       - quantity

#       - unit

#       properties:

#         itemId: {type: string, minLength: 1, maxLength: 128}

#         partNumber: {type: string, minLength: 1, maxLength: 128}

#         description: {type: string, maxLength: 2000}

#         quantity: {type: number, minimum: 0}

#         unit: {type: string, minLength: 1, maxLength: 32}

#         unitCost: {type: number, minimum: 0}

#     BomInput:

#       type: object

#       additionalProperties: false

#       required:

#       - projectId

#       - revision

#       - currency

#       - items

#       properties:

#         projectId: {type: string, minLength: 1, maxLength: 128}

#         revision: {type: string, minLength: 1, maxLength: 128}

#         currency: {type: string, pattern: '^\[A-Z\]{3}$'}

#         items:

#           type: array

#           minItems: 1

#           maxItems: 50000

#           items: {$ref: '#/components/schemas/BomItem'}

#     Bom:

#       type: object

#       additionalProperties: false

#       required:

#       - bomId

#       - input

#       - createdAt

#       properties:

#         bomId: {type: string, minLength: 1, maxLength: 128}

#         input: {$ref: '#/components/schemas/BomInput'}

#         createdAt: {type: string, format: date-time}

#     ReportRequest:

#       type: object

#       additionalProperties: false

#       required:

#       - bomId

#       - reportType

#       - format

#       properties:

#         bomId: {type: string, minLength: 1, maxLength: 128}

#         reportType:

#           type: string

#           enum:

#           - engineering

#           - sow_quote

#           - bom_payload

#         format:

#           type: string

#           enum:

#           - xlsx

#           - json

#         templateId: {type: string, minLength: 1, maxLength: 128}

#         callbackId: {type: string, minLength: 1, maxLength: 128}

#       allOf:

#       - if:

#           properties:

#             format: {const: xlsx}

#           required:

#           - format

#         then:

#           required:

#           - templateId

#       - if:

#           properties:

#             reportType: {const: bom_payload}

#           required:

#           - reportType

#         then:

#           properties:

#             format: {const: json}

#         else:

#           properties:

#             format: {const: xlsx}

#     Accepted:

#       type: object

#       additionalProperties: false

#       required:

#       - workflowId

#       - state

#       - statusUrl

#       - execution

#       properties:

#         workflowId: {type: string, minLength: 1, maxLength: 128}

#         state:

#           type: string

#           enum:

#           - queued

#         statusUrl: {type: string, format: uri-reference}

#         reportId: {type: string, minLength: 1, maxLength: 128}

#         execution: {$ref: '#/components/schemas/ExecutionBinding'}

#     Workflow:

#       type: object

#       additionalProperties: false

#       required:

#       - workflowId

#       - state

#       - queuedAt

#       - execution

#       properties:

#         workflowId: {type: string, minLength: 1, maxLength: 128}

#         state:

#           type: string

#           enum:

#           - queued

#           - running

#           - succeeded

#           - failed

#           - cancelled

#         queuedAt: {type: string, format: date-time}

#         startedAt: {type: string, format: date-time}

#         completedAt: {type: string, format: date-time}

#         resultId: {type: string, minLength: 1, maxLength: 128}

#         failure: {$ref: '#/components/schemas/Problem'}

#         execution: {$ref: '#/components/schemas/ExecutionBinding'}

#     Report:

#       type: object

#       additionalProperties: false

#       required:

#       - reportId

#       - bomId

#       - reportType

#       - format

#       - state

#       - workflowId

#       - createdAt

#       - execution

#       properties:

#         reportId: {type: string, minLength: 1, maxLength: 128}

#         bomId: {type: string, minLength: 1, maxLength: 128}

#         reportType:

#           type: string

#           enum:

#           - engineering

#           - sow_quote

#           - bom_payload

#         format:

#           type: string

#           enum:

#           - xlsx

#           - json

#         templateId: {type: string, minLength: 1, maxLength: 128}

#         state:

#           type: string

#           enum:

#           - queued

#           - running

#           - succeeded

#           - failed

#           - cancelled

#         workflowId: {type: string, minLength: 1, maxLength: 128}

#         checksumSha256: {type: string, pattern: '^\[0-9a-f\]{64}$'}

#         createdAt: {type: string, format: date-time}

#         execution: {$ref: '#/components/schemas/ExecutionBinding'}

#     IngestionEvent:

#       type: object

#       additionalProperties: false

#       required:

#       - sourceId

#       - eventId

#       - projectId

#       - revision

#       properties:

#         sourceId: {type: string, minLength: 1, maxLength: 128}

#         eventId: {type: string, minLength: 1, maxLength: 128}

#         projectId: {type: string, minLength: 1, maxLength: 128}

#         revision: {type: string, minLength: 1, maxLength: 128}

#         callbackId: {type: string, minLength: 1, maxLength: 128}

#     CompletionEvent:

#       type: object

#       additionalProperties: false

#       required:

#       - eventId

#       - eventType

#       - workflowId

#       - occurredAt

#       properties:

#         eventId: {type: string, minLength: 1, maxLength: 128}

#         eventType:

#           type: string

#           enum:

#           - workflow.succeeded

#           - workflow.failed

#         workflowId: {type: string, minLength: 1, maxLength: 128}

#         resourceId: {type: string, minLength: 1, maxLength: 128}

#         occurredAt: {type: string, format: date-time}

#       description: Minimal notification. Re-authorize API retrieval; receiving a callback does not grant access or approve an action.

#     Problem:

#       type: object

#       required:

#       - type

#       - title

#       - status

#       - code

#       - correlationId

#       properties:

#         type: {type: string, format: uri-reference}

#         title: {type: string}

#         status: {type: integer, minimum: 400, maximum: 599}

#         detail: {type: string}

#         instance: {type: string, format: uri-reference}

#         code: {type: string}

#         correlationId: {type: string, minLength: 1, maxLength: 128}

#     ExecutionBinding:

#       type: object

#       additionalProperties: false

#       required:

#       - capabilityId

#       - skillVersion

#       - configVersion

#       - policyDecisionId

#       description: Server-selected immutable execution context. Not caller-selected tenant/role or approval. Map to existing backend identifiers; exact field names proposed.

#       properties:

#         capabilityId: {type: string, minLength: 1, maxLength: 128}

#         skillVersion: {type: string, minLength: 1, maxLength: 128}

#         configVersion: {type: string, minLength: 1, maxLength: 128}

#         policyDecisionId: {type: string, minLength: 1, maxLength: 128}

#     ReportAccepted:

#       allOf:

#       - {$ref: '#/components/schemas/Accepted'}

#       - type: object

#         required:

#         - reportId

#   responses:

#     Problem:

#       description: Failure envelope; code and correlationId support diagnosis without secret data.

#       content:

#         application/problem+json:

#           schema: {$ref: '#/components/schemas/Problem'}

# security:

# - bearerAuth: \[\]

# webhooks:

#   workflowCompletion:

#     post:

#       operationId: receiveWorkflowCompletion

#       summary: Client receiver contract; registered HTTPS callback only. Signature wire format requires approval.

#       security: \[\]

#       parameters:

#       - name: X-BuLLM-Timestamp

#         in: header

#         required: true

#         schema: {type: string}

#       - name: X-BuLLM-Signature

#         in: header

#         required: true

#         schema: {type: string}

#       requestBody:

#         required: true

#         content:

#           application/json:

#             schema: {$ref: '#/components/schemas/CompletionEvent'}

#       responses:

#         '204': {description: 'Event verified, deduplicated and acknowledged.'}

#         '400': {description: Invalid event.}

#         '401': {description: Invalid signature or expired timestamp.}

#         '503': {description: Temporary receiver failure; sender retries.}

# x-bullm-architecture:

#   status: proposed-not-implemented

#   runtime: SRI

#   orchestration: Temporal

#   typed-contracts: Pydantic AI

#   model-routing: Bifrost

#   tools: FastMCP

#   pdf-sow-ingestion: Cognee, not LightRAG

#   policy: 'REPEL: allow, require approval, mask, deny'

#   first-channel-pilot: existing read-only RFQ status/report capability

#   instinct-connection: unconfirmed; not selected or installed

#   approval-commit-api: unresolved; no commit endpoint selected in this pilot

# 

# References and verification record

Source documents: user-uploaded API Platform Excellence & Governance Initiative DOCX and the user's Reports & Analytics requirements with ten-day sequence. The Sep 21 section 7 reporting scope was recovered during this review; prior-to-replacement mapping remains unverified. No repository, live endpoint, template file, CI log or task tracker was inspected because none was supplied for this revision.

## OpenAPI 3.1 specification

https://spec.openapis.org/oas/v3.1

## Requested error envelope and superseding RFC notice

https://www.rfc-editor.org/info/rfc7807/

## Temporal retry-policy conventions

https://docs.temporal.io/encyclopedia/retry-policies

## HubDB API guide

https://developers.hubspot.com/docs/api-reference/latest/cms/hubdb/guide

## Superset database connection guidance

https://superset.apache.org/user-docs/databases/

These references support protocol/tool conventions only. They do not validate the proposed BuLLM fields, limits, owners, dates or implementation. Tool designation xlsx-template (xlsxtpl) is preserved from the user's request pending exact package/version confirmation.

# v0.2 review sources and evidence

Reviewed live on 7 October 2026: [Current BuLLM client deployment and WhatsApp/personal-assistant architecture](https://docs.google.com/document/d/1Ptb-ZrEXgKOqhk9Dn30p4bIo2zupvnshys47pLaQW-8/edit?usp=drivesdk&authuser=sriniketh.s@digibull.ai); [ISATVON 1.4.2 Temporal update](https://docs.google.com/document/d/1OaWXGtOQRM3bQ5Ke015PKkm25CFdz3wDVmUacZIq0vI/edit?usp=drivesdk&authuser=sriniketh.s@digibull.ai); [REPEL runtime-policy description](https://docs.google.com/document/d/1AwH8ADxukhOKZemwYzBWDYp3DKR_3C-sIU5QgaoFeGg/edit?usp=drivesdk&authuser=sriniketh.s@digibull.ai). These are design records, not proof of deployment.

Owner inputs: 7 October current alignment request; new Google Doc version label v0.2; Cognee rather than LightRAG for PDF/SOW ingestion; BuLLM v1 not ready. Source attachment: API_Platform_Excellence_Governance_Initiative_Revised_07Oct26.docx, preserved unchanged. September 21 BuLLM Mastery section 7, recovered from DigiBull email, corroborates reporting tool names only. It is not authority to assign work or publish.

Protocol references opened during this review: [OpenAPI 3.1.0](https://spec.openapis.org/oas/v3.1.0); [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457); [Temporal retry policies](https://docs.temporal.io/encyclopedia/retry-policies); [Superset databases](https://superset.apache.org/docs/databases/); [HubDB guide](https://developers.hubspot.com/docs/api-reference/cms-hubdb-v3/guide). Provider feature/eligibility statements are readiness checks against the architecture, not a fresh vendor certification.

Verification status: original attachment and live design sources inspected; embedded YAML parsed and local reference checks performed. No current repo implementation, running endpoint, test log, client workbook or installed channel connector was supplied as evidence. These remain unverified, not completed. Review copy remains private until the owner approves recipient, message and document access together.