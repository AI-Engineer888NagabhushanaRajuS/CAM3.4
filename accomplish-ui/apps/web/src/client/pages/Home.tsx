import { lazy, Suspense } from 'react';
import { RFQChatPane } from '@/components/rfq/RFQChatPane';
import { useRfqContext } from '../contexts/RfqContext';
import { useHomePage } from './home/useHomePage';

const SettingsDialog = lazy(async () => {
  const module = await import('@/components/layout/SettingsDialog');
  return { default: module.SettingsDialog };
});

/**
 * The middle pane. It is always the assistant: with an RFQ selected it answers from that RFQ's results; without one it
 * lists the RFQs and routes to the one the question names. It stays on screen after every answer (the earlier one-shot
 * task launcher closed the conversation after the first message).
 */
export function HomePage() {
  const { activeRfqId } = useRfqContext();
  const {
    showSettingsDialog,
    settingsInitialTab,
    handleSettingsDialogChange,
    handleApiKeySaved,
    handleOpenSpeechSettings,
    handleOpenModelSettings,
  } = useHomePage();

  return (
    <>
      {showSettingsDialog && (
        <Suspense fallback={null}>
          <SettingsDialog
            open={showSettingsDialog}
            onOpenChange={handleSettingsDialogChange}
            onApiKeySaved={handleApiKeySaved}
            initialTab={settingsInitialTab}
          />
        </Suspense>
      )}

      <div className="srim-theme-shell relative flex h-full flex-col overflow-hidden">
        <RFQChatPane
          rfqId={activeRfqId || null}
          isOpen
          inline
          onOpenModelSettings={handleOpenModelSettings}
          onOpenSpeechSettings={handleOpenSpeechSettings}
        />
      </div>
    </>
  );
}
