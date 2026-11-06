# SPEC-006: RFQ Assistant Chat API + UI Pane

**Status:** COMPLETED  
**Branch:** `feat/spec-006-rfq-chat-pane`  
**Commit target:** `feat: add read-only RFQ assistant chat API and UI pane`  
**Depends on:** SPEC-004, SPEC-005

## Context

CAM 3.3 has no chat interface. Users navigate static pages in accomplish-ui.
The CAM 3.4 proposal adds an "assistant chat pane" where users can ask natural-language
questions about an active RFQ: status, cost breakdown, which parts are missing, etc.

**Scope (3.4):** READ-ONLY. The chat assistant can answer questions about RFQ data
but cannot trigger new RFQ runs, approve HITL, or mutate any data.

**What exists already:**
- `fastmcp-router/` has `rfq_memory_client.py` — memory/context retrieval
- `accomplish-ui/apps/web/src/client/components/rfq/` — RFQ-related UI components
- `accomplish-ui/apps/web/src/client/components/` has existing components to follow for style
- The daemon at `apps/daemon/src/rfq-chat/` (from the folder tree) suggests a chat service existed
- `mcp-tools/rfq-memory/` has a vector memory service for RFQ context

**API layer:** The chat API must call Ollama (already running locally) via the existing
Bifrost/OpenRouter pattern, with RFQ data injected as context.

## What to Build

### 1. Chat API endpoint in `fastapi_router.py`

Add a new route for chat that is completely separate from the tool execution path:

```python
from typing import List
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    rfq_id: str
    messages: List[ChatMessage]
    
class ChatResponse(BaseModel):
    message: str
    sources: List[dict]  # which RFQ data was referenced

@app.post("/rfq/{rfq_id}/chat")
async def rfq_chat(rfq_id: str, request: ChatRequest):
    """Read-only RFQ assistant. Can answer questions about this RFQ's data.
    Cannot trigger actions, approve HITL, or modify any data.
    """
    # Validate rfq_id
    rfq_id = _validate_sql_identifier(rfq_id, "rfq_id")
    
    # 1. Fetch RFQ context from DuckDB (summary data only)
    context = _build_rfq_context(rfq_id)
    
    # 2. Get Temporal workflow status (if enabled)
    if USE_TEMPORAL:
        workflow_status = _get_temporal_status(rfq_id)
        context["workflow_status"] = workflow_status
    
    # 3. Build system prompt with RFQ context
    system_prompt = _build_rfq_system_prompt(rfq_id, context)
    
    # 4. Call Ollama (via existing pattern)
    response = await _call_llm(system_prompt, request.messages)
    
    return ChatResponse(message=response, sources=context.get("sources", []))


def _build_rfq_context(rfq_id: str) -> dict:
    """Pull key RFQ facts from DuckDB for the chat context."""
    import duckdb
    # Use the existing database.py connection pattern from reporting module
    # Query summary data: total cost, part count, missing parts, HITL status
    context = {}
    try:
        con = duckdb.connect(...)  # same connection as reporting module
        
        # Summary: total cost per volume
        summary = con.execute(
            "SELECT * FROM summary_report WHERE rfq_id = ? LIMIT 1", [rfq_id]
        ).fetchdf()
        if not summary.empty:
            context["summary"] = summary.to_dict(orient="records")[0]
        
        # Missing parts
        missing = con.execute(
            "SELECT COUNT(*) as count FROM missing_notes_report WHERE rfq_id = ?", [rfq_id]
        ).fetchone()
        context["missing_parts_count"] = missing[0] if missing else 0
        
        # Part count
        part_count = con.execute(
            "SELECT COUNT(*) as count FROM cbom WHERE rfq_id = ? AND is_assembly = FALSE", [rfq_id]
        ).fetchone()
        context["total_parts"] = part_count[0] if part_count else 0
        
        context["sources"] = ["summary_report", "missing_notes_report", "cbom"]
    except Exception as e:
        context["error"] = str(e)
    return context


async def _call_llm(system_prompt: str, messages: List[ChatMessage]) -> str:
    """Call Ollama (or Bifrost) with the system prompt + conversation."""
    OLLAMA_BASE = "http://localhost:11434"  # local Ollama
    payload = {
        "model": "llama3.1:8b",  # or read from config
        "system": system_prompt,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": False,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["message"]["content"]
```

### 2. System prompt template for the RFQ assistant

```python
def _build_rfq_system_prompt(rfq_id: str, context: dict) -> str:
    return f"""You are a read-only RFQ assistant for Centum Electronics.
You have access to the following data for RFQ {rfq_id}:

{json.dumps(context, indent=2)}

Rules you must follow:
- Answer ONLY from the data provided above
- You CANNOT trigger new RFQ runs, approve any HITL gates, or change any data
- If asked to do something that would change data, say: "I can only read data. 
  Please use the main RFQ interface to make changes."
- If data is missing or the RFQ is still processing, say so clearly
- For cost questions: always specify which volume tier (Proto / VL-1 / VL-2 etc.)
- Currency: all costs are in USD unless specified

Example questions you can answer:
- "What is the total cost for VL-1 volume?"
- "Which parts are missing suppliers?"
- "What's the status of the current RFQ run?"
- "How many A-class parts does this RFQ have?"
"""
```

