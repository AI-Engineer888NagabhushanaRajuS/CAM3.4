import { useEffect, useState } from 'react';
import Uppy from '@uppy/core';
import { Dashboard } from '@uppy/react';
import '@uppy/core/dist/style.min.css';
import '@uppy/dashboard/dist/style.min.css';
import { ACCEPTED_EXTENSIONS, MAX_FILE_BYTES, MAX_PICK, REJECT_TEXT, triageFiles } from '@/lib/rfqAttachments';
import { useMonacoTheme } from '@/components/manifests/useMonacoTheme';

interface Props {
  /** What was picked or dropped; the rules of triageFiles decide which of them are tiles. */
  files: File[];
  alreadyAttached: string[];
  /** Every change of the tiles (drop, browse, remove), as plain Files in tile order. */
  onChange: (picked: File[]) => void;
  /** The Uppy instance, for the dialog's "Remove all". */
  onReady: (uppy: Uppy) => void;
}

/**
 * Uppy Dashboard as the PICKER only (SPEC-022): tiles, remove, add more, drag and drop. There is no upload plugin: the files go to
 * the twin-engine scan when the dialog says so, and nothing is read here. triageFiles stays the one source of the acceptance rules.
 */
export function IntakeDashboard({ files, alreadyAttached, onChange, onReady }: Props) {
  const theme = useMonacoTheme() === 'vs-dark' ? 'dark' : 'light';
  const [uppy, setUppy] = useState<Uppy | null>(null);

  // Built inside the effect, not memoised: StrictMode runs effect, cleanup, effect, and a destroyed Uppy cannot be reused.
  useEffect(() => {
    const names = alreadyAttached;
    const u = new Uppy({
      autoProceed: false,
      restrictions: { maxNumberOfFiles: MAX_PICK, maxFileSize: MAX_FILE_BYTES, allowedFileTypes: ACCEPTED_EXTENSIONS },
      // A file added from the Dashboard's own "browse" goes through the same rules as one picked outside it.
      onBeforeFileAdded: (file, current) => {
        const t = triageFiles([file.data as File], [...names, ...Object.values(current).map((f) => f.name ?? '')]);
        if (t.usable.length === 0) {
          u.info(`${file.name}: ${REJECT_TEXT[t.rejected[0].reason]}`, 'error', 4000);
          return false;
        }
        return true;
      },
    });
    const usable = triageFiles(files, names).usable.slice(0, MAX_PICK);
    u.addFiles(usable.map((f) => ({ name: f.name, type: f.type, data: f, source: 'Local' })));
    const sync = () => onChange(u.getFiles().map((f) => f.data as File));
    sync();
    u.on('file-added', sync);
    u.on('file-removed', sync);
    setUppy(u);
    onReady(u);
    return () => {
      u.off('file-added', sync);
      u.off('file-removed', sync);
      u.destroy();
      setUppy(null);
    };
    // A new pick is a new dashboard. `alreadyAttached` is read once: a release refreshes it, and that must not rebuild the tiles.
  }, [files]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="cam-intake-dashboard" data-testid="intake-dashboard">
      {uppy && <Dashboard
        uppy={uppy}
        height={300}
        width="100%"
        theme={theme}
        hideUploadButton
        showRemoveButtonAfterComplete
        proudlyDisplayPoweredByUppy={false}
        note="Spreadsheets (.xlsx .xls .csv), PDF, Word and text. Up to 25 MB each. Nothing is read before both security engines clear it."
      />}
    </div>
  );
}
