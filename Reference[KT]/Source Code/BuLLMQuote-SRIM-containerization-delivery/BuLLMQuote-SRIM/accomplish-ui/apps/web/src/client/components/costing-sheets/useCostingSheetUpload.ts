import { useCallback, useRef, useState } from 'react';
import { MAX_FILE_SIZE, formatFileSize } from '@/lib/fileUtils';

export type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';

export interface CostingSheetUploadState {
  file: File | null;
  status: UploadStatus;
  progress: number;
  error: string | null;
}

const PROGRESS_TICK_MS = 150;
const PROGRESS_STEP = 18;

/**
 * Per-card upload state + simulated transport.
 *
 * PLACEHOLDER: no backend endpoint exists yet for costing-sheet uploads.
 * `simulateUpload` is the single swap point — replace its body with a real
 * `fetch(...)`/XHR call (reporting real progress) once the API ships.
 */
export function useCostingSheetUpload() {
  const [state, setState] = useState<CostingSheetUploadState>({
    file: null,
    status: 'idle',
    progress: 0,
    error: null,
  });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const simulateUpload = useCallback((file: File) => {
    clearTimer();
    setState({ file, status: 'uploading', progress: 0, error: null });

    timerRef.current = setInterval(() => {
      setState((prev) => {
        if (prev.status !== 'uploading') {
          return prev;
        }
        const next = Math.min(100, prev.progress + PROGRESS_STEP);
        if (next >= 100) {
          clearTimer();
          return { ...prev, progress: 100, status: 'success' };
        }
        return { ...prev, progress: next };
      });
    }, PROGRESS_TICK_MS);
  }, [clearTimer]);

  const selectFile = useCallback(
    (file: File) => {
      if (file.size > MAX_FILE_SIZE) {
        clearTimer();
        setState({
          file,
          status: 'error',
          progress: 0,
          error: `File exceeds the ${formatFileSize(MAX_FILE_SIZE)} limit`,
        });
        return;
      }
      simulateUpload(file);
    },
    [clearTimer, simulateUpload],
  );

  const removeFile = useCallback(() => {
    clearTimer();
    setState({ file: null, status: 'idle', progress: 0, error: null });
  }, [clearTimer]);

  return { ...state, selectFile, removeFile };
}
