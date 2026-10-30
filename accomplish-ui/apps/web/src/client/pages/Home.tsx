import { lazy, Suspense } from 'react';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { ArrowClockwise } from '@phosphor-icons/react';
import { TaskInputBar } from '@/components/landing/TaskInputBar';
import { springs } from '@/lib/animations';
import { PlusMenu } from '@/components/landing/PlusMenu';
import { getSession } from '@/lib/session';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useHomePage } from './home/useHomePage';
import { FavoritesSection } from './home/FavoritesSection';
import { ExamplesSection } from './home/ExamplesSection';
import { useRfqContext } from '../contexts/RfqContext';

const SettingsDialog = lazy(async () => {
  const module = await import('@/components/layout/SettingsDialog');
  return { default: module.SettingsDialog };
});

export function HomePage() {
  const { t } = useTranslation('home');
  const { activeRfqId } = useRfqContext();
  const {
    prompt,
    setPrompt,
    showAllFavorites,
    setShowAllFavorites,
    attachments,
    attachmentError,
    setAttachments,
    workingDirectory,
    setWorkingDirectory,
    showSettingsDialog,
    settingsInitialTab,
    favoritesList,
    removeFavorite,
    isLoading,
    useCaseExamples,
    displayedFavorites,
    hasMoreFavorites,
    handleSubmit,
    handleSettingsDialogChange,
    handleOpenSpeechSettings,
    handleOpenModelSettings,
    handleApiKeySaved,
    handleExampleClick,
    handleSkillSelect,
    handleAttachFiles,
    handleOpenSettings,
    MAX_FILES,
  } = useHomePage();

  const userName = getSession()?.user.name ?? 'there';
  const handleResetChat = () => {
    setPrompt('');
    setAttachments([]);
    setWorkingDirectory(undefined);
  };

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
        {/* Header — matches the left pane's font sizes for uniformity */}
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-sm font-semibold text-foreground">New Chat</h2>
              {activeRfqId && (
                <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                  {activeRfqId}
                </span>
              )}
            </div>
            <p className="truncate text-xs text-muted-foreground">How can I help you today?</p>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label="Reset conversation"
                onClick={handleResetChat}
              >
                <ArrowClockwise className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Reset</TooltipContent>
          </Tooltip>
        </div>

        <div className="flex flex-1 flex-col overflow-y-auto px-4 sm:px-6">
          {/* Above-fold: fills full viewport height */}
          <div className="flex min-h-full flex-col">
            {/* Greeting is vertically centered in the empty state. */}
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                className="mb-5"
              >
                <img src="/assets/cam-logo.png" alt="Centum" className="h-16 w-auto object-contain" />
              </motion.div>
              <motion.p
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                className="mb-1 text-sm font-semibold text-foreground"
              >
                {userName}
              </motion.p>
              <motion.h1
                data-testid="home-title"
                initial={{ opacity: 0, scale: 0.93, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.75, ease: [0.16, 1, 0.3, 1] }}
                className="text-sm font-normal text-muted-foreground"
              >
                What will your Sourcing Team handle today?
              </motion.h1>
            </div>

            {/* Input — pinned at the bottom */}
            <div className="mx-auto w-full max-w-[760px] pb-8">
              <div className="mx-auto w-full max-w-[760px]">
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ ...springs.gentle, delay: 0.35 }}
                  className="w-full"
                >
                  <TaskInputBar
                    value={prompt}
                    onChange={setPrompt}
                    onSubmit={handleSubmit}
                    isLoading={isLoading}
                    placeholder={t('inputPlaceholder')}
                    typingPlaceholder={true}
                    large={true}
                    autoFocus={true}
                    autoSubmitOnTranscription={false}
                    onOpenSpeechSettings={handleOpenSpeechSettings}
                    onOpenModelSettings={handleOpenModelSettings}
                    hideModelWhenNoModel={true}
                    attachments={attachments}
                    attachmentError={attachmentError}
                    onAttachmentsChange={setAttachments}
                    toolbarLeft={
                      <PlusMenu
                        onSkillSelect={handleSkillSelect}
                        onOpenSettings={handleOpenSettings}
                        onAttachFiles={handleAttachFiles}
                        disabled={isLoading}
                        attachmentCount={attachments.length}
                        maxAttachments={MAX_FILES}
                      />
                    }
                  />
                  {workingDirectory && (
                    <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                      <span className="max-w-[400px] truncate" title={workingDirectory}>
                        {t('selectedFolder.badge', { folder: workingDirectory })}
                      </span>
                      <button
                        type="button"
                        onClick={() => setWorkingDirectory(undefined)}
                        className="ml-1 transition-colors hover:text-foreground"
                        aria-label={t('selectedFolder.clearAriaLabel')}
                      >
                        ✕
                      </button>
                    </div>
                  )}
                </motion.div>
              </div>
              {/* end inner max-w wrapper */}
            </div>
            {/* end title+input wrapper */}
          </div>
          {/* end above-fold flex */}

          {/* Below fold — only visible on scroll */}
          <div className="mx-auto w-full max-w-[760px] pb-8">
            <FavoritesSection
              favoritesList={favoritesList}
              displayedFavorites={displayedFavorites}
              hasMoreFavorites={hasMoreFavorites}
              showAllFavorites={showAllFavorites}
              onSetPrompt={setPrompt}
              onRemoveFavorite={removeFavorite}
              onShowAll={() => setShowAllFavorites(true)}
            />

            <ExamplesSection
              useCaseExamples={useCaseExamples}
              onExampleClick={handleExampleClick}
            />
          </div>
        </div>
      </div>
    </>
  );
}
