# SPEC-008 — Chat via rfq-memory + Shadow-Run Parity

## Branch
`feat/spec-008-chat-memory-shadowrun`

## Why
Two architectural gaps from gap audit:

**Gap 1 — Chat API wrong backend:**
SPEC-006 built `POST /rfq/{rfq_id}/chat` in fastapi_router.py calling Ollama directly.
The rfq-memory service (ports 8108/8109, Cognee-backed) already exists and already has
RFQ-scoped memory with ingested context. The daemon already has `rfq-chat/rfq-chat-client.ts`
that was wired to the memory service. SPEC-006 bypassed all of this and created a duplicate path.
Fix: route chat through rfq-memory service. fastapi_router becomes a thin proxy.

**Gap 2 — Shadow-run parity test missing:**
Architecture Diagram 6, Step 10 explicitly says:
"Run DAQ and Temporal on same RFQ and compare outputs"
This validation harness was never built.

## Scope (files to change)

### 1. Fix chat endpoint — `fastapi-router/fastapi_router.py`
Replace the Ollama-direct `POST /rfq/{rfq_id}/chat` implementation with a proxy to rfq-memory:
```python
RFQ_MEMORY_URL = os.environ.get("RFQ_MEMORY_URL", "http://localhost:8108")

@app.post("/rfq/{rfq_id}/chat")
async def rfq_chat(rfq_id: str, body: RFQChatRequest):
    if not RFQ_ID_RE.match(rfq_id):
        raise HTTPException(400, "invalid rfq_id")
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                f"{RFQ_MEMORY_URL}/chat",
                json={"rfq_id": rfq_id, "messages": body.messages},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise HTTPException(503, {"error": "rfq-memory service unavailable"})
```

### 2. Update daemon proxy — `accomplish-ui/apps/daemon/src/browser-api-server.ts`
The existing proxy for `/api/rfq/:rfqId/chat` targets `CAM_FASTAPI_ROUTER_URL`.
Keep it as-is (daemon → fastapi_router → rfq-memory). Add env var `RFQ_MEMORY_URL` to
docker-compose.yml for the fastapi-router service so it knows where rfq-memory lives.

### 3. Remove Ollama-direct helper — `fastapi-router/fastapi_router.py`
Remove `_build_rfq_context()` helper and the Ollama prompt-assembly block.
Delete the dead import of any Ollama-specific httpx calls.

### 4. Shadow-run parity harness — `testing/test_shadow_run_parity.py`
New test file. Compares Temporal workflow output vs DAQ (direct tool execution) output
for the same rfq_id:
- Fixture: use a known test RFQ (CE-TEST-SHADOW-001) with deterministic outputs
- Run 1: call upload_server's temporal path via `start_rfq_workflow`
- Run 2: call the same tool sequence directly via fastapi_router POST /tool/execute
- Assert: both paths produce same final_cost, same part_count, same status
- If services unavailable: pytest.skip (integration test, not unit)

### 5. docker-compose.yml
Add `RFQ_MEMORY_URL=http://rfq-memory-server:8108` to `fastapi-router` service environment.

## Tests
- Update `testing/test_rfq_chat.py`: mock target is now rfq-memory endpoint, not Ollama
- New `testing/test_shadow_run_parity.py` (integration, skip if services down)

## Acceptance criteria
- `POST /rfq/{rfq_id}/chat` proxies to rfq-memory, no Ollama calls
- `_build_rfq_context` removed (was Ollama-specific)
- `test_shadow_run_parity.py` exists and passes when services available
- `test_rfq_chat.py` updated to mock rfq-memory not Ollama
