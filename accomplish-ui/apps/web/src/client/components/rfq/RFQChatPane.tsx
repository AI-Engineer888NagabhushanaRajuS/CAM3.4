import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowClockwise, ChatCircle, Plus, ShieldCheck, X } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { TaskInputBar } from '@/components/landing/TaskInputBar';
import { ACCEPTED_EXTENSIONS, deleteAttachment, listAttachments, type Attachment } from '@/lib/rfqAttachments';
import { AssistantMessages } from './AssistantMessages';
import { AttachFilesDialog } from './AttachFilesDialog';
import { useAssistantChat } from './useAssistantChat';

interface RFQChatPaneProps {
  /** The RFQ the assistant answers about; null = the assistant that lists RFQs and routes to the one named. */
  rfqId: string | null;
  isOpen: boolean;
  onClose?: () => void;
  /** Render in the page's middle column instead of the floating corner pane. */
  inline?: boolean;
  onOpenModelSettings?: () => void;
  onOpenSpeechSettings?: () => void;
}

/**
 * The assistant. One persistent conversation: it never closes after an answer, a refusal or an error. Answers come from
 * the RFQ's results (daemon rfq-chat service), each with the cells they came from. Files are added through a review
 * popup and two security engines; only released files become context.
 */
export function RFQChatPane({ rfqId, isOpen, onClose, inline = false, onOpenModelSettings, onOpenSpeechSettings }: RFQChatPaneProps) {
  const chat = useAssistantChat(rfqId);
  const [draft, setDraft] = useState('');
  const [picked, setPicked] = useState<File[] | null>(null);
  const [context, setContext] = useState<Attachment[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    if (!rfqId) {
      setContext([]);
      return;
    }
    try {
      setContext(await listAttachments(rfqId));
    } catch {
      setContext([]); // the scan service may be down or older: show no files rather than guess
    }
  }, [rfqId]);
  useEffect(() => { void refresh(); }, [refresh]);

  if (!isOpen && !inline) return null;

  const submit = () => {
    if (chat.running) {
      chat.stop();
      return;
    }
    const text = draft.trim();
    if (!text) return;
    setDraft('');
    void chat.send(text);
  };

  const remove = async (a: Attachment) => {
    if (!rfqId) return;
    try {
      await deleteAttachment(rfqId, a.attachment_id);
    } finally {
      void refresh();
    }
  };

  const model = [...chat.messages].reverse().find((m) => m.model)?.model;
  const rootClass = inline
    ? 'flex h-full min-h-0 w-full flex-col overflow-hidden bg-background'
    : 'fixed bottom-4 right-4 z-50 flex h-[min(640px,calc(100dvh-2rem))] w-[min(440px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-2xl';

  return (
    <div className={rootClass}>
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <ChatCircle className="h-4 w-4 shrink-0 text-primary" weight="fill" />
            <h2 className="truncate text-sm font-semibold text-foreground">RFQ Assistant</h2>
            <span className="inline-flex shrink-0 items-center rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">{rfqId ?? 'All RFQs'}</span>
          </div>
          <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
            <ShieldCheck className="h-3 w-3 shrink-0 text-primary" weight="fill" />
            Answers come only from the RFQ’s results, with their sources{model ? ` · ${model}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button type="button" variant="outline" size="icon" aria-label="Reset conversation" onClick={() => { chat.reset(); setDraft(''); }}>
                <ArrowClockwise className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Reset conversation</TooltipContent>
          </Tooltip>
          {onClose && (
            <Button type="button" variant="ghost" size="icon" aria-label="Close chat" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      <AssistantMessages messages={chat.messages} running={chat.running} rfqId={rfqId} onPick={(p) => void chat.send(p)} />

      <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4 sm:px-6">
        {context.length > 0 && (
          <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Files the assistant can read">
            {context.map((a) => (
              <li key={a.attachment_id} className="inline-flex max-w-[260px] items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-foreground">
                <ShieldCheck className="h-3 w-3 shrink-0 text-emerald-600 dark:text-emerald-400" weight="fill" aria-hidden />
                <span className="truncate" title={`${a.name}: cleared by both security engines`}>{a.name}</span>
                <button type="button" aria-label={`Remove ${a.name}`} className="-my-1 -mr-1.5 flex h-6 w-6 items-center justify-center rounded-full text-muted-foreground hover:bg-background/60 hover:text-foreground" onClick={() => void remove(a)}>
                  <X className="h-3 w-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div
          onDropCapture={(e) => {
            const files = Array.from(e.dataTransfer?.files ?? []);
            if (rfqId && files.length) setPicked(files);
          }}
        >
          <TaskInputBar
            value={draft}
            onChange={setDraft}
            onSubmit={submit}
            isLoading={chat.running}
            placeholder={rfqId ? 'Ask about this RFQ’s results…' : 'Ask which RFQs you have, or name one…'}
            autoFocus={inline}
            autoSubmitOnTranscription={false}
            onOpenSpeechSettings={onOpenSpeechSettings}
            onOpenModelSettings={onOpenModelSettings}
            hideModelWhenNoModel
            toolbarLeft={
              <Tooltip>
                <TooltipTrigger asChild>
                  {/* the span carries the hint: a disabled button shows no tooltip of its own */}
                  <span className="inline-flex" title={rfqId ? undefined : 'Pick an RFQ to add files'}>
                    <button
                      type="button"
                      disabled={!rfqId || chat.running}
                      onClick={() => fileInput.current?.click()}
                      aria-label="Add files"
                      className="flex h-6 w-6 shrink-0 items-center justify-center text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Plus className="h-4 w-4" weight="light" aria-hidden />
                    </button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>{rfqId ? 'Add files: checked by two security engines first' : 'Pick an RFQ to add files'}</TooltipContent>
              </Tooltip>
            }
          />
        </div>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          accept={ACCEPTED_EXTENSIONS.join(',')}
          data-testid="assistant-file-input"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = '';
            if (files.length) setPicked(files);
          }}
        />
      </div>

      {rfqId && picked && (
        <AttachFilesDialog
          open
          rfqId={rfqId}
          files={picked}
          alreadyAttached={context.map((a) => a.name)}
          onClose={() => setPicked(null)}
          onReleased={() => void refresh()}
        />
      )}
    </div>
  );
}

/** Floating trigger button shown in ExecutionHeader when the pane is closed. */
export function RFQChatButton({ rfqId, onClick }: { rfqId: string; onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onClick} className="gap-1.5" title={`Open RFQ assistant for ${rfqId}`}>
      <ChatCircle className="h-4 w-4" weight="fill" />
      Ask Assistant
    </Button>
  );
}
