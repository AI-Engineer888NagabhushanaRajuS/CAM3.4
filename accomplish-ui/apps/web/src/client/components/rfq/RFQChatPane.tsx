import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowClockwise, ChatCircle, Plus, ShieldCheck, X } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { TaskInputBar } from '@/components/landing/TaskInputBar';
import { ACCEPTED_EXTENSIONS, deleteAttachment, listAttachments, type Attachment } from '@/lib/rfqAttachments';
import { chatStagingId, singleRfq } from '@/lib/chatContract';
import { AssistantMessages } from './AssistantMessages';
import type { DirectiveActions } from './AssistantDirectives';
import { AttachFilesDialog } from './AttachFilesDialog';
import { ProviderSwitch } from './ProviderSwitch';
import { RfqPickerDialog } from './RfqPickerDialog';
import { ScopeChips } from './ScopeChips';
import { useAssistantChat } from './useAssistantChat';

interface RFQChatPaneProps {
  /** The RFQ selected in the left list: it becomes the conversation's scope. null = normal chat until the assistant asks which RFQs. */
  rfqId: string | null;
  isOpen: boolean;
  onClose?: () => void;
  /** Render in the page's middle column instead of the floating corner pane. */
  inline?: boolean;
  onOpenModelSettings?: () => void;
  onOpenSpeechSettings?: () => void;
  /** Select an RFQ exactly as picking it in the left list (the assistant's "Open RFQ-x" button). */
  onSelectRfq?: (rfqId: string) => void;
}

/**
 * The assistant. One persistent conversation: it never closes after an answer, a refusal or an error. RFQ answers come
 * from the scope's results (daemon rfq-chat service), each with the cells they came from; the daemon's `ui` directives
 * (RFQ picker, option buttons, confirmation card, upload) are drawn here and never acted on without the user. Files are
 * added through a review popup and two security engines; only released files become context.
 */
export function RFQChatPane({ rfqId, isOpen, onClose, inline = false, onOpenModelSettings, onOpenSpeechSettings, onSelectRfq }: RFQChatPaneProps) {
  const [context, setContext] = useState<Attachment[]>([]);
  const contextRef = useRef<{ files: Attachment[]; at: string }>({ files: [], at: '' });
  const getFileRefs = useCallback(
    () => contextRef.current.files.map((a) => ({ attachmentId: a.attachment_id, name: a.name, rfqId: contextRef.current.at })),
    [],
  );
  const chat = useAssistantChat(rfqId, getFileRefs);
  const [draft, setDraft] = useState('');
  const [picked, setPicked] = useState<File[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Files are scanned and listed under the one RFQ in scope, else the one selected in the left list, else a per-tab
  // staging scope: with no RFQ yet, "create an RFQ from this file" still has somewhere safe to scan it first.
  const one = singleRfq(chat.scope);
  const uploadRfq = one ?? rfqId ?? chatStagingId();
  contextRef.current = { files: context, at: uploadRfq };

  const refresh = useCallback(async () => {
    try {
      setContext(await listAttachments(uploadRfq));
    } catch {
      setContext([]); // the scan service may be down or older: show no files rather than guess
    }
  }, [uploadRfq]);
  useEffect(() => { void refresh(); }, [refresh]);

  const { choose, openPicker, settle } = chat;
  const actions = useMemo<DirectiveActions>(() => ({
    onChoose: choose,
    onOpenPicker: openPicker,
    onSettle: (id, outcome) => settle(id, { confirm: outcome }),
    // marked done first: selecting switches the conversation, and the mark must land on this one
    onOpenRfq: onSelectRfq && ((id, target) => {
      settle(id, { done: target });
      onSelectRfq(target);
    }),
    onOpenSettings: onOpenModelSettings,
    onUpload: (accept) => {
      setNotice(null);
      if (fileInput.current) {
        fileInput.current.accept = (accept.length > 0 ? accept : ACCEPTED_EXTENSIONS).join(',');
        fileInput.current.click();
      }
    },
  }), [choose, openPicker, settle, onSelectRfq, onOpenModelSettings]);

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
    try {
      await deleteAttachment(uploadRfq, a.attachment_id);
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
      {/* wraps: title and scope chips keep a readable width, the switch and buttons drop to a second row when the pane is narrow */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border px-4 py-3 sm:px-6">
        <div className="min-w-[11rem] flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <ChatCircle className="h-4 w-4 shrink-0 text-primary" weight="fill" />
            <h2 className="truncate text-sm font-semibold text-foreground">RFQ Assistant</h2>
            <ScopeChips scope={chat.scope} onRemove={chat.removeFromScope} />
          </div>
          <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
            <ShieldCheck className="h-3 w-3 shrink-0 text-primary" weight="fill" />
            RFQ answers come with their source cells{model ? ` · ${model}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <ProviderSwitch mode={chat.provider} onChange={chat.setProvider} onOpenSettings={onOpenModelSettings} />
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

      <AssistantMessages messages={chat.messages} running={chat.running} rfqId={one} onPick={(p) => void chat.send(p)} actions={actions} />

      <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4 sm:px-6">
        {notice && <p role="status" className="mb-2 text-xs text-amber-700 dark:text-amber-400">{notice}</p>}
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
            if (files.length) setPicked(files);
          }}
        >
          <TaskInputBar
            value={draft}
            onChange={setDraft}
            onSubmit={submit}
            isLoading={chat.running}
            placeholder={one ? 'Ask about this RFQ’s results…' : 'Ask anything, or ask about an RFQ…'}
            autoFocus={inline}
            autoSubmitOnTranscription={false}
            onOpenSpeechSettings={onOpenSpeechSettings}
            onOpenModelSettings={onOpenModelSettings}
            hideModelWhenNoModel
            toolbarLeft={
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex">
                    <button
                      type="button"
                      disabled={chat.running}
                      onClick={() => {
                        if (fileInput.current) fileInput.current.accept = ACCEPTED_EXTENSIONS.join(',');
                        fileInput.current?.click();
                      }}
                      aria-label="Add files"
                      className="flex h-6 w-6 shrink-0 items-center justify-center text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Plus className="h-4 w-4" weight="light" aria-hidden />
                    </button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>Add files: checked by two security engines first</TooltipContent>
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

      {picked && (
        <AttachFilesDialog
          open
          rfqId={uploadRfq}
          files={picked}
          alreadyAttached={context.map((a) => a.name)}
          onClose={() => setPicked(null)}
          onReleased={() => void refresh()}
        />
      )}

      {chat.picker?.ui?.type === 'pick_rfq' && (
        <RfqPickerDialog
          key={chat.picker.id}
          reason={chat.picker.ui.reason}
          options={chat.picker.ui.options}
          initial={chat.scope.mode === 'rfqs' ? chat.scope.rfqIds : []}
          onPick={(next) => chat.picker && chat.applyPick(chat.picker, next)}
          onCancel={chat.closePicker}
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
