import { useEffect, useMemo, useState } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { fetchManifestHistory, fetchManifestVersion } from '@/lib/manifestsApi';
import { comparable, pickBaseline, summarizeLineChanges, totalChanges, type Baseline, type ChangeCounts, type LineChange } from '@/lib/manifestDiff';
import { cn } from '@/lib/utils';
import { modelPath } from './monacoSetup';
import { useMonacoTheme } from './useMonacoTheme';

interface Props {
  /** Manifest path, e.g. skills/skill_01_input_standardization.json */
  path: string;
  /** The text in the editor right now (saved or not). */
  current: string;
  /** The text as it is on disk. */
  saved: string;
}

type Previous = { text: string; savedAt: string } | null | 'loading' | 'error';

const CHOICES: { id: Baseline; label: string }[] = [
  { id: 'saved', label: 'Saved on disk' },
  { id: 'previous', label: 'Previous saved version' },
];

/** GitLens-style inline diff of the editor text against a chosen baseline: added, removed and modified lines, coloured, with counts. */
export function ChangesView({ path, current, saved }: Props) {
  const theme = useMonacoTheme();
  const [choice, setChoice] = useState<Baseline>('saved');
  const [previous, setPrevious] = useState<Previous>('loading');
  const [counts, setCounts] = useState<ChangeCounts | null>(null);

  // The newest earlier copy is the file as it was before the last save. Loaded when this tab opens, and again when the path or the
  // text on disk changes (a save makes a new earlier copy).
  useEffect(() => {
    let stopped = false;
    setPrevious('loading');
    fetchManifestHistory(path)
      .then(async (list) => (list.length ? fetchManifestVersion(path, list[0].stamp) : null))
      .then((v) => { if (!stopped) setPrevious(v ? { text: v.text, savedAt: v.savedAt } : null); })
      .catch(() => { if (!stopped) setPrevious('error'); });
    return () => { stopped = true; };
  }, [path, saved]);

  const baseline = pickBaseline(choice, saved, previous);
  const pair = useMemo(() => (baseline.kind === 'diff' ? comparable(baseline.base, current) : null), [baseline, current]);
  const same = pair !== null && pair.base === pair.now;

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="changes-view">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2 text-xs">
        <div role="group" aria-label="Compare the editor with" className="inline-flex rounded-full border border-border bg-muted/40 p-0.5">
          {CHOICES.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={choice === c.id}
              onClick={() => setChoice(c.id)}
              className={cn(
                'min-h-7 rounded-full px-3 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                choice === c.id ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
        <span className="inline-flex items-center gap-2" aria-label="Colour key">
          <ins className="rounded bg-emerald-500/20 px-1.5 text-emerald-800 no-underline dark:text-emerald-300">+ Added</ins>
          <del className="rounded bg-red-500/20 px-1.5 text-red-800 dark:text-red-300">&minus; Removed</del>
          <mark className="rounded bg-amber-500/25 px-1.5 text-amber-900 dark:text-amber-200">~ Modified</mark>
        </span>
        {baseline.kind === 'diff' && !same && counts && (
          <span role="status" className="font-medium text-foreground">
            {totalChanges(counts)} changed line{totalChanges(counts) === 1 ? '' : 's'}: {counts.added} added &middot; {counts.removed} removed &middot; {counts.modified} modified
          </span>
        )}
      </div>

      {baseline.kind === 'none' && <Note>{baseline.reason}</Note>}
      {baseline.kind === 'diff' && same && (
        <Note>
          {choice === 'saved'
            ? 'No unsaved changes: the editor matches the file on disk. Choose "Previous saved version" to see what the last save changed.'
            : 'The editor matches the previous saved version: nothing differs.'}
        </Note>
      )}
      {pair && !same && (
        <>
          <p className="border-b border-border bg-muted/30 px-3 py-1 text-xs text-muted-foreground">
            Baseline <b className="text-foreground">{baseline.kind === 'diff' ? baseline.label : ''}</b> &rarr; current editor text.
            {pair.normalized && ' Compared on the same JSON layout, so spacing and line breaks are ignored.'}
          </p>
          <div className="min-h-[240px] flex-1">
            <DiffEditor
              height="100%"
              language="json"
              theme={theme}
              original={pair.base}
              modified={pair.now}
              originalModelPath={`${modelPath(path)}?baseline`}
              modifiedModelPath={`${modelPath(path)}?current`}
              loading={<p className="p-4 text-sm text-muted-foreground">Loading comparison...</p>}
              onMount={(ed) => {
                const update = () => setCounts(summarizeLineChanges(ed.getLineChanges() as LineChange[] | null));
                ed.onDidUpdateDiff(update);
                update();
              }}
              options={{
                readOnly: true, originalEditable: false, renderSideBySide: false, renderIndicators: true, minimap: { enabled: false },
                fontSize: 13, scrollBeyondLastLine: false, automaticLayout: true, wordWrap: 'on', ignoreTrimWhitespace: false,
                ariaLabel: `Changes in ${path}`, fixedOverflowWidgets: true,
              }}
            />
          </div>
        </>
      )}
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="p-4 text-sm text-muted-foreground" role="note">{children}</p>;
}
