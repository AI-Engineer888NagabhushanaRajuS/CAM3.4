import { useMemo, useState } from 'react';
import { CheckCircle, Hourglass, MagnifyingGlass, Stack } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { scopeFromIds, type ChatScope, type RfqOption } from '@/lib/chatContract';

interface RfqPickerDialogProps {
  /** Why the assistant needs a choice (from the daemon). */
  reason: string;
  options: RfqOption[];
  /** RFQs already in scope: ticked when the popup opens. */
  initial: string[];
  onPick: (scope: ChatScope) => void;
  /** Esc, the close button, Cancel or a click outside: the scope stays as it was. */
  onCancel: () => void;
}

const badge = 'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium';
const matches = (o: RfqOption, q: string) => [o.rfqId, o.customer, o.project].some((v) => v?.toLowerCase().includes(q));

/** The popup the assistant opens when a question needs RFQ data and none is chosen: tick RFQs, or use All context. */
export function RfqPickerDialog({ reason, options, initial, onPick, onCancel }: RfqPickerDialogProps) {
  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(initial));
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => matches(o, q)) : options;
  }, [options, query]);
  const toggle = (id: string) => setChosen((s) => { const n = new Set(s); if (!n.delete(id)) n.add(id); return n; });

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="max-h-[90dvh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Stack className="h-5 w-5 text-primary" weight="fill" aria-hidden />Choose RFQs</DialogTitle>
          <DialogDescription className="break-words">{reason}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <MagnifyingGlass className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search RFQs by id, customer or project" placeholder="Search by id, customer or project" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span aria-live="polite">{shown.length} of {options.length} RFQs{chosen.size > 0 && ` · ${chosen.size} selected`}</span>
          <button type="button" className="min-h-6 px-1 hover:text-foreground disabled:opacity-50" disabled={chosen.size === 0} onClick={() => setChosen(new Set())}>Clear selection</button>
        </div>
        <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-xl border border-border" aria-label="RFQs">
          {shown.map((o) => (
            <li key={o.rfqId}>
              <label className="flex min-h-10 cursor-pointer items-start gap-3 px-3 py-2 hover:bg-accent/50 has-[:focus-visible]:bg-accent/50">
                <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-primary" checked={chosen.has(o.rfqId)} onChange={() => toggle(o.rfqId)} />
                <span className="min-w-0 flex-1">
                  <span className="block break-all text-sm font-medium text-foreground">{o.rfqId}</span>
                  <span className="block break-words text-xs text-muted-foreground">{[o.customer, o.project].filter(Boolean).join(' · ') || 'No customer or project recorded'}</span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    <span className={`${badge} border-border text-muted-foreground`}>{o.stage === null ? 'Not started' : `Steps done: ${o.stage}`}</span>
                    {o.reviewPending && (
                      <span className={`${badge} border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400`}><Hourglass className="h-3 w-3" aria-hidden />Review pending</span>
                    )}
                    <span className={`${badge} ${o.hasExport ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' : 'border-border text-muted-foreground'}`}>
                      {o.hasExport && <CheckCircle className="h-3 w-3" aria-hidden />}
                      {o.hasExport ? 'Export available' : 'No export yet'}
                    </span>
                  </span>
                </span>
              </label>
            </li>
          ))}
          {shown.length === 0 && <li className="px-3 py-4 text-center text-sm text-muted-foreground">{options.length === 0 ? 'No RFQs to list yet.' : 'No RFQ matches this search.'}</li>}
        </ul>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button variant="outline" disabled={chosen.size === 0} onClick={() => onPick(scopeFromIds([...chosen]))}>Use selected ({chosen.size})</Button>
          <Button onClick={() => onPick({ mode: 'all' })}>All context</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
