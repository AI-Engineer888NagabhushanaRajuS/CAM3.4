import { Sparkle } from '@phosphor-icons/react';
import type { FdeStageId } from './FDEStageSidebar';

const STAGE_LABELS: Record<FdeStageId, string> = {
  upload_docs: 'Upload Docs',
  cognify: 'Cognify',
  okf_bundle: 'OKF Bundle',
  sow_generation: 'SOW Generation',
  validation: 'Validation',
  skill: 'Skill',
};

interface FDEStageStubProps {
  stageId: FdeStageId;
}

/** One generic placeholder for every not-yet-implemented stage -- not 5
 * separate stub files. Stage 2+ needs SBAM (the Cognee/OKF/SOW engine),
 * which isn't available on this machine yet; this is wired for real once
 * it is. */
export function FDEStageStub({ stageId }: FDEStageStubProps) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="flex max-w-sm flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-card p-8 text-center">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Sparkle className="h-5 w-5" />
        </span>
        <p className="text-sm font-semibold text-foreground">{STAGE_LABELS[stageId]}</p>
        <p className="text-xs text-muted-foreground">Coming soon.</p>
      </div>
    </div>
  );
}
