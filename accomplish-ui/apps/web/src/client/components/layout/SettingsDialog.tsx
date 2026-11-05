import { AnimatePresence, LayoutGroup, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { SignOut } from '@phosphor-icons/react';
import { settingsVariants, settingsTransitions } from '@/lib/animations';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import type { ProviderId } from '@accomplish_ai/agent-core/common';
import { ProviderGrid } from '@/components/settings/ProviderGrid';
import { ProviderSettingsPanel } from '@/components/settings/ProviderSettingsPanel';
import { RoutingProfilePanel } from '@/components/settings/routingProfile';
import { ProjectTrackingPanel } from '@/components/settings/projectTracking';
import { UsersPanel } from '@/components/settings/users';
import { CurrenciesPanel } from '@/components/settings/currencies';
import { AboutTab } from '@/components/settings/AboutTab';
import { SecurityTab } from '@/components/settings/SecurityTab';
import { GeneralTab } from '@/components/settings/GeneralTab';
import { SandboxSection } from '@/components/settings/SandboxSection';
import { cn } from '@/lib/utils';
import { logout, isAdmin } from '@/lib/session';
import { BrandMark } from '@/components/BrandMark';
import { SETTINGS_TABS, type SettingsTabId } from './settings-tabs';
import { useSettingsDialog } from './useSettingsDialog';

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApiKeySaved?: () => void;
  initialProvider?: ProviderId;
  initialTab?: SettingsTabId;
}

export function SettingsDialog({
  open,
  onOpenChange,
  onApiKeySaved,
  initialProvider,
  initialTab = 'providers',
}: SettingsDialogProps) {
  const { t } = useTranslation('settings');
  const s = useSettingsDialog({ open, onOpenChange, onApiKeySaved, initialProvider, initialTab });
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true, state: { loggedOut: true } });
  };

  if (s.loading || !s.settings) {
    return (
      <Dialog open={open} onOpenChange={s.handleOpenChange}>
        <DialogContent
          className="srim-settings-dialog max-w-4xl w-full h-[80vh] max-h-[720px] flex flex-col overflow-hidden p-0"
          data-testid="settings-dialog"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <DialogHeader className="sr-only">
            <DialogTitle>{t('title')}</DialogTitle>
          </DialogHeader>
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={s.handleOpenChange}>
      <DialogContent
        className="srim-settings-dialog max-w-4xl w-full h-[80vh] max-h-[720px] flex overflow-hidden p-0"
        data-testid="settings-dialog"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <DialogHeader className="sr-only">
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>

        <LayoutGroup id="srim-settings-navigation">
        <nav className="w-48 shrink-0 border-r border-border bg-muted/30 p-3 flex flex-col h-full">
          <div className="flex flex-col gap-1 flex-1 overflow-y-auto min-h-0">
            <div className="px-3 py-2 mb-1 flex items-center gap-2">
              <BrandMark className="text-sm" />
            </div>
            {SETTINGS_TABS.filter((tab) => (tab.id !== 'users' && tab.id !== 'currencies') || isAdmin()).map((tab) => (
              <button
                key={tab.id}
                onClick={() => s.setActiveTab(tab.id)}
                className={cn(
                  'relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors text-left',
                  s.activeTab === tab.id
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-background/50',
                )}
                >
                {s.activeTab === tab.id && (
                  <motion.span layoutId="active-settings-tab" className="absolute inset-0 rounded-lg bg-background shadow-sm" transition={{ type: 'spring', stiffness: 420, damping: 32 }} />
                )}
                <span className="relative z-10 flex items-center gap-2.5">
                  <tab.icon className="h-4 w-4 shrink-0" />
                  {t(tab.labelKey)}
                </span>
                </button>
            ))}
          </div>
          <div className="pt-2 border-t border-border shrink-0">
            <button
              onClick={handleLogout}
              className="flex items-center gap-2.5 w-full rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
            >
              <SignOut className="h-4 w-4 shrink-0" />
              Sign out
            </button>
          </div>
        </nav>
        </LayoutGroup>

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-6 pt-5 pb-3">
            <h3 className="text-sm font-semibold text-foreground">
              {SETTINGS_TABS.find((tab) => tab.id === s.activeTab)?.labelKey &&
                t(SETTINGS_TABS.find((tab) => tab.id === s.activeTab)!.labelKey)}
            </h3>
          </div>

          <div className="flex-1 overflow-y-auto px-6 pb-6">
            <div className="space-y-6">
              <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={s.activeTab}
                initial={{ opacity: 0, y: 12, filter: 'blur(3px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                exit={{ opacity: 0, y: -8, filter: 'blur(3px)' }}
                transition={{ duration: 0.26, ease: [0.16, 1, 0.3, 1] }}
                className="srim-settings-tab-content"
              >
              {s.activeTab === 'providers' && (
                <div className="space-y-6">
                  <section>
                    <ProviderGrid
                      settings={s.settings}
                      selectedProvider={s.selectedProvider}
                      onSelectProvider={s.handleSelectProvider}
                      expanded={s.gridExpanded}
                      onToggleExpanded={() => s.setGridExpanded(!s.gridExpanded)}
                    />
                  </section>
                  <AnimatePresence>
                    {s.selectedProvider && (
                      <motion.section
                        variants={settingsVariants.slideDown}
                        initial="initial"
                        animate="animate"
                        exit="exit"
                        transition={settingsTransitions.enter}
                      >
                        <ProviderSettingsPanel
                          key={s.selectedProvider}
                          providerId={s.selectedProvider}
                          connectedProvider={s.settings?.connectedProviders?.[s.selectedProvider]}
                          onConnect={s.handleConnect}
                          onUpdateProvider={s.handleUpdateProvider}
                          onDisconnect={s.handleDisconnect}
                          onModelChange={s.handleModelChange}
                          showModelError={s.showModelError}
                        />
                      </motion.section>
                    )}
                  </AnimatePresence>
                  <SandboxSection visible={!!s.selectedProvider} />
                </div>
              )}

              {s.activeTab === 'skills' && (
                <div className="space-y-4">
                  <RoutingProfilePanel refreshTrigger={s.skillsRefreshTrigger} />
                </div>
              )}
              {s.activeTab === 'projectTracking' && (
                <div className="space-y-4">
                  <ProjectTrackingPanel />
                </div>
              )}
              {s.activeTab === 'currencies' && (
                <div className="space-y-4">
                  <CurrenciesPanel />
                </div>
              )}
              {s.activeTab === 'users' && (
                <div className="space-y-4">
                  <UsersPanel />
                </div>
              )}
              {s.activeTab === 'security' && <SecurityTab />}
              {s.activeTab === 'general' && (
                <GeneralTab
                  notificationsEnabled={s.notificationsEnabled}
                  onNotificationsToggle={s.handleNotificationsToggle}
                  debugMode={s.debugMode}
                  onDebugToggle={s.handleDebugToggle}
                />
              )}
              {s.activeTab === 'about' && <AboutTab appVersion={s.appVersion} />}
              </motion.div>
              </AnimatePresence>

              <div className="mt-4 flex items-center justify-between">
                <div />
                <button
                  onClick={s.handleDone}
                  className="flex items-center gap-2 rounded-md bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  data-testid="settings-done-button"
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                  {t('buttons.done')}
                </button>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default SettingsDialog;
