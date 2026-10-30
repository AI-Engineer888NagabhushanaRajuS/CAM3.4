import { useState, useRef, useEffect } from 'react';
import {
  useExternalStoreRuntime,
  AssistantRuntimeProvider,
  ThreadPrimitive,
  type ThreadMessageLike,
  type AppendMessage,
} from '@assistant-ui/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  ChatCircle,
  X,
  Database,
  Rows,
  Brain,
  FileText,
} from '@phosphor-icons/react';
import type { MessageCitation } from '@accomplish_ai/agent-core';

// ── Types ─────────────────────────────────────────────────────────────────────

type RFQMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: MessageCitation[];
};

// ── KT-derived suggestions (from Extras encyclopedias) ────────────────────────
// Vocabulary: A-class (>$1.25), uncosted, MOQ excess, price control split
// (Centum/CONTRACT/CNP), lead time weeks, quote-age buckets (Enc. 1-4).

const RFQ_SUGGESTIONS = [
  { title: 'A-class spend',    prompt: 'Which A-class parts have the highest spend percentage in this RFQ?' },
  { title: 'Uncosted parts',   prompt: 'Which parts have no pricing (uncosted) in this RFQ?' },
  { title: 'Lead time risks',  prompt: 'Which parts have lead times over 20 weeks?' },
  { title: 'MOQ excess cost',  prompt: 'What is the total excess inventory cost driven by MOQ rounding?' },
  { title: 'Price control',    prompt: 'What is the split between Centum, CONTRACT, and CNP pricing?' },
  { title: 'Stale quotes',     prompt: 'Are there any supplier quotes older than 2 months in this RFQ?' },
];

const SOURCE_ICON: Record<MessageCitation['sourceType'], React.ElementType> = {
  cbom_row:         Database,
  bom_row:          Rows,
  cognee_memory:    Brain,
  gerber_checklist: FileText,
  excel_export:     FileText,
  file_telemetry:   FileText,
};

// ── Runtime hook ──────────────────────────────────────────────────────────────

