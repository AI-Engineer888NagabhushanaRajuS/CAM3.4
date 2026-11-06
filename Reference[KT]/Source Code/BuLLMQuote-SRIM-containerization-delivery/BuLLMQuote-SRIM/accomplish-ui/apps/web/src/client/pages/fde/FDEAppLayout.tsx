import { useState } from 'react';
import { FDEStageSidebar, type FdeStageId } from '@/components/fde/FDEStageSidebar';
import { FDEStageStub } from '@/components/fde/FDEStageStub';
import { FDEUploadDocsPanel } from '@/components/fde/FDEUploadDocsPanel';
import { FDESettingsDialog } from '@/components/fde/FDESettingsDialog';

/**
 * FDE Staging Pipeline's top-level shell -- same 3-pane look as the RFQ
 * App (left stage list / center content / right output), completely
 * separate component tree and state (no WORKFLOW_STAGES/activeRfqId-scoped
 * SSE reuse from App.tsx, which is too RFQ-specific). Reached only via
 * /workflow-builder's requireFde() loader.
 */
export function FDEAppLayout() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [activeStage, setActiveStage] = useState<FdeStageId>('upload_docs');
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="flex h-screen bg-background text-foreground">
      <FDEStageSidebar
        activeStage={activeStage}
        onSelectStage={setActiveStage}
        selectedProjectId={selectedProjectId}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {activeStage === 'upload_docs' ? (
          <FDEUploadDocsPanel
            selectedProjectId={selectedProjectId}
            onSelectProject={setSelectedProjectId}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        ) : (
          <FDEStageStub stageId={activeStage} />
        )}
      </main>

      {/* Right pane: HITL/output -- same shell position as the RFQ App's
          own right pane, empty for Stage 1 (no output to show yet). */}
      <aside className="w-80 shrink-0 border-l border-border bg-card" />

      <FDESettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        onProjectCreated={(projectId) => {
          setSelectedProjectId(projectId);
          setActiveStage('upload_docs');
        }}
      />
    </div>
  );
}
