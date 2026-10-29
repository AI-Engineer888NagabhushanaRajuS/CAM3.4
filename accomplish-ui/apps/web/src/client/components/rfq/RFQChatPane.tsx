import { useState, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ChatCircle, X } from '@phosphor-icons/react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface RFQChatPaneProps {
  rfqId: string;
  isOpen: boolean;
  onClose: () => void;
}

const QUICK_QUESTIONS = [
  { label: 'Total cost summary', text: 'What is the total cost breakdown by volume tier?' },
  { label: 'Missing parts', text: 'Which parts are missing suppliers or pricing?' },
  { label: 'Workflow status', text: "What is the current status of this RFQ's workflow?" },
];

export function RFQChatPane({ rfqId, isOpen, onClose }: RFQChatPaneProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: `Hi! I can answer read-only questions about RFQ ${rfqId}. What would you like to know?`,
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const sendMessage = async (text: string = input) => {
    const trimmed = text.trim();
    if (!trimmed || isLoading) return;
    setInput('');

    const next: Message[] = [...messages, { role: 'user', content: trimmed }];
    setMessages(next);
    setIsLoading(true);

    try {
      const resp = await fetch(`/api/rfq/${rfqId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: next.map(m => ({ role: m.role, content: m.content })),
        }),
      });
      const data = (await resp.json()) as { message?: string; error?: string };
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: data.message ?? data.error ?? 'No response.' },
      ]);
    } catch {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: "Couldn't reach the chat service. Please try again." },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex h-[540px] w-96 flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-2xl">
      {/* Header */}
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

      {/* Messages */}
      <ScrollArea className="flex-1 px-4 py-3">
        <div className="space-y-3">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'rounded-br-sm bg-primary text-primary-foreground'
                    : 'rounded-bl-sm bg-muted text-foreground'
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start">
              <div className="rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2.5">
                <span className="flex gap-1">
                  {[0, 1, 2].map(i => (
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

      {/* Quick-question chips */}
      <div className="flex shrink-0 gap-1.5 overflow-x-auto border-t border-border px-4 py-2">
        {QUICK_QUESTIONS.map(q => (
          <button
            key={q.label}
            onClick={() => sendMessage(q.text)}
            disabled={isLoading}
            className="shrink-0 rounded-full border border-border bg-muted/60 px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            {q.label}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex shrink-0 gap-2 border-t border-border px-4 py-3">
        <Input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask about this RFQ…"
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
          disabled={isLoading}
          className="flex-1 rounded-xl text-sm"
        />
        <Button
          onClick={() => sendMessage()}
          disabled={isLoading || !input.trim()}
          size="sm"
          className="rounded-xl"
        >
          Send
        </Button>
      </div>
    </div>
  );
}

/** Floating trigger button shown when the pane is closed. */
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