function useRFQChatRuntime(rfqId: string) {
  const [isRunning, setIsRunning] = useState(false);
  const [messages, setMessages] = useState<RFQMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        `Hi! I can answer **read-only** questions about **RFQ ${rfqId}**.\n\n` +
        `Ask about A-class spend, uncosted parts, lead time risks, MOQ excess, ` +
        `price control split, or stale quotes. I can't approve HITL gates or change any data.`,
    },
  ]);

  // Keep a stable ref so onNew can read current messages without stale closure.
  const messagesRef = useRef(messages);
  useEffect(() => { messagesRef.current = messages; }, [messages]);

  const onNew = async (msg: AppendMessage) => {
    if (msg.content[0]?.type !== 'text') return;
    const text = msg.content[0].text;

    const userMsg: RFQMessage = { id: crypto.randomUUID(), role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setIsRunning(true);

    try {
      const resp = await fetch(`/api/rfq/${rfqId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [...messagesRef.current, userMsg].map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
      });

      const data = (await resp.json()) as {
        message?: string;
        error?: string;
        citations?: MessageCitation[];
      };

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: data.message ?? data.error ?? 'No response.',
          citations: data.citations?.length ? data.citations : undefined,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: "Couldn't reach the chat service. Please try again.",
        },
      ]);
    } finally {
      setIsRunning(false);
    }
  };

  const runtime = useExternalStoreRuntime<RFQMessage>({
    isRunning,
    messages,
    convertMessage: (m): ThreadMessageLike => ({
      id: m.id,
      role: m.role,
      content: [{ type: 'text', text: m.content }],
    }),
    onNew,
    suggestions: RFQ_SUGGESTIONS.map((s) => ({ prompt: s.prompt, title: s.title })),
  });

  return { runtime, messages, isRunning };
}

// ── Citation chip ─────────────────────────────────────────────────────────────

function CitationChip({ citation }: { citation: MessageCitation }) {
  const Icon = SOURCE_ICON[citation.sourceType] ?? FileText;
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/60 px-2 py-0.5 text-[10px] text-muted-foreground">
      <Icon className="h-2.5 w-2.5 shrink-0" />
      {citation.label}
    </span>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: RFQMessage }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[84%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        <div
          className={`rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
            isUser
              ? 'rounded-br-sm bg-primary text-primary-foreground'
              : 'rounded-bl-sm bg-muted text-foreground'
          }`}
        >
          {isUser ? (
            msg.content
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // Keep tables readable inside the narrow bubble
                table: ({ children }) => (
                  <div className="overflow-x-auto">
                    <table className="text-xs border-collapse">{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th className="border border-border px-2 py-1 bg-muted font-semibold">{children}</th>
                ),
                td: ({ children }) => (
                  <td className="border border-border px-2 py-1">{children}</td>
                ),
                // Tighter spacing for lists
                ul: ({ children }) => <ul className="list-disc pl-4 space-y-0.5">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-4 space-y-0.5">{children}</ol>,
                p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
                code: ({ children }) => (
                  <code className="rounded bg-background/60 px-1 py-0.5 font-mono text-[11px]">{children}</code>
                ),
              }}
            >
              {msg.content}
            </ReactMarkdown>
          )}
        </div>
        {msg.citations && msg.citations.length > 0 && (
          <div className="flex flex-wrap gap-1 px-1">
            {msg.citations.map((c, i) => (
              <CitationChip key={i} citation={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Pane inner (must be inside AssistantRuntimeProvider) ──────────────────────

interface PaneInnerProps {
  rfqId: string;
  messages: RFQMessage[];
  isRunning: boolean;
  runtime: ReturnType<typeof useExternalStoreRuntime<RFQMessage>>;
  onClose: () => void;
}

function PaneInner({ rfqId, messages, isRunning, runtime, onClose }: PaneInnerProps) {
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isRunning]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isRunning) return;
    setInput('');
    void runtime.thread.append({
      parentId: null,
      role: 'user',
      content: [{ type: 'text', text }],
    });
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 flex h-[580px] w-[400px] flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-2xl">

      {/* ── Header ── */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-card/60 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <ChatCircle className="h-4 w-4 text-primary" weight="fill" />
          <span className="text-sm font-semibold text-foreground">RFQ Assistant</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
            {rfqId}
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Close chat"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* ── Messages ── */}
      <ScrollArea className="flex-1 px-4 py-3">
        <div className="space-y-3">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          {isRunning && (
            <div className="flex justify-start">
              <div className="rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2.5">
                <span className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* ── KT-derived suggestion chips (always visible) ── */}
      <div className="flex shrink-0 gap-1.5 overflow-x-auto border-t border-border px-4 py-2 scrollbar-none">
        {RFQ_SUGGESTIONS.map((s) => (
          <ThreadPrimitive.Suggestion
            key={s.title}
            prompt={s.prompt}
            send
            asChild
          >
            <button
              disabled={isRunning}
              className="shrink-0 rounded-full border border-border bg-muted/60 px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
            >
              {s.title}
            </button>
          </ThreadPrimitive.Suggestion>
        ))}
      </div>

      {/* ── Composer ── */}
      <div className="flex shrink-0 gap-2 border-t border-border px-4 py-3">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this RFQ…"
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          disabled={isRunning}
          className="flex-1 rounded-xl text-sm"
        />
        <Button
          onClick={handleSend}
          disabled={isRunning || !input.trim()}
          size="sm"
          className="rounded-xl"
        >
          Send
        </Button>
      </div>
    </div>
  );
}

// ── Public exports ─────────────────────────────────────────────────────────────

interface RFQChatPaneProps {
  rfqId: string;
  isOpen: boolean;
  onClose: () => void;
}

export function RFQChatPane({ rfqId, isOpen, onClose }: RFQChatPaneProps) {
  const { runtime, messages, isRunning } = useRFQChatRuntime(rfqId);

  if (!isOpen) return null;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <PaneInner
        rfqId={rfqId}
        messages={messages}
        isRunning={isRunning}
        runtime={runtime}
        onClose={onClose}
      />
    </AssistantRuntimeProvider>
  );
}

/** Floating trigger button shown in ExecutionHeader when the pane is closed. */
export function RFQChatButton({ rfqId, onClick }: { rfqId: string; onClick: () => void }) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onClick}
      className="gap-1.5"
      title={`Open RFQ assistant for ${rfqId}`}
    >
      <ChatCircle className="h-4 w-4" weight="fill" />
      Ask Assistant
    </Button>
  );
}
