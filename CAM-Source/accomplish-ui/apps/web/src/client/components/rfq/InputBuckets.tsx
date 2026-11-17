import { useState, type DragEvent } from 'react';
import { FileText } from '@phosphor-icons/react';

/**
 * The input buckets of the scan dialog: each picked file is dragged onto the input it belongs to. Required inputs are red until they have a
 * file; optional ones are grey. A file in no bucket is "Not sorted" and the scan decides its role itself, as before.
 */
export type BucketKey = 'bom' | 'volume' | 'quotewin' | 'costing' | 'gerber';

export const BUCKET_DEFS: { key: BucketKey; label: string; required: boolean; why: string }[] = [
  { key: 'bom', label: 'BOM', required: true, why: 'Scrub BOM workbook. The run needs it.' },
  { key: 'quotewin', label: 'QuoteWin export', required: true, why: 'Prices the parts. Kept for the RFQ and attached to its BOM.' },
  { key: 'volume', label: 'Volume', required: false, why: 'Optional: the default pipeline reads volumes from the BOM.' },
  { key: 'costing', label: 'Costing sheet', required: false, why: 'Optional extra costing input, kept with the QuoteWin.' },
  { key: 'gerber', label: 'Gerber ZIP', required: false, why: 'Optional. Without it feature extraction is skipped.' },
];

export type Assignment = Record<string, BucketKey | undefined>;

interface Props {
  names: string[];
  assignment: Assignment;
  onAssign: (name: string, key: BucketKey | undefined) => void;
}

export function InputBuckets({ names, assignment, onAssign }: Props) {
  const [over, setOver] = useState<string | null>(null);
  const unsorted = names.filter((n) => !assignment[n]);

  const dragStart = (e: DragEvent, name: string) => {
    e.dataTransfer.setData('text/plain', name);
    e.dataTransfer.effectAllowed = 'move';
  };
  const drop = (e: DragEvent, key: BucketKey | undefined) => {
    e.preventDefault();
    setOver(null);
    const name = e.dataTransfer.getData('text/plain');
    if (name && names.includes(name)) onAssign(name, key);
  };
  const zone = (key: BucketKey | undefined) => ({
    onDragOver: (e: DragEvent) => { e.preventDefault(); setOver(key ?? 'unsorted'); },
    onDragLeave: () => setOver(null),
    onDrop: (e: DragEvent) => drop(e, key),
  });

  const chip = (name: string) => (
    <li key={name}>
      <div
        draggable
        onDragStart={(e) => dragStart(e, name)}
        className="flex max-w-full cursor-grab items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs text-foreground active:cursor-grabbing"
        title={`Drag ${name} into its bucket`}
      >
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 truncate">{name}</span>
      </div>
    </li>
  );

  return (
    <section aria-label="Input buckets" className="space-y-2" data-testid="input-buckets">
      <p className="text-xs text-muted-foreground">Drag each file into the input it is. Red inputs are required.</p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {BUCKET_DEFS.map((b) => {
          const mine = names.filter((n) => assignment[n] === b.key);
          const filled = mine.length > 0;
          const hot = over === b.key;
          const tone = filled
            ? 'border-emerald-500/60 bg-emerald-500/5'
            : b.required ? 'border-destructive/70 bg-destructive/5' : 'border-dashed border-border bg-muted/30';
          return (
            <div
              key={b.key}
              data-testid={`scan-bucket-${b.key}`}
              {...zone(b.key)}
              className={`min-h-[84px] rounded-lg border-2 p-2 transition-colors ${tone} ${hot ? 'ring-2 ring-primary/50' : ''}`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-foreground">{b.label}</p>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${b.required ? (filled ? 'bg-emerald-500/15 text-emerald-700' : 'bg-destructive/15 text-destructive') : 'bg-muted text-muted-foreground'}`}>
                  {b.required ? (filled ? 'Ready' : 'Required') : 'Optional'}
                </span>
              </div>
              <ul className="mt-1.5 space-y-1">
                {mine.map((n) => chip(n))}
                {!filled && <li className="text-[11px] text-muted-foreground">{b.why}</li>}
              </ul>
            </div>
          );
        })}
      </div>
      <div
        data-testid="scan-bucket-unsorted"
        {...zone(undefined)}
        className={`rounded-lg border border-dashed border-border p-2 ${over === 'unsorted' ? 'ring-2 ring-primary/50' : ''}`}
      >
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Not sorted ({unsorted.length})</p>
        <ul className="mt-1.5 flex flex-wrap gap-1.5">
          {unsorted.length ? unsorted.map((n) => chip(n)) : <li className="text-[11px] text-muted-foreground">Drop a file here to take it out of its bucket.</li>}
        </ul>
      </div>
    </section>
  );
}
