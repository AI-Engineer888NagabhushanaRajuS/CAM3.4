/**
 * Deterministic structured-vs-semantic routing heuristic for RFQ chat
 * questions (BuLLMQuote-SRIM). Cheap, regex-based first pass — kept
 * deterministic and fast rather than an LLM-routing call, since the two
 * demo question shapes (bom_qa_lookup_server.py) already show the common
 * cases fit simple patterns. A "structured" question should be answered
 * from DuckDB/Postgres via MCP tools (deterministic values), never from
 * Cognee's semantic retrieval alone — see task-service.ts's own use of
 * this module for how the split is applied.
 */

// Mirrors bom_qa_lookup_server.py's own `_validate_sql_token` shape —
// alphanumeric + hyphen only — for any captured token this module extracts.
const TOKEN_RE = /[\w-]+/;

const STRUCTURED_KEYWORDS = [
  'price', 'cost', 'qty', 'quantity', 'how many', 'supplier', 'lead time',
  'moq', 'stock', 'currency', 'unit of measure', 'final conv', 'final price',
];

// CPN/MPN/RFQ-ID-shaped tokens: this platform's identifiers are
// alphanumeric-with-hyphens AND always contain at least one digit (CPN-4471,
// RFQ-000167, ABC-123) -- unlike ordinary English words, which don't. The
// digit requirement is what actually distinguishes "the user named a part/
// RFQ" from "the user used a 3+ letter word" (an earlier version of this
// regex matched any such word, misrouting narrative questions as
// structured — e.g. "Summarize..." itself matched).
const PART_NUMBER_RE = /\b[A-Za-z0-9]*\d[A-Za-z0-9-]*\b/;

export type RfqChatRouting = 'structured' | 'semantic';

export function routeRfqChatQuestion(question: string): RfqChatRouting {
  const lower = question.toLowerCase();
  const hasStructuredKeyword = STRUCTURED_KEYWORDS.some((kw) => lower.includes(kw));
  const hasPartNumberShape = PART_NUMBER_RE.test(question) && TOKEN_RE.test(question);
  return hasStructuredKeyword || hasPartNumberShape ? 'structured' : 'semantic';
}
