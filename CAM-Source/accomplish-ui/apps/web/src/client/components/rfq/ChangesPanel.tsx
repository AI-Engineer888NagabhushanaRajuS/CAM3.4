import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { ArrowsClockwise, CaretDown, CaretRight, CheckCircle, DownloadSimple, PencilSimple, WarningCircle } from '@phosphor-icons/react';
import { PYTHON_BRIDGE_URL } from '@/config/endpoints';
import { authDownload, authFetch } from '@/lib/apiAuth';
import { getRfqChanges, subscribeRfqChanges, type RfqChangeEntry, type RfqChangeKind } from '@/lib/rfqChanges';
import { downloadReports } from './OpenDirectives';

export interface ExportVersion {
  filename: string;
  generated_at: string;
  diff_summary: unknown;
}

const KIND: Record<RfqChangeKind, { word: string; Icon: typeof CheckCircle; tone: string }> = {
  changed: { word: 'Value changed', Icon: PencilSimple, tone: 'text-foreground' },
  regenerating: { word: 'Regenerating', Icon: ArrowsClockwise, tone: 'text-primary' },
  ready: { word: 'Reports ready', Icon: CheckCircle, tone: 'text-emerald-700 dark:text-emerald-400' },
  failed: { word: 'Failed', Icon: WarningCircle, tone: 'text-destructive' },
};
const BUTTON = 'inline-flex min-h-6 min-w-6 items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs font-semibold text-foreground hover:bg-muted disabled:opacity-50';

/** One sentence for a version's diff_summary: a string as sent, or the counts of { total_changed_cells, sheets }; null = the first version. */
export function describeDiff(d: unknown): string {
  if (typeof d === 'string' && d.trim()) return d;
  const o = d as { total_changed_cells?: unknown; totalChangedCells?: unknown; sheets?: unknown } | null;
  const total = o?.total_changed_cells ?? o?.totalChangedCells;
  if (typeof total !== 'number') return 'First version, nothing to compare with';
  const sheets = Array.isArray(o?.sheets) ? o.sheets.length : typeof o?.sheets === 'number' ? o.sheets : null;
  return `${total} changed cell${total === 1 ? '' : 's'}${sheets === null ? '' : ` across ${sheets} sheet${sheets === 1 ? '' : 's'}`}`;
}

/** Downloads one stored version. Assumption: the bridge serves it at /api/rfq/{id}/exports/{filename}/download (SPEC-020 contract lists only the listing). */
export const downloadVersion = (rfqId: string, filename: string): Promise<void> =>
  authDownload(`${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/exports/${encodeURIComponent(filename)}/download`, rfqId, filename);

function Download({ label, run }: { label: string; run: () => Promise<void> }) {
  const [state, setState] = useState<'idle' | 'working' | 'failed'>('idle');
  const click = async () => {
    setState('working');
    try {
      await run();
      setState('idle');
    } catch {
      setState('failed');
    }
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <button type="button" className={BUTTON} disabled={state === 'working'} onClick={() => void click()}>
        <DownloadSimple className="h-3.5 w-3.5" aria-hidden />
        {state === 'working' ? 'Downloading...' : label}
      </button>
      {state === 'failed' && <span role="alert" className="text-xs font-medium text-destructive">Download failed</span>}
    </span>
  );
}

function Row({ e, rfqId }: { e: RfqChangeEntry; rfqId: string }) {
  const { word, Icon, tone } = KIND[e.kind];
  return (
    <li className="flex flex-wrap items-start gap-x-2 gap-y-1 text-xs">
      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${tone}`} weight="fill" aria-hidden />
      <span className="min-w-0 flex-1 break-words text-foreground">
        <strong className={`font-semibold ${tone}`}>{word}:</strong> {e.text}
        <span className="ml-1.5 text-muted-foreground">{new Date(e.at).toLocaleTimeString()}</span>
      </span>
      {e.kind === 'ready' && <Download label="Download" run={() => downloadReports(rfqId)} />}
    </li>
  );
}

/** GET /api/rfq/{id}/exports: newest first. `refresh` changes when a new version is announced, which re-reads the list. */
export function VersionsList({ rfqId, refresh }: { rfqId: string; refresh: number }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<{ rows: ExportVersion[] | null; error: string }>({ rows: null, error: '' });
  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/exports`, rfqId);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as unknown;
      setState({ rows: Array.isArray(body) ? (body as ExportVersion[]) : [], error: '' });
    } catch (err) {
      setState({ rows: null, error: err instanceof Error ? err.message : 'The request failed' });
    }
  }, [rfqId]);
  useEffect(() => {
    if (open) void load();
  }, [open, load, refresh]);

  const { rows, error } = state;
  return (
    <div>
      <button type="button" className="inline-flex min-h-6 items-center gap-1 text-xs font-semibold text-foreground" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? <CaretDown className="h-3.5 w-3.5" aria-hidden /> : <CaretRight className="h-3.5 w-3.5" aria-hidden />}
        Versions{rows ? ` (${rows.length})` : ''}
      </button>
      {open && (
        <div className="mt-1.5 space-y-1.5">
          {error && <p role="alert" className="text-xs font-medium text-destructive">Could not load the versions: {error}</p>}
          {!error && rows === null && <p role="status" className="text-xs text-muted-foreground">Loading versions...</p>}
          {rows?.length === 0 && <p className="text-xs text-muted-foreground">No exported versions yet.</p>}
          {rows && rows.length > 0 && (
            <ul className="space-y-1.5" aria-label="Versions">
              {rows.map((v, i) => (
                <li key={v.filename} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                  <span className="min-w-0 flex-1 break-words">
                    <span className="font-mono text-foreground">{v.filename}</span>
                    {i === 0 && <strong className="ml-1.5 font-semibold text-emerald-700 dark:text-emerald-400">Latest</strong>}
                    <span className="block text-muted-foreground">{new Date(v.generated_at).toLocaleString()}: {describeDiff(v.diff_summary)}</span>
                  </span>
                  <Download label="Download" run={() => downloadVersion(rfqId, v.filename)} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Right pane, under the progress log: what changed for this RFQ, live, and the versions of its reports. */
export function ChangesPanel({ rfqId }: { rfqId: string }) {
  const entries = useSyncExternalStore(subscribeRfqChanges, () => getRfqChanges(rfqId));
  if (!rfqId) return null;
  const ready = entries.filter((e) => e.kind === 'ready').length;
  return (
    <section className="mx-5 mb-5 mt-3 space-y-2 rounded-xl border border-border bg-card p-3" aria-label="Live changes">
      <h3 className="text-xs font-bold text-foreground">Live changes</h3>
      <div aria-live="polite">
        {entries.length === 0 ? (
          <p className="text-xs text-muted-foreground">No value changes yet for {rfqId}. Changes appear here as they happen.</p>
        ) : (
          <ol className="space-y-1.5" aria-label="Changes">
            {entries.map((e) => <Row key={e.id} e={e} rfqId={rfqId} />)}
          </ol>
        )}
      </div>
      <VersionsList rfqId={rfqId} refresh={ready} />
    </section>
  );
}
