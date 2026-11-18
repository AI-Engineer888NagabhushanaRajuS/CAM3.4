import type { MessageCitation } from '@accomplish_ai/agent-core';
import type { ChatScope, RfqOption, UiDirective } from './rfq-chat-contract.js';

export type ChatMessage = { role: 'system' | 'user' | 'assistant'; content: string };

/** A language model. complete() returns null when the model cannot be reached (or the caller aborted); it never throws. */
export interface ChatModel {
  label: string;
  complete(messages: ChatMessage[], signal?: AbortSignal): Promise<{ text: string; model: string } | null>;
  /** Tool calling (the agent): one model turn. `messages` are in the provider's own shape; `assistant` is the turn to append back. */
  callTools?(messages: unknown[], tools: unknown[], signal?: AbortSignal): Promise<ToolTurn | null>;
}

/** One model turn that may ask for tools. `toolCalls` empty = the final answer in `text`. */
export interface ToolTurn {
  text: string;
  toolCalls: Array<{ id: string; name: string; args: Record<string, unknown> }>;
  model: string;
  assistant: unknown;
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

/** One RFQ as the list shows it. hasExport is optional so a list source that cannot tell leaves it out (read as false). */
export type RfqSummary = Omit<RfqOption, 'hasExport'> & { hasExport?: boolean };

/** What the conversation service returns; the HTTP route sends it as the ChatResponse (rfq-chat-contract.ts). */
export interface ChatReply {
  rfq_id: string | null;
  message: string;
  citations: GroundedAnswer['citations'];
  model: string | null;
  scope?: ChatScope;
  ui?: UiDirective;
}
