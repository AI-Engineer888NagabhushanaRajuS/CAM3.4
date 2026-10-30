import { useState } from 'react';
import type { TaskStatus } from '@accomplish_ai/agent-core';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/button';
import { XCircle, ArrowLeft, CheckCircle, Clock, Square, Hourglass } from '@phosphor-icons/react';
import { RFQChatPane, RFQChatButton } from '@/components/rfq/RFQChatPane';

function StatusBadge({ status }: { status: TaskStatus }) {
  const { t } = useTranslation('execution');

  switch (status) {
    case 'queued':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-600 shrink-0">
          <Clock className="h-3 w-3" />
          {t('status.queued')}
        </span>
      );
    case 'running':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-primary/10 dark:bg-primary/5 shrink-0">
          <span className="animate-shimmer bg-gradient-to-r from-primary via-primary/50 to-primary dark:from-primary/70 dark:via-primary/30 dark:to-primary/70 bg-[length:200%_100%] bg-clip-text text-transparent">
            {t('status.running')}
          </span>
        </span>
      );
    case 'failed':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-destructive/10 text-destructive shrink-0">
          <XCircle className="h-3 w-3" />
          {t('status.failed')}
        </span>
      );
    case 'cancelled':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-muted text-muted-foreground shrink-0">
          <XCircle className="h-3 w-3" />
          {t('status.cancelled')}
        </span>
      );
    case 'interrupted':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-600 shrink-0">
          <Square className="h-3 w-3" />
          {t('status.stopped')}
        </span>
      );
    case 'pending':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-muted text-muted-foreground shrink-0">
          <Hourglass className="h-3 w-3" />
          {t('status.pending')}
        </span>
      );
    case 'waiting_permission':
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-600 shrink-0">
          <Hourglass className="h-3 w-3" />
          {t('status.waiting_permission')}
        </span>
      );
    default:
      return null;
  }
}

export function ExecutionHeader({
  prompt: _prompt,
  status,
  rfqId,
}: {
  prompt: string;
  status: TaskStatus;
  rfqId?: string;
}) {
  const navigate = useNavigate();
  const [chatOpen, setChatOpen] = useState(false);
  const showStatus = status === 'running' || status === 'queued' || status === 'waiting_permission' || status === 'pending';

  return (
    <>
      <div className="flex-shrink-0 border-b border-border bg-card/50 px-4 py-3">
        <div className="flex items-center justify-between max-w-4xl mx-auto">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => navigate('/')}
              aria-label="Back"
              className="shrink-0 no-drag"
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-foreground">Chat</p>
              <p className="text-xs text-muted-foreground">Sourcing Assistant</p>
            </div>
            {showStatus && (
              <span data-testid="execution-status-badge">
                <StatusBadge status={status} />
              </span>
            )}
            {rfqId && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-muted text-muted-foreground shrink-0">
                {rfqId}
              </span>
            )}
          </div>
          {rfqId && !chatOpen && (
            <RFQChatButton rfqId={rfqId} onClick={() => setChatOpen(true)} />
          )}
        </div>
      </div>
      {rfqId && (
        <RFQChatPane rfqId={rfqId} isOpen={chatOpen} onClose={() => setChatOpen(false)} />
      )}
    </>
  );
}
