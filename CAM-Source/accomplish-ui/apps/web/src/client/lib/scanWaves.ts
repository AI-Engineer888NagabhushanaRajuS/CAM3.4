/** Runs a pick that is over one scan's limits as sequential waves and merges the verdicts (see planWaves). */
import { planWaves, scanFiles, type ScanResponse } from './rfqAttachments';

export interface WaveOutcome {
  /** Verdicts of every wave that completed, merged; null when the first wave already failed. */
  response: ScanResponse | null;
  /** A wave failed: the rest was never sent. `unsent` is that wave's files and every later one. */
  failure: { message: string; wave: number; waves: number; unsent: File[] } | null;
}

/** Scans the waves one after another. A failed wave stops the rest; an abort is rethrown. */
export async function scanInWaves(
  rfqId: string,
  files: File[],
  opts: { signal?: AbortSignal; onWave?: (wave: number, waves: number) => void; acceptRisk?: string[] } = {},
): Promise<WaveOutcome> {
  const { waves } = planWaves(files);
  let response: ScanResponse | null = null;
  for (let i = 0; i < waves.length; i++) {
    opts.onWave?.(i + 1, waves.length);
    try {
      const out = await scanFiles(rfqId, waves[i], opts.signal, opts.acceptRisk ?? []);
      response = response ? { ...out, results: [...response.results, ...out.results] } : out;
    } catch (err) {
      if (opts.signal?.aborted) throw err;
      const message = err instanceof Error ? err.message : 'The scan failed';
      return { response, failure: { message, wave: i + 1, waves: waves.length, unsent: waves.slice(i).flat() } };
    }
  }
  return { response, failure: null };
}
