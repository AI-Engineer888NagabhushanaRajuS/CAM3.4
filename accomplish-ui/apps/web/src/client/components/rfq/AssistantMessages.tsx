import { memo, useEffect, useRef, type ElementType } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Brain, ChatCircleDots, Database, FileText, Paperclip, Rows, ShieldCheck } from '@phosphor-icons/react';
import type { MessageCitation } from '@accomplish_ai/agent-core';
import { cn } from '@/lib/utils';
import { MessageCopyButton } from '@/components/execution/MessageCopyButton';
import { markdownComponents, proseClasses } from '@/components/execution/message-markdown-config';
import { Directive, type DirectiveActions } from './AssistantDirectives';
import type { ChatMsg } from './useAssistantChat';

// Vocabulary from the KT encyclopedias: A-class (> $1.25), uncosted, MOQ excess, price control (Centum/CONTRACT/CNP), lead time.
export const RFQ_SUGGESTIONS = [
  { title: 'RFQ status', prompt: 'What is the status of this RFQ, and is anything waiting for my review?' },
  { title: 'A-class spend', prompt: 'Which A-class parts have the highest spend percentage in this RFQ?' },
  { title: 'Uncosted parts', prompt: 'Which parts have no pricing (uncosted) in this RFQ?' },
  { title: 'Lead time risks', prompt: 'Which parts have lead times over 20 weeks?' },
  { title: 'MOQ excess cost', prompt: 'What is the total excess inventory cost driven by MOQ rounding?' },
  { title: 'Price control', prompt: 'What is the split between Centum, CONTRACT, and CNP pricing?' },
];

const GENERAL_SUGGESTIONS = [
  { title: 'How to use CAM 3.4', prompt: 'How do I use this tool?' },
  { title: 'My RFQs', prompt: 'Which RFQs do I have?' },
];

const SOURCE_ICON: Partial<Record<string, ElementType>> = {
  cbom_row: Database,
  bom_row: Rows,
  cognee_memory: Brain,
  attachment: Paperclip,
};

function Citations({ citations }: { citations: MessageCitation[] }) {
  const unique = [...new Map(citations.map((c) => [c.label, c])).values()];
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Sources">
      {unique.map((c) => {
        const Icon = SOURCE_ICON[c.sourceType] ?? FileText;
        return (
          <li key={c.label} title={c.label} className="inline-flex max-w-[240px] items-center gap-1 rounded-full border border-border bg-muted/60 px-2 py-0.5 text-[11px] text-foreground/80">
            <Icon className="h-2.5 w-2.5 shrink-0" />
            <span className="truncate">{c.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

const Bubble = memo(function Bubble({ msg, actions, busy }: { msg: ChatMsg; actions: DirectiveActions; busy: boolean }) {
  const isUser = msg.role === 'user';
  const sources = msg.citations?.length ?? 0;
  return (
    <div className={cn('group flex flex-col', isUser ? 'items-end' : 'items-start')} data-testid={isUser ? 'user-message' : 'assistant-message'}>
      <div
        className={cn(
          'relative max-w-[85%] rounded-2xl px-4 py-3 transition-all duration-150',
          msg.ui?.type === 'confirm_action' && 'w-full',
          isUser ? 'bg-primary text-primary-foreground' : msg.failed ? 'border border-destructive/30 bg-destructive/5' : 'border border-border bg-card',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words text-sm text-primary-foreground">{msg.content}</p>
        ) : (
          <div className={proseClasses}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{msg.content}</ReactMarkdown>
          </div>
        )}
        {!isUser && <Directive msg={msg} actions={actions} busy={busy} />}
        <p className={cn('mt-1.5 text-xs', isUser ? 'text-primary-foreground/70' : 'text-muted-foreground')}>
          {new Date(msg.at).toLocaleTimeString()}
        </p>
        <MessageCopyButton content={msg.content} isUser={isUser} />
      </div>
      {!isUser && sources > 0 && (
        <div className="mt-1.5 flex max-w-[85%] flex-col gap-1.5 px-1">
          <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <ShieldCheck className="h-3 w-3 text-primary" weight="fill" />
            Every figure checked against {sources === 1 ? 'the cited row' : `${sources} cited rows`}
            {msg.model ? ` · ${msg.model}` : ''}
          </p>
          <Citations citations={msg.citations ?? []} />
        </div>
      )}
    </div>
  );
});

interface AssistantMessagesProps {
  messages: ChatMsg[];
  running: boolean;
  /** The one RFQ in scope, when exactly one. */
  rfqId: string | null;
  onPick: (prompt: string) => void;
  actions: DirectiveActions;
}

export function AssistantMessages({ messages, running, rfqId, onPick, actions }: AssistantMessagesProps) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const calm = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
    end.current?.scrollIntoView?.({ behavior: calm ? 'auto' : 'smooth', block: 'end' });
  }, [messages.length, running]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5" data-testid="assistant-messages">
      <div className="mx-auto max-w-3xl space-y-3" role="log" aria-live="polite" aria-relevant="additions">
        {messages.length === 0 && (
          <div className="flex flex-col items-center gap-5 py-8 text-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
              <ChatCircleDots className="h-5 w-5" weight="fill" />
            </span>
            <div className="space-y-1">
              <h3 className="text-base font-semibold text-foreground">{rfqId ? `Ask about ${rfqId}` : 'Ask anything about CAM 3.4'}</h3>
              <p className="mx-auto max-w-md text-sm text-muted-foreground">
                {rfqId
                  ? 'Answers about this RFQ come from its results and show the cells they came from. You can also ask me to check progress, resume it, upload a file or download its reports.'
                  : 'Ask how to use the tool, or ask about an RFQ: you will be asked which RFQs to use. You can also ask me to open an RFQ, upload a file or download its reports.'}
              </p>
            </div>
            <div className="grid w-full max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
              {(rfqId ? RFQ_SUGGESTIONS : GENERAL_SUGGESTIONS).map((s) => (
                <button
                  key={s.title}
                  type="button"
                  onClick={() => onPick(s.prompt)}
                  className="rounded-xl border border-border bg-card px-3.5 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-accent"
                >
                  <span className="block text-sm font-medium text-foreground">{s.title}</span>
                  <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{s.prompt}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} msg={m} actions={actions} busy={running} />
        ))}
        {running && (
          <div className="flex justify-start" role="status" aria-label="The assistant is working">
            <div className="flex items-center gap-2.5 rounded-2xl border border-border bg-card px-4 py-3">
              <span className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground motion-reduce:animate-none" style={{ animationDelay: `${i * 0.2}s` }} />
                ))}
              </span>
              <span className="text-xs text-muted-foreground">{rfqId ? `Reading ${rfqId}…` : 'Working on it…'}</span>
            </div>
          </div>
        )}
        <div ref={end} />
      </div>
    </div>
  );
}
