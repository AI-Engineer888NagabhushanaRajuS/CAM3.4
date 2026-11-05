import { lazy, Suspense } from 'react';
import { RFQChatPane } from '@/components/rfq/RFQChatPane';
import { useRfqContext } from '../contexts/RfqContext';
import { useHomePage } from './home/useHomePage';

const SettingsDialog = lazy(async () => {
  const module = await import('@/components/layout/SettingsDialog');
  return { default: module.SettingsDialog };
});

/**
 * The middle pane. It is always the assistant: selecting an RFQ on the left sets the conversation's scope to it; without
 * one it is a normal chat that asks which RFQs to use when a question needs them. It stays on screen after every answer
 * (the earlier one-shot task launcher closed the conversation after the first message).
 */
export function HomePage() {
  const { activeRfqId, selectRfq } = useRfqContext();
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
          onSelectRfq={selectRfq}
        />
      </div>
    </>
  );
}
