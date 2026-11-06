# RFQ Chat / Cognee Investigation Report — Dataset Isolation Blocker

**Status: RESOLVED (2026-09-10).** The original blocker (below) — Cognee's
`search()` not honoring the `datasets=[...]` parameter reliably — is fixed.
The real isolation boundary is a different, more granular Cognee mechanism:
`search(node_type=NodeSet, node_name=[tag])`, filtering on a single explicit
node-level tag rather than trusting the dataset parameter. Verified via 3
independent test rounds (2-way, 3-way, and a full integration test against
this service's own real `ingest.py`/`query.py`/`citation_store.py`), each
including a genuine process restart between write and verify, each with
zero cross-RFQ leakage. See "Resolution" at the bottom of this document for
the concrete fix and what changed in the implementation. The rest of this
document is preserved as-is below as the factual record of the original
investigation, so the reasoning that led to the fix stays visible.

## What this investigation was for

The approved implementation plan for the BuLLMQuote-SRIM RFQ chat feature
(`C:\Users\ADMIN\.claude\plans\we-have-an-existing-harmonic-cocke.md`)
specifies Cognee (https://github.com/topoteretes/cognee) as a per-RFQ
memory/retrieval layer, with isolation enforced by giving each RFQ its own
Cognee dataset (`rfq_{rfq_id}`) and always deriving that dataset name
server-side from a JWT-verified `rfq_id`. Before wiring this into
production ingestion/retrieval, the plan's own mandatory requirements (and
a follow-up explicit instruction) required proving that isolation actually
holds at the Cognee layer itself — not just that the dataset-naming
convention is correct.

## Environment

- OS: Windows 10 (10.0.26200)
- Python: 3.10.11 (this repo's shared interpreter, `mcp-tools/rfq-memory`'s
  target environment)
- Postgres: same local instance already used for `logic_db_2`/
  `file_metadata_db_2`, with a new dedicated database `cognee_memory_db`
  created for this investigation (never mixed with those two).
- Ollama: local, `qwen3:8b` (LLM) and `nomic-embed-text` (embeddings), both
  already pulled/confirmed reachable at `http://localhost:11434`.

## Versions tested, in order, and what happened

| Version | Result |
|---|---|
| `cognee==1.5.4` (initial install) | **Blocked at import/migration time**, regardless of graph/relational provider choice. |
| `cognee==1.5.3` | Same blocker, plus a second, unrelated blocker (see below). |
| `cognee==1.5.2` | Same blocker as 1.5.4. |
| `cognee==1.5.1` | Same blocker (confirmed via file presence + version chain; not re-run standalone). |
| `cognee==1.5.0` | Same blocker (confirmed via file presence). |
| `cognee==1.4.2` | **Migration blocker does NOT occur.** `add()`/`cognify()`/`search()` all execute successfully against real Ollama models. Isolation test then FAILED (see below) — this is the version the rest of this report focuses on. |

### Blocker #1 (1.5.0–1.5.4): Kuzu/ladybug native library crash

Every one of `cognee`'s `alembic/versions/` migration scripts is imported
unconditionally by Alembic's own revision-graph resolution
(`_revision_map`), regardless of which relational/graph provider is
actually configured. One of those files
(`b9274c27a25a_kuzu_11_migration.py`) does a module-level `import kuzu`,
which transitively imports `ladybug` (Kuzu's Python wrapper in this
version), whose native C API library fails to load on this machine:

```
RuntimeError: Could not find lbug C API shared library. Set LBUG_C_API_LIB_PATH
or download a shared lib (e.g. run LBUG_LIB_KIND=shared bash scripts/download_lbug.sh).
```

This happens even when `graph_database_provider` is set to `"postgres"` —
switching graph backends does not avoid it, because the crash happens
during Alembic's migration-file *discovery*, before any provider-specific
code runs. `cognee`'s own suggested fix is a bash script with no confirmed
Windows path.

Confirmed present in 1.5.4, 1.5.3, 1.5.2, 1.5.1, 1.5.0 (same file, same
`import kuzu` line, verified for 1.5.4/1.5.3/1.5.2/1.4.2 by direct read;
1.5.1/1.5.0 confirmed by file presence only, not independently re-run).

**A second, unrelated blocker was also found and fixed along the way**:
the newest available `litellm` release at investigation time uses
`typing.NotRequired`, a Python 3.11+ construct not available on this
machine's Python 3.10 — this crashes on `import cognee` regardless of the
Kuzu issue. Fixed by pinning `litellm>=1.83.7,<1.84` (the floor `cognee`
itself requires, confirmed importable). This fix is real and independent
of the isolation blocker below — it's recorded in
`mcp-tools/rfq-memory/requirements.txt`'s own comment.

### Blocker #2 (1.4.2): cross-dataset isolation failure in `search()`

`cognee==1.4.2` does **not** hit the Kuzu/ladybug crash — relational
migrations, graph-engine setup, `add()`, `cognify()`, and `search()` all
completed successfully, including correct persistence across a process
restart (verified: a fresh Python process, same dataset name, same search
query, same result).

**Isolation test methodology** (per explicit instruction):
1. Two Cognee datasets, `rfq_RFQ-SMOKE-A` and `rfq_RFQ-SMOKE-B`.
2. Dataset A: `add()` one fact — "RFQ-SMOKE-A CBOM line ... CPN
   CPN-ABC-123 ... Texas Instruments" — tagged `node_set=["cbom"]`.
3. Dataset B: `add()` one different fact — "RFQ-SMOKE-B CBOM line ... CPN
   CPN-XYZ-999 ... Analog Devices" — tagged `node_set=["cbom"]`.
4. `cognify(datasets=[A, B])`.
5. `search(datasets=[A], only_context=True)` for a question about A's own
   content — succeeded, returned A's content correctly.
6. `search(datasets=[A], only_context=True)` for "What CPNs and
   manufacturers are mentioned?" — **this is the isolation check**.

**Result**: step 6 returned graph nodes explicitly tagged
`[cbom, line, rfq-smoke-b]`, containing RFQ-SMOKE-B's exact content
verbatim ("CPN CPN-XYZ-999 ... Analog Devices") inside a search scoped to
dataset A only. Full raw output captured; representative excerpt:

```
Node: The RFQ-SMOKE-B CBOM line specifies a top-level... [cbom, line, rfq-smoke-b]
__node_content_start__
The RFQ-SMOKE-B CBOM line specifies a top-level FG component with CPN CPN-XYZ-999.
The manufacturer selected for this CBOM line is Analog Devices.
__node_content_end__
```

**This was tested twice**, per the explicit instruction to rule out a
config gap before concluding it's a real defect:

- **First run**: default fallback (no explicit `graph_database_*`
  credentials set, `ENABLE_BACKEND_ACCESS_CONTROL=false`). Leaked. Cognee's
  own log explained why this path is even more permissive: *"Postgres
  graph credentials are not fully configured; falling back to the
  relational database configuration."*
- **Second run**: explicit `graph_database_host/port/username/password/
  name` all set (same Postgres server, `cognee_memory_db`),
  `graph_dataset_database_handler` auto-corrected by Cognee's own config
  validator to `"postgres_graph"` (confirmed via source read of
  `GraphConfig.fill_derived`). **Leaked identically.** A fresh database
  was used for this run (`DROP DATABASE`/`CREATE DATABASE` between runs)
  to rule out contamination from the first run.

**Root cause (inferred from source, not exhaustively traced)**: Cognee's
Postgres graph adapter (`cognee/infrastructure/databases/graph/
postgres_demo/adapter.py`, a two-table `graph_node`/`graph_edge` design)
appears to store all datasets' nodes/edges without the graph-traversal
step in `search()` applying a dataset-scoping filter — `add()` correctly
tags content by dataset (confirmed: searching dataset A for dataset A's
own unique content works and returns only relevant results when the
question doesn't force cross-dataset graph traversal), but `search()`'s
graph projection/traversal appears to pull from the full shared graph
rather than filtering to the requested dataset's own subgraph.

**Handlers/config active for this test** (for reproducibility):
- `LLM_PROVIDER=ollama`, `LLM_MODEL=ollama/qwen3:8b`,
  `LLM_ENDPOINT=http://localhost:11434/v1`
- `EMBEDDING_PROVIDER=ollama`, `EMBEDDING_MODEL=nomic-embed-text`,
  `EMBEDDING_ENDPOINT=http://localhost:11434/api/embed`
- `db_provider=postgres` (relational), `cognee_memory_db`
- `graph_database_provider=postgres`, `graph_dataset_database_handler=postgres_graph` (auto-resolved), explicit host/port/username/password/name
- Vector store: left at Cognee's file-based default (LanceDB) — **not**
  independently tested for its own isolation behavior, since the graph
  layer alone was sufficient to fail the test.
- `ENABLE_BACKEND_ACCESS_CONTROL=false`, `REQUIRE_AUTHENTICATION=false`
  (per earlier explicit decision — Cognee's own multi-user ACL is not used
  for isolation; dataset-scoping was meant to be the enforced boundary,
  which is exactly what this investigation found does not hold).

## What was NOT done, per explicit instruction

- Did not patch/filter Cognee's search results after the fact to hide the
  leak (would be a fragile, false sense of security, not a fix).
- Did not accept dataset-name scoping alone as sufficient despite this
  result.
- Did not expose Cognee directly to the frontend.
- Did not continue wiring real ingestion/retrieval into production code
  paths beyond what was already built structurally (see below).
- Did not attempt Neo4j as an alternative graph backend (would require new
  infrastructure — deferred pending direction).
- Did not attempt to patch Cognee's own source.

## What IS verified, working, and preserved

Independent of the isolation blocker — all typecheck clean, all unit tests
passing:

- **`mcp-tools/rfq-memory/`** (new backend service): dual-listener network
  topology (LAN JWT-gated chat port 8108, loopback-only internal ingest/
  reset port 8109 — genuinely unreachable off-host, not just
  unauthenticated), reuses `fastmcp-router/auth.py`'s JWT scheme
  unmodified, reuses `fastmcp-router/db.py`'s `get_active_version`/
  Postgres connection helpers unmodified. `versioning.py`'s version-race
  safety (re-validates the active version immediately before any write,
  rejects stale jobs) — **5/5 unit tests passing**
  (`test_versioning.py`), including the exact race-ordering scenario the
  plan called out (old-version job completes after a new-version prune).
- **Ingestion hooks**: wired into `fastapi_router.py`'s `/tool/execute`
  success branch, `upload_server.py`'s `process_file_upload`, and
  `hitl_router.py`'s `submit_resolutions`/`submit_alternates` — all
  fire-and-forget, all fail-open, all carrying explicit
  `rfq_id`+`version`+`source` (never inferred).
- **`manage_backend.py`**: new `rfq_memory_server` SERVICES entry,
  health-checks the LAN port including real Ollama reachability.
- **Daemon** (`apps/daemon/src/rfq-chat/*`): JWT-minting HTTP client,
  deterministic structured-vs-semantic routing heuristic (3/3 unit tests
  passing after fixing a real bug found during test-writing — the initial
  regex matched any 3+ letter word, not just part-number-shaped tokens),
  single-shot Ollama answer-synthesis with no tool-calling capability
  given to the model at all (the actual read-only enforcement mechanism).
  `task-service.ts`'s provider chain updated (scripted-QA → RFQ-chat if
  flagged+scoped → existing `COMING_SOON_MESSAGE` fallback, byte-for-byte
  unchanged for non-RFQ tasks) — gated behind `ACCOMPLISH_ENABLE_RFQ_CHAT`
  (default off).
- **Agent-core**: `TaskConfig.rfqId`/`Task.rfqId`/
  `TaskMessage.citations`/`MessageCitation` type additions, a new SQLite
  migration (`v032-rfq-chat.ts`, `tasks.rfq_id` + `task_messages.citations`
  columns) so both fields actually persist across reload, not just live
  in-memory.
- **Frontend**: `RfqContext` (provides `App.tsx`'s `activeRfqId` to the
  routed chat pages without prop-drilling), RFQ-indicator pills in
  `Home.tsx`/`ExecutionHeader.tsx`, citation-rendering block in
  `MessageBubble` (renders only backend-sourced `message.citations`, never
  LLM free text).

**Nothing above depends on Cognee's search() being correct to compile,
typecheck, or leave existing functionality unaffected** — the feature flag
is off by default, and every new code path fails open toward existing
behavior. The blocker is specifically: real ingestion/retrieval against
Cognee cannot be turned on in good conscience until dataset isolation is
proven safe.

## Candidate paths forward (not implemented, for future direction)

1. **Neo4j as the graph backend.** Cognee's more mature, non-demo graph
   provider. Requires standing up a Neo4j instance — real new
   infrastructure — untested for whether its `search()` correctly scopes
   by dataset where Postgres's does not.
2. **Wait for a newer Cognee release** that both fixes the Windows/Kuzu
   native-library issue (or makes Postgres/Neo4j selection avoid loading
   Kuzu's migration file at all) and doesn't regress dataset isolation
   for the Postgres graph provider specifically.
3. **Reconsider whether Cognee's graph layer is needed at all** for this
   feature's actual requirements — e.g. a simpler per-RFQ-scoped semantic
   search using a plain vector store keyed by dataset (bypassing Cognee's
   graph layer, which is where the leak was isolated to) might satisfy the
   "narrative/decision context" retrieval need in §8 of the plan without
   inheriting this specific defect — untested, would need its own
   isolation verification before being trusted.
4. **File an issue with Cognee** — this appears to be either an
   undocumented limitation of the `postgres_demo`/`postgres` graph
   adapter (their own docs already call it "not production-ready") or a
   real bug; upstream visibility would help confirm which.

No further implementation work should proceed on the Cognee retrieval path
until one of these is chosen.

---

## Resolution (2026-09-10)

**The fix**: `search(node_type=NodeSet, node_name=[tag])` — a single
explicit node-level tag filter — gives real isolation where
`datasets=[...]` alone did not. Discovered by testing Cognee's other
built-in filtering mechanism once the dataset-level approach was confirmed
broken; `node_name` filters on a per-node metadata tag set at `add()` time
(`belongs_to_set`), independent of whichever dataset a node's parent
document was added under.

**Critical constraint discovered alongside the fix**: `node_name`'s
matching operator (`node_name_filter_operator`) defaults to `"OR"`. Passing
two tags in one `node_name` list (e.g. an RFQ-scoping tag AND a
content-type tag together) would **widen** the match to anything with
either tag — reintroducing a leak the moment a second tag is added to the
search-time filter. The fix therefore keeps `node_name` to a single,
RFQ-scoping tag only; content-type narrowing (e.g. "only Gerber-related
context") is applied as a pure Python post-filter on the already
RFQ-scoped results, never merged into the Cognee-side filter.

**Verification performed** (all with a genuine process restart between
write and verify, not just a fresh in-process call):
1. 2 RFQs, same shared dataset, distinct node tags — zero leakage.
2. 3 RFQs, same shared dataset, distinct node tags — zero leakage,
   confirmed after a real process restart.
3. Full integration test against the real `mcp-tools/rfq-memory` service
   code (not a standalone script) — 2 RFQs, separate per-RFQ datasets
   (matching production), multi-tag nodes (`[rfq_tag, "cbom"]`, confirming
   a node carrying a second tag still matches a single-tag `node_name`
   search correctly) — 9/9 checks passed, covering both isolation and
   citation-integrity correctness together.

**What changed in the implementation**:
- `config.py`: added `node_set_tag_for(rfq_id)` (the enforced isolation
  tag) alongside the existing `dataset_name_for(rfq_id)` (kept as a
  secondary/operational scoping boundary — simplifies whole-RFQ pruning
  via `datasets.empty_dataset()` — but no longer the security boundary on
  its own). Added explicit `COGNEE_GRAPH_DB_CONFIG` (host/port/username/
  password/name) — confirmed required; the earlier "second run" test in
  this investigation already used explicit credentials but they were never
  wired into the actual service's own `configure_cognee()`, only into the
  standalone test scripts.
- `ingest.py`: every `cognee.add()` call now tags with
  `node_set=[node_set_tag_for(rfq_id), <content-type tag>]` (both riding
  on the same node — safe at add-time, since the OR-widening risk is
  specific to search-time multi-tag combination, not add-time tagging).
  Each (text, citation) pair is also recorded in a new citation lookup
  table at ingest time (see below).
- **New file `citation_store.py`**: a small Postgres table
  (`rfq_memory_citations`, content-hash → citation JSON, in the same
  dedicated `cognee_memory_db`) recording the real citation for every
  piece of ingested text. Necessary because Cognee's `SearchType.CHUNKS`
  returns the verbatim ingested text but has no concept of *our* source
  records (a real DuckDB `cbom` row, a real Postgres file-telemetry row) —
  so citations are looked up by re-hashing the returned chunk text against
  what was recorded at ingest time, never reconstructed or guessed at
  retrieval time. A chunk whose text doesn't resolve to a stored citation
  is dropped from the response, never shown uncited-but-fabricated.
- `query.py`: switched from `SearchType.GRAPH_COMPLETION` (with
  `only_context=True`, which returns one narrative text blob per query —
  not useful for per-chunk citations) to `SearchType.CHUNKS` (returns a
  list of structured dicts: `text`, `belongs_to_set`, `document_id`, etc.).
  Every result's `belongs_to_set` is re-checked in Python to confirm it
  actually contains the expected RFQ tag — a free defense-in-depth check
  on top of the search-time filter, not a replacement for it.
- `config.py`: `RFQ_MEMORY_ENABLED` flipped back to default-on now that
  the blocker is confirmed resolved in the real production code path.

**Not yet re-verified after this fix** (flagged, not silently assumed):
`datasets.empty_dataset()` (the prune/reset mechanism `versioning.py` uses
for version-rollover and the `/internal/memory/reset` hook) was verified
working *before* this fix, against the old dataset-only isolation scheme —
it should be unaffected (pruning still targets a real dataset, which still
exists as a secondary scoping boundary), but has not been independently
re-tested against the new tagging scheme. Worth a quick confirmation before
relying on it in production.
