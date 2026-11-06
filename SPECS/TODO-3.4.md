# CAM 3.4 TODO (from handoff/HANDOFF-2026-11-03.md section 4; status updated as work lands)

Rules: 3.4 only. Decide, don't ask. Real proof = browser run with screenshots, console, network.

1. [~] Real UI run, end to end (RFQ-000007 reached final-selection gate via real UI; final-selection modal not yet confirmed on screen), through the Browser (Playwright at localhost:5173): log in, create RFQ, upload BOM, watch SSE progress, intake HITL, upload QuoteWin, continue, final-selection review, exports. Evidence per control.
2. [x] Compose: python-bridge service on :13110, exports volume, CAM_DAEMON_URL (commit 2988249).
3. [x] Rebuild fastapi-router, upload-server, hitl-router, temporal-worker, python-bridge (all Up on current code).
4. [x] Daemon up on :9334 (currency_name schema fix, commit 2988249).
5. [ ] RFQ_Flow inside 3.4: profile selection per upload (CAM_DEFAULT_PROFILE + request field), router honours hitl_required, env-var bom_storage path (done for duck_db_api and hitl_router).
6. [ ] Distributor: run to the vendor-API-key boundary (DigiKey/Mouser/Element14 keys unavailable), record it.
7. [ ] import_bom ignores "already exists" failure: fix.
8. [ ] Add .dockerignore (images about 5.5 GB).
9. [ ] Commit UI-run fixes: RfqIntakeProgressPanel QuoteWin button (restored; was removed, workflow needs QuoteWin). Not committed yet.
   9a. [ ] Intake panel stays on 'Standardizing BOM' after later steps (stale status).
   9b. [ ] Final-selection review: confirm modal renders on screen.
   9c. [ ] rfq-memory not running: upload logs MEMORY INGEST ERROR (non-fatal).
10. [ ] SPEC-018 dynamic recalculation: proposed only; needs design approval before code.
