/**
 * The Changes tab's rules (SPEC-022), after BAM's SOW comparison: a baseline is chosen explicitly, and when there is nothing
 * earlier to compare with the answer is "nothing to compare", never a manufactured diff. Pure functions, unit tested.
 */

/** One hunk of Monaco's line diff (a line number of 0 on one side means that side has no lines in the hunk). */
export interface LineChange {
  originalStartLineNumber: number;
  originalEndLineNumber: number;
  modifiedStartLineNumber: number;
  modifiedEndLineNumber: number;
}
export interface ChangeCounts { added: number; removed: number; modified: number }

/** Lines added (only on the new side), removed (only on the old side) and modified (both sides, counted on the new side). */
export function summarizeLineChanges(changes: readonly LineChange[] | null | undefined): ChangeCounts {
  const c: ChangeCounts = { added: 0, removed: 0, modified: 0 };
  for (const h of changes ?? []) {
    const oldLines = h.originalEndLineNumber === 0 ? 0 : h.originalEndLineNumber - h.originalStartLineNumber + 1;
    const newLines = h.modifiedEndLineNumber === 0 ? 0 : h.modifiedEndLineNumber - h.modifiedStartLineNumber + 1;
    if (oldLines === 0) c.added += newLines;
    else if (newLines === 0) c.removed += oldLines;
    else c.modified += newLines;
  }
  return c;
}
export const totalChanges = (c: ChangeCounts) => c.added + c.removed + c.modified;

/** JSON re-printed with two-space indentation; null when the text is not JSON. Key order is kept. */
export function normalizeJson(text: string): string | null {
  try {
    return JSON.stringify(JSON.parse(text), null, 2) + '\n';
  } catch {
    return null;
  }
}

/**
 * The two texts to show. Saving rewrites a file's layout (the daemon re-prints it), so a raw comparison with an older version
 * would mark every line changed. When both sides are JSON they are compared on the same layout and the view says so.
 */
export function comparable(base: string, now: string): { base: string; now: string; normalized: boolean } {
  const a = normalizeJson(base);
  const b = normalizeJson(now);
  return a !== null && b !== null ? { base: a, now: b, normalized: true } : { base, now, normalized: false };
}

export type Baseline = 'saved' | 'previous';

/** What the chosen baseline lets the view show. `none` carries the reason, in words. */
export type BaselineText =
  | { kind: 'diff'; label: string; base: string }
  | { kind: 'none'; reason: string };

export function pickBaseline(choice: Baseline, savedText: string, previous: { text: string; savedAt: string } | null | 'loading' | 'error'): BaselineText {
  if (choice === 'saved') return { kind: 'diff', label: 'saved on disk', base: savedText };
  if (previous === 'loading') return { kind: 'none', reason: 'Loading the earlier saved versions...' };
  if (previous === 'error') return { kind: 'none', reason: 'The earlier saved versions could not be loaded.' };
  if (!previous) return { kind: 'none', reason: 'This file has no earlier saved version yet, so there is nothing to compare with. Your next save keeps the current one as the earlier version.' };
  return { kind: 'diff', label: `previous saved version (${new Date(previous.savedAt).toLocaleString()})`, base: previous.text };
}
