import type { ChatScope } from './rfq-chat-contract.js';

const MAX_IDS = 200; // far above the 25 an answer may span: enough to say "too many", too few to be a cost attack

/** The scope the browser sent, or undefined when it is missing or malformed (the route then falls back to the URL's RFQ). */
export function parseScope(value: unknown): ChatScope | undefined {
  if (!value || typeof value !== 'object') {
    return undefined;
  }
  const s = value as { mode?: unknown; rfqIds?: unknown };
  if (s.mode === 'none' || s.mode === 'all') {
    return { mode: s.mode };
  }
  if (s.mode === 'rfqs' && Array.isArray(s.rfqIds)) {
    return { mode: 'rfqs', rfqIds: s.rfqIds.filter((id): id is string => typeof id === 'string' && id.length > 0).slice(0, MAX_IDS) };
  }
  return undefined;
}
