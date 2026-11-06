import { SpinnerGap, CheckCircle, Warning, FileText } from '@phosphor-icons/react';
import type { WorkflowStageId } from '../../App';

export type UploadStepStatus = 'pending' | 'uploading' | 'processing' | 'done' | 'error';

export interface IntakeProgressState {
  bomFileName: string | null;
  bomStatus: UploadStepStatus;
  quoteWinFileName: string | null;
  costingSheetFileName: string | null;
  erpStatus: UploadStepStatus;
  errorMessage: string | null;
}

export const initialIntakeProgress: IntakeProgressState = {
  bomFileName: null,
  bomStatus: 'pending',
  quoteWinFileName: null,
  costingSheetFileName: null,
  erpStatus: 'pending',
  errorMessage: null,
};

interface RfqIntakeProgressPanelProps {
  progress: IntakeProgressState;
  currentWorkflowStage: WorkflowStageId;
  onRequestErpUpload: () => void;
}

function StatusGlyph({ status }: { status: UploadStepStatus }) {
  if (status === 'uploading' || status === 'processing') {
    return <SpinnerGap className="h-4 w-4 shrink-0 animate-spin text-primary" />;
  }
  if (status === 'done') {
    return <CheckCircle weight="fill" className="h-4 w-4 shrink-0 text-emerald-400" />;
  }
  if (status === 'error') {
    return <Warning weight="fill" className="h-4 w-4 shrink-0 text-red-400" />;
  }
  return <div className="h-2 w-2 shrink-0 rounded-full bg-muted-foreground/30 ml-1 mr-1" />;
}

function stepLabel(status: UploadStepStatus, verb: string, errorMessage: string | null): string {
  if (status === 'uploading') { return 'Uploading…'; }
  if (status === 'processing') { return `${verb}…`; }
  if (status === 'done') { return 'Done'; }
  if (status === 'error') { return errorMessage ?? 'Failed'; }
  return 'Waiting';
}

/**
 * Live left-panel indicator for the BOM -> QuoteWin/Costing Sheet intake
 * flow. Fed entirely by state App.tsx already derives from the upload
 * modals and the awaitUploads hitl:request event -- this component only
 * renders it.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function RfqIntakeProgressPanel({ progress, currentWorkflowStage: _currentWorkflowStage, onRequestErpUpload: _onRequestErpUpload }: RfqIntakeProgressPanelProps) {
  if (progress.bomStatus === 'pending') { return null; }

  // QuoteWin/Costing Sheet progress + the "upload next" prompt intentionally
  // removed from this panel -- RFQ_Flow (this project's only active pipeline)
  // uploads BOM + Volume together up front; there is no separate QuoteWin/
  // Costing Sheet step to progress-track here. currentWorkflowStage/
  // onRequestErpUpload are kept as props (Standard_BOM_Flow's own upload
  // modal still uses them elsewhere) but no longer read by this panel.
  return (
    <div className="mb-4 rounded-lg border border-border/70 bg-background/60 p-3 space-y-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Intake Progress</p>

      <div className="flex items-center gap-2 text-xs">
        <StatusGlyph status={progress.bomStatus} />
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-foreground">{progress.bomFileName}</span>
        <span className="shrink-0 text-muted-foreground">
          {stepLabel(progress.bomStatus, 'Standardizing BOM', progress.errorMessage)}
        </span>
      </div>
    </div>
  );
}
