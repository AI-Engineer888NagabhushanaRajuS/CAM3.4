# Findings &amp; fixes — Centum / BuLLMQuote-SRIM

Every item here was independently reproduced against live source or a live,
non-mutating process check — not copied from a prior report without
re-checking. Where two passes agree, both are cited.

---

## 1. [HIGH — fix now] HITL resume webhook is dead on both ends

**What's wrong:** When a user approves certain HITL (human-in-the-loop)
decisions, `accomplish-ui/apps/daemon/src/browser-api-server.ts` (~line 1023)
fires an un-awaited `POST` to `http://127.0.0.1:8000/api/orchestrator/resume`,
with no timeout and no response check, then immediately returns
`{success: true}` to the browser.

**Why it's actually broken, not just risky:**
- Zero route anywhere in the Python backend (`fastmcp-router/`) handles
  `POST /api/orchestrator/resume`. Confirmed via repo-wide grep for
  `@app.post`/`@router.post` near "resume" — zero matches.
- The Postgres column this webhook exists to help manage, `hitl_required`,
  is **write-only**: `get_hitl_state()`, the only function in the codebase
  that reads it, has zero call sites anywhere.
- The pipeline doesn't actually need this webhook. A separate, correctly
  wired mechanism already works: Dify polls via `/trigger-hitl`, and 2 real
  gates — `resolve_final_selection` and `detect_alternates`, both in
  `fastmcp-router/hitl_router.py` — advance the pipeline on approval.

**Repro (read-only):**
```bash
grep -rn "@app.post\|@router.post" fastmcp-router/ | grep -i resume   # zero matches
grep -rn "get_hitl_state" . --include="*.py"                          # only the definition, zero callers
```

**Smallest fix:** In `browser-api-server.ts`, either (a) delete the dead
webhook call and the `hitl_required` column write entirely, since nothing
reads it, or (b) if you want to keep a notification mechanism, `await` the
fetch and check `response.ok` before returning success — that at minimum
stops lying to the user. Deleting is smaller and the council's recommendation,
since nothing downstream depends on this path.

**Citations:** `accomplish-ui/apps/daemon/src/browser-api-server.ts` ~991–1034
· `fastmcp-router/db.py` (`get_hitl_state`) · `fastmcp-router/hitl_router.py`
~199–328, ~494–561.

---

## 2. [MEDIUM — fix before migration, not before] Standard_BOM_Flow routing bug is real but latent

**What's wrong:** `fastmcp-router/tool_calling.py`'s `_endpoint_url()` splits
a tool name on its first `-` to find the registered Bifrost client. Jungle-style
tool names (e.g. `centum_reporting__cbom`) use a double underscore, not a
hyphen — `tool_name.partition("-")` finds nothing to split on, treats the
whole string as the client, and the lookup misses, raising:

```
ValueError: No Bifrost endpoint_slug registered for client 'centum_reporting__cbom'
```

Reproduced directly via a unit-level call to the real function, twice.

**Why it's not urgent:** `Standard_BOM_Flow` has no entry anywhere in
`dify-orchestration/` (only `Dify_DMR_RFQ_Flow.yml` exists) and, per
`config.py` and `manage_backend.py`'s own comments, still routes through MCP
Jungle directly — it never reaches this router under current operation.
**Zero active impact today.** It activates immediately if `Standard_BOM_Flow`
is ever migrated onto Bifrost without first fixing this.

**Full pre-migration checklist:** see
[MIGRATION-RISK-STANDARD-BOM-FLOW.md](MIGRATION-RISK-STANDARD-BOM-FLOW.md).

**Citations:** `fastmcp-router/tool_calling.py` ~1–33 · `fastmcp-router/fastapi_router.py`
:14, 557 · `config.py` ~1–3 · `manage_backend.py` ~37–38, 444–447.

---

## 3. [LOW — documentation only] HITL type count was wrong

The architecture dossier (pre-this-session) stated "4 special HITL types"
have a working resume path. The real number, traced to code, is **2**:
`resolve_final_selection` and `detect_alternates`. Not actionable beyond
correcting the number — already fixed in `architecture-dossier.html` Rev C.

---

## 4. [Informational] Two subsystems are real, despite a mid-review false alarm

During this session's review, one verification stage briefly concluded that
the Cognee-backed RFQ memory service and the entire FDE Staging Pipeline
didn't exist — because it searched the wrong, similarly-named sibling project
(`centum intake` instead of this repo). This was caught and corrected before
it reached any conclusion. Both are confirmed real in the correct repo:

- `mcp-tools/rfq-memory/` — substantial working code (`memory_service.py`,
  `ingest.py`, `query.py`, `citation_store.py`, `versioning.py`), integrated
  via `fastmcp-router/rfq_memory_client.py`. Ports 8108/8109 confirmed
  listening.
- FDE pipeline — exactly 1 of 6 stages built. `accomplish-ui/apps/web/src/client/components/fde/FDEUploadDocsPanel.tsx`
  is real and implemented; `FDEStageStub.tsx` is what every other stage
  (`cognify`, `okf_bundle`, `sow_generation`, `validation`, `skill`) renders
  instead — a named placeholder, not a hidden gap.

No fix needed — this entry exists so the false alarm doesn't get
rediscovered and re-reported as new.

---

## 5. [See SECURITY-REPORT.md] 5 security gaps

Covered in their own document since they share one remediation owner and one
deployment-gate decision: [SECURITY-REPORT.md](SECURITY-REPORT.md).
