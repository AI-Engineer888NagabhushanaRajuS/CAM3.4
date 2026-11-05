import type { MessageCitation } from '@accomplish_ai/agent-core';

export type ChatMessage = { role: 'system' | 'user' | 'assistant'; content: string };

/** A language model. complete() returns null when the model cannot be reached (or the caller aborted); it never throws. */
export interface ChatModel {
  label: string;
  complete(messages: ChatMessage[], signal?: AbortSignal): Promise<{ text: string; model: string } | null>;
}

export interface Turn {
  role: string;
  content: string;
}

export interface GroundedAnswer {
  message: string;
  citations: MessageCitation[];
  /** Always true: every reply is built from the RFQ's results or says it cannot. */
  grounded: true;
  /** Which model phrased it; null when no model was needed (a refusal, a greeting, an evidence listing). */
  model: string | null;
}
