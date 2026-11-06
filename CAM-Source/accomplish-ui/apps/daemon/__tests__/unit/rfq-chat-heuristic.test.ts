import { describe, it, expect } from 'vitest';
import { routeRfqChatQuestion } from '../../src/rfq-chat/rfq-chat-heuristic.js';

describe('routeRfqChatQuestion', () => {
  it('routes price/qty/supplier questions as structured', () => {
    expect(routeRfqChatQuestion("What's the final conv price of MPN ABC-123?")).toBe('structured');
    expect(routeRfqChatQuestion('How many FGs does RFQ-000167 contain?')).toBe('structured');
    expect(routeRfqChatQuestion('Which supplier was selected for CPN-4471?')).toBe('structured');
    expect(routeRfqChatQuestion('What is the lead time for this part?')).toBe('structured');
  });

  it('routes open-ended/narrative questions as semantic', () => {
    expect(routeRfqChatQuestion('Why was this alternate chosen?')).toBe('semantic');
    expect(routeRfqChatQuestion('Summarize what changed between the input and final CBOM')).toBe('semantic');
    expect(routeRfqChatQuestion('What was flagged in the Gerber checklist?')).toBe('semantic');
  });

  it('routes bare part-number-shaped questions as structured', () => {
    expect(routeRfqChatQuestion('Tell me about CPN-ABC-123')).toBe('structured');
  });
});
