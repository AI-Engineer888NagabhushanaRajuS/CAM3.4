# SPEC-010 — assistant-ui Runtime + Domain-Aware Chat Pane

## Branch
`feat/spec-010-assistant-ui-chat`

## Why
SPEC-006's RFQChatPane is hand-rolled: manual useState for messages/loading,
raw text rendering, generic hardcoded quick-question chips. KT encyclopedias
(Extras/) document exactly what a Centum RFQ specialist needs to query:
A-class spend, uncosted parts, MOQ excess cost, price control split, stale quotes,
lead time risks. assistant-ui's useExternalStoreRuntime gives proper state + 
suggestion primitives; react-markdown (already installed) enables rich answers.

## Scope

### 1. `accomplish-ui/apps/web/package.json`
Add `"@assistant-ui/react": "^0.7.0"` (or latest stable).

### 2. Rewrite `accomplish-ui/apps/web/src/client/components/rfq/RFQChatPane.tsx`
- Extract `useRFQChatRuntime(rfqId)` hook:
  - State: `messages: RFQMessage[]` (with optional `citations: MessageCitation[]`),
    `isRunning: boolean`
  - `onNew(msg: AppendMessage)` calls `/api/rfq/${rfqId}/chat`, appends user + assistant msgs
  - Pass KT-derived `suggestions` to `useExternalStoreRuntime`
- Wrap pane body in `<AssistantRuntimeProvider runtime={runtime}>`
- Message bubbles: render content via `react-markdown` + `remark-gfm` (already installed)
- Citation chips: when `citations` present, show small pills below assistant msg
  - Label from `citation.label`; icon from `citation.sourceType`
- Suggestions: `<ThreadPrimitive.Suggestion prompt={s.prompt} send>` for each KT chip
  - Always visible strip (not only on empty thread)
- Input: keep custom Input + Button, call `runtime.thread.append()` on send
- Welcome message: domain-aware ("Ask about A-class parts, uncosted lines,
  lead time risks, MOQ excess, price control split...")

### 3. KT-derived suggestion list (Encyclopedia knowledge → chips)
| Chip label | Prompt |
|---|---|
| A-class spend | Which A-class parts have the highest spend % in this RFQ? |
| Uncosted parts | Which parts have no pricing (uncosted) in this RFQ? |
| Lead time risks | Which parts have lead times over 20 weeks? |
| MOQ excess cost | What is the total excess inventory cost from MOQ rounding? |
| Price control | What is the split between Centum, CONTRACT, and CNP pricing? |
| Stale quotes | Are there quotes older than 2 months in this RFQ? |

### 4. Citation chip rendering
`MessageCitation.sourceType` → icon mapping:
- `cbom_row` → database icon
- `bom_row` → list icon
- `cognee_memory` → brain icon (or just books)
- others → default file icon

## Tests
- `testing/test_assistant_ui_chat.py` is not relevant (TypeScript component)
- Update `testing/test_rfq_chat.py` to assert 410 still returns (backend unchanged)

## Acceptance criteria
- `@assistant-ui/react` in package.json
- `useRFQChatRuntime` extracts state into assistant-ui runtime
- 6 KT-derived suggestion chips rendered via `ThreadPrimitive.Suggestion`
- Assistant messages render markdown (bold, lists, tables)
- Citation chips appear below messages when `citations` array non-empty
- `RFQChatButton` export unchanged (ExecutionHeader.tsx needs no edit)
