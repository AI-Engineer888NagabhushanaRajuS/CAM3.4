/**
 * SPEC-020 live changes: the four RFQ events (rfq:value-changed, rfq:reports-regenerating, rfq:reports-ready,
 * rfq:reports-failed) arrive on App.tsx's one root EventSource; App hands them to pushRfqChangeEvent and the right-pane
 * ChangesPanel reads them here. A tiny store (not React state in App) so no second connection and no prop drilling, and
 * events that arrive before the panel mounts are not lost. Frames are untrusted: every field is read defensively.
 */
export type RfqChangeKind = 'changed' | 'regenerating' | 'ready' | 'failed';

export interface RfqChangeEntry {
  id: number;
  kind: RfqChangeKind;
  at: number;
  /** What the timeline row says after its status word (Value changed, Regenerating, Reports ready, Failed). */
  text: string;
  filename?: string;
  totalChangedCells?: number;
  sheetCount?: number;
}

const EVENTS: Record<string, RfqChangeKind> = {
  'rfq:value-changed': 'changed',
  'rfq:reports-regenerating': 'regenerating',
  'rfq:reports-ready': 'ready',
  'rfq:reports-failed': 'failed',
};
const KEEP = 40;
const NONE: readonly RfqChangeEntry[] = Object.freeze([]);

const byRfq = new Map<string, readonly RfqChangeEntry[]>();
const listeners = new Set<() => void>();
let nextId = 1;

export const isRfqChangeEvent = (name: unknown): boolean => typeof name === 'string' && name in EVENTS;

const list = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => (typeof x === 'string' || typeof x === 'number' ? String(x) : (x as { field?: unknown; bom_item_id?: unknown })?.field ?? (x as { bom_item_id?: unknown })?.bom_item_id)).filter((x): x is string => typeof x === 'string' && x !== '') : []);
const count = (v: unknown): number | undefined => (Array.isArray(v) ? v.length : typeof v === 'number' && Number.isFinite(v) ? v : undefined);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

export function pushRfqChangeEvent(frame: unknown, now: number = Date.now()): void {
  const f = frame as Record<string, unknown> | null;
  const kind = typeof f?.event === 'string' ? EVENTS[f.event] : undefined;
  if (!f || !kind || typeof f.rfqId !== 'string' || !f.rfqId) {
    return;
  }
  let entry: RfqChangeEntry;
  if (kind === 'changed') {
    const fields = list(f.fields);
    const items = count(f.items);
    entry = { id: nextId++, kind, at: now, text: `${fields.length ? fields.join(', ') : 'a value'}${items !== undefined ? ` (${plural(items, 'item')})` : ''}` };
  } else if (kind === 'regenerating') {
    entry = { id: nextId++, kind, at: now, text: 'rebuilding the workbooks from the new value...' };
  } else if (kind === 'ready') {
    const filename = typeof f.filename === 'string' ? f.filename : undefined;
    const total = typeof f.totalChangedCells === 'number' ? f.totalChangedCells : undefined;
    const sheets = count(f.sheets);
    const cells = total === undefined ? 'no cell comparison' : `${plural(total, 'changed cell')}${sheets !== undefined ? ` across ${plural(sheets, 'sheet')}` : ''}`;
    entry = { id: nextId++, kind, at: now, text: `${filename ? `new version ${filename}, ` : ''}${cells}`, filename, totalChangedCells: total, sheetCount: sheets };
  } else {
    entry = { id: nextId++, kind, at: now, text: typeof f.message === 'string' && f.message ? f.message : 'no reason given' };
  }
  byRfq.set(f.rfqId, [...(byRfq.get(f.rfqId) ?? NONE), entry].slice(-KEEP));
  listeners.forEach((l) => l());
}

export const getRfqChanges = (rfqId: string): readonly RfqChangeEntry[] => byRfq.get(rfqId) ?? NONE;

export function subscribeRfqChanges(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Tests only. */
export function resetRfqChanges(): void {
  byRfq.clear();
  listeners.forEach((l) => l());
}