### 3. UI Chat Pane in accomplish-ui

The UI work must match the existing accomplish-ui style (Tailwind + shadcn/ui).

#### Component: `apps/web/src/client/components/rfq/RFQChatPane.tsx`

```tsx
import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface RFQChatPaneProps {
  rfqId: string;
  isOpen: boolean;
  onClose: () => void;
}

export function RFQChatPane({ rfqId, isOpen, onClose }: RFQChatPaneProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: `Hi! I can answer read-only questions about RFQ ${rfqId}. 
                What would you like to know?`,
      timestamp: new Date(),
    }
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const sendMessage = async () => {
    if (!input.trim() || isLoading) return;
    
    const userMessage: Message = { role: "user", content: input, timestamp: new Date() };
    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);
    
    try {
      const resp = await fetch(`/api/rfq/${rfqId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rfq_id: rfqId,
          messages: [...messages, userMessage].map(m => ({
            role: m.role,
            content: m.content,
          })),
        }),
      });
      const data = await resp.json();
      setMessages(prev => [...prev, {
        role: "assistant",
        content: data.message,
        timestamp: new Date(),
      }]);
    } catch (e) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: "Sorry, I couldn't reach the chat service. Please try again.",
        timestamp: new Date(),
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed bottom-4 right-4 w-96 h-[500px] bg-background border rounded-xl shadow-2xl flex flex-col z-50">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <span className="font-semibold text-sm">RFQ Assistant</span>
          <span className="text-xs text-muted-foreground">· {rfqId}</span>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>✕</Button>
      </div>
      
      {/* Messages */}
      <ScrollArea className="flex-1 p-3" ref={scrollRef}>
        <div className="space-y-3">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                msg.role === "user" 
                  ? "bg-primary text-primary-foreground" 
                  : "bg-muted"
              }`}>
                {msg.content}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-muted rounded-lg px-3 py-2 text-sm">
                <span className="animate-pulse">Thinking...</span>
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
      
      {/* Input */}
      <div className="p-3 border-t flex gap-2">
        <Input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask about this RFQ..."
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          disabled={isLoading}
          className="flex-1"
        />
        <Button onClick={sendMessage} disabled={isLoading || !input.trim()} size="sm">
          Send
        </Button>
      </div>
    </div>
  );
}
```

#### Wire into existing RFQ page

Find the RFQ execution or history page in `apps/web/src/client/pages/execution/` or similar.
Add a chat button that opens `RFQChatPane`:

```tsx
// In the RFQ detail page:
import { RFQChatPane } from "@/components/rfq/RFQChatPane";
const [chatOpen, setChatOpen] = useState(false);

// Add chat button in the header area:
<Button variant="outline" size="sm" onClick={() => setChatOpen(true)}>
  💬 Ask Assistant
</Button>
<RFQChatPane rfqId={activeRfqId} isOpen={chatOpen} onClose={() => setChatOpen(false)} />
```

### 4. Proxy route in daemon (apps/daemon)

The accomplish-ui daemon (`apps/daemon/src/`) proxies API calls to the Python backend.
Add a proxy route for `/api/rfq/:rfqId/chat` → `http://localhost:5000/rfq/:rfqId/chat`:

```typescript
// In apps/daemon/src/ (find the existing proxy setup):
app.post("/api/rfq/:rfqId/chat", async (req, res) => {
  const { rfqId } = req.params;
  const backendUrl = `http://localhost:5000/rfq/${rfqId}/chat`;
  const response = await fetch(backendUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req.body),
  });
  const data = await response.json();
  res.json(data);
});
```

## Files to Create/Modify

- `fastmcp-router/fastapi_router.py` (add /rfq/{rfq_id}/chat endpoint)
- `accomplish-ui/apps/web/src/client/components/rfq/RFQChatPane.tsx` (new)
- `accomplish-ui/apps/web/src/client/pages/execution/` (add chat button)
- `accomplish-ui/apps/daemon/src/rfq-chat/` (add proxy route, may already exist)
- `tests/test_rfq_chat.py` (new)

## Acceptance Criteria

1. `POST /rfq/TEST-RFQ-001/chat` returns a JSON response with `message` field (even with empty DB)
2. `RFQChatPane` renders in accomplish-ui without TypeScript errors
3. Sending "What is the total cost?" in the chat pane returns a real response from Ollama
4. "Please approve this HITL" triggers the "I can only read data" guard message
5. Chat pane is accessible via a button on the RFQ detail/execution page
6. All files committed to `feat/spec-006-rfq-chat-pane` branch

## Design Constraints

- Match accomplish-ui style: Tailwind CSS + shadcn/ui components ONLY
- No new UI libraries
- Chat pane must be a floating panel (not a full page), like a customer support chat widget
- Dark mode must work (use `bg-background`, `text-foreground` CSS vars, not hardcoded colors)
- Read-only guard is enforced server-side (even if frontend shows a "mutation" message,
  the backend endpoint must reject it)

## Suggested Quick Questions (pre-fill buttons)

Add 3 quick-question buttons above the input:
- "📊 Total cost summary"
- "⚠️ Missing parts"  
- "📈 Workflow status"

These fill the input with the question text when clicked.
