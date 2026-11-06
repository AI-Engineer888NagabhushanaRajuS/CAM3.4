import { useState } from 'react';
import { CheckCircle, DownloadSimple, FileCode, FolderOpen, GearSix, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { PYTHON_BRIDGE_URL } from '@/config/endpoints';
import { authDownload } from '@/lib/apiAuth';
import { manifestHash } from '@/lib/chatContract';
import type { ChatMsg } from './useAssistantChat';

/** The same file the Quote Readiness "Download" button opens; fetched with the RFQ token so a refusal can be shown. */
export function downloadReports(rfqId: string): Promise<void> {
  return authDownload(`${PYTHON_BRIDGE_URL}/api/bom/export/${encodeURIComponent(rfqId)}/download`, rfqId);
}

/** Selects the RFQ exactly like the left list. One press, then it stays marked done on the message. */
export function OpenRfqDirective({ msg, rfqId, busy, onOpen }: { msg: ChatMsg; rfqId: string; busy: boolean; onOpen?: () => void }) {
  if (msg.done) {
    return (
      <p role="status" className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <CheckCircle className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" weight="fill" aria-hidden />
        Opened {rfqId}
      </p>
    );
  }
  if (!onOpen) {
    return null;
  }
  return (
    <div className="mt-3">
      <Button size="sm" variant="outline" className="min-h-8 gap-1.5" disabled={busy} onClick={onOpen}>
        <FolderOpen className="h-4 w-4" aria-hidden />
        Open {rfqId}
      </Button>
    </div>
  );
}

/** Downloads the RFQ's reports. A refusal (no export yet, bridge down) is written under the button, in words. */
export function OpenExportDirective({ rfqId, busy }: { rfqId: string; busy: boolean }) {
  const [state, setState] = useState<'idle' | 'working' | 'started' | 'failed'>('idle');
  const [error, setError] = useState('');

  const run = async () => {
    if (state === 'working') {
      return;
    }
    setState('working');
    try {
      await downloadReports(rfqId);
      setState('started');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The download failed');
      setState('failed');
    }
  };

  return (
    <div className="mt-3 space-y-1.5">
      <Button size="sm" variant="outline" className="min-h-8 gap-1.5" disabled={busy || state === 'working'} onClick={() => void run()}>
        <DownloadSimple className="h-4 w-4" aria-hidden />
        {state === 'working' ? 'Downloading…' : `Download reports for ${rfqId}`}
      </Button>
      {state === 'started' && <p role="status" className="text-xs text-muted-foreground">Download started for {rfqId}.</p>}
      {state === 'failed' && (
        <p role="alert" className="flex items-start gap-1.5 text-xs font-medium text-destructive">
          <WarningCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" weight="fill" aria-hidden />
          <span className="min-w-0 break-words">Could not download the reports for {rfqId}: {error}. Check that the reports were exported, then try again.</span>
        </p>
      )}
    </div>
  );
}

/** Opens Settings on the Providers tab (the existing onOpenModelSettings). */
export function OpenSettingsDirective({ busy, onOpen }: { busy: boolean; onOpen?: () => void }) {
  if (!onOpen) {
    return null;
  }
  return (
    <div className="mt-3">
      <Button size="sm" variant="outline" className="min-h-8 gap-1.5" disabled={busy} onClick={onOpen}>
        <GearSix className="h-4 w-4" aria-hidden />
        Open Settings
      </Button>
    </div>
  );
}

/** Opens the manifest editor on one manifest (hash route). A link, so it also works with the keyboard and in a new tab. */
export function OpenManifestDirective({ path, label }: { path: string; label: string }) {
  return (
    <div className="mt-3">
      <Button asChild size="sm" variant="outline" className="min-h-8 gap-1.5">
        <a href={manifestHash(path)}>
          <FileCode className="h-4 w-4" aria-hidden />
          Open {label}
        </a>
      </Button>
    </div>
  );
}
