import { useEffect, useMemo, useRef, useState } from 'react';
import { CircleNotch, FileText, ShieldCheck, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { fitsOneScan, formatBytes, MAX_FILES, REJECT_TEXT, scanFiles, triageFiles, type ScanResponse } from '@/lib/rfqAttachments';
import { ScanResults } from './ScanResults';

type Phase = 'review' | 'scanning' | 'result';

interface AttachFilesDialogProps {
  open: boolean;
  rfqId: string;
  /** What the user picked or dropped. */
  files: File[];
  /** Names already released for this RFQ, so a second copy is turned away. */
  alreadyAttached: string[];
  onClose: () => void;
  /** At least one file was released: refresh the list of context files. */
  onReleased: () => void;
}

const STEPS = ['Select', 'Quarantine', 'BuLL*Sav', 'Repel', 'Verdict'] as const;
const LIST_CAP = 200; // rows drawn; a folder drop can hold thousands

/** The five stages of the perimeter. Quarantine to Repel run together on the server, so they are shown as one running block. */
function Steps({ phase, response }: { phase: Phase; response: ScanResponse | null }) {
  const failed = response?.engines.some((e) => e.status !== 'ok') ?? false;
  const state = (i: number) =>
    phase === 'review' ? (i === 0 ? 'now' : 'todo')
    : phase === 'scanning' ? (i === 0 ? 'done' : i < 4 ? 'now' : 'todo')
    : i === 2 || i === 3 ? (failed ? 'alert' : 'done') : 'done';
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-[11px]" aria-label="Security pipeline">
      {STEPS.map((label, i) => (
        <li key={label} className="flex items-center gap-1.5" aria-current={state(i) === 'now' ? 'step' : undefined}>
          <span className={cn('rounded-full border px-2 py-0.5 font-medium', {
            'border-primary/40 bg-primary/10 text-primary': state(i) === 'now',
            'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400': state(i) === 'done',
            'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400': state(i) === 'alert',
            'border-border text-muted-foreground': state(i) === 'todo',
          })}>
            {label}
            <span className="sr-only"> ({{ now: 'in progress', done: 'done', alert: 'needs attention', todo: 'not started' }[state(i)]})</span>
          </span>
          {i < STEPS.length - 1 && <span aria-hidden className="h-px w-3 bg-border" />}
        </li>
      ))}
    </ol>
  );
}

/** Select or reject what was picked, then run both security engines on the rest. Nothing reaches the assistant before that. */
export function AttachFilesDialog({ open, rfqId, files, alreadyAttached, onClose, onReleased }: AttachFilesDialogProps) {
  const triage = useMemo(() => triageFiles(files, alreadyAttached), [files, alreadyAttached]);
  const [chosen, setChosen] = useState<Set<File>>(new Set());
  const [phase, setPhase] = useState<Phase>('review');
  const [response, setResponse] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    setChosen(new Set(triage.usable.slice(0, MAX_FILES)));
    setPhase('review');
    setResponse(null);
    setError(null);
  }, [triage]);

  const picked = triage.usable.filter((f) => chosen.has(f));
  const fit = fitsOneScan(picked);
  const toggle = (f: File) => setChosen((s) => { const n = new Set(s); if (!n.delete(f)) n.add(f); return n; });

  const run = async () => {
    const controller = new AbortController();
    abort.current = controller;
    setError(null);
    setPhase('scanning');
    try {
      const out = await scanFiles(rfqId, picked, controller.signal);
      setResponse(out);
      setPhase('result');
      if (out.results.some((r) => r.decision === 'released')) onReleased();
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : 'The scan failed');
      setPhase('review');
    } finally {
      abort.current = null;
    }
  };

  const close = () => {
    abort.current?.abort();
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close(); }}>
      <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" weight="fill" aria-hidden />
            {phase === 'review' ? 'Review files before they reach the assistant' : phase === 'scanning' ? 'Scanning with both engines…' : 'Scan complete'}
          </DialogTitle>
          <DialogDescription>
            BuLL*Sav (ClamAV signatures) and Repel Shield (macros, injected instructions, disguised files) both check every file. A file is released only if both pass; a problem with either engine holds it.
          </DialogDescription>
        </DialogHeader>
        <Steps phase={phase} response={response} />

        {phase === 'review' && (
          <div className="space-y-3">
            {error && (
              <p role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
                <WarningCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                {error}. Nothing was released.
              </p>
            )}
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{picked.length} of {triage.usable.length} selected{triage.rejected.length > 0 && ` · ${triage.rejected.length} rejected`}</span>
              <span className="flex gap-3">
                <button type="button" className="hover:text-foreground" onClick={() => setChosen(new Set(triage.usable.slice(0, MAX_FILES)))}>Select all</button>
                <button type="button" className="hover:text-foreground" onClick={() => setChosen(new Set())}>Clear</button>
              </span>
            </div>
            <ul className="max-h-60 divide-y divide-border overflow-y-auto rounded-xl border border-border">
              {triage.usable.slice(0, LIST_CAP).map((f) => (
                <li key={`${f.name}-${f.size}-${f.lastModified}`}>
                  <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-accent/50">
                    <input type="checkbox" className="h-4 w-4 accent-primary" checked={chosen.has(f)} onChange={() => toggle(f)} aria-label={`Send ${f.name}`} />
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate text-sm text-foreground" title={f.name}>{f.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(f.size)}</span>
                  </label>
                </li>
              ))}
              {triage.usable.length === 0 && <li className="px-3 py-4 text-center text-sm text-muted-foreground">None of these files can be sent.</li>}
              {triage.usable.length > LIST_CAP && <li className="px-3 py-2 text-center text-xs text-muted-foreground">{triage.usable.length - LIST_CAP} more not listed: at most {MAX_FILES} are sent per scan.</li>}
            </ul>
            {triage.rejected.length > 0 && (
              <details open={triage.usable.length === 0} className="text-xs text-muted-foreground">
                <summary className="cursor-pointer select-none">Rejected ({triage.rejected.length}): not sent</summary>
                <ul className="mt-1.5 space-y-1">
                  {triage.rejected.map(({ file, reason }) => (
                    <li key={`${file.name}-${file.size}`} className="flex gap-2"><span className="truncate text-foreground" title={file.name}>{file.name}</span><span>{REJECT_TEXT[reason]}</span></li>
                  ))}
                </ul>
              </details>
            )}
            {!fit.ok && picked.length > 0 && <p className="text-xs text-destructive">{fit.reason}</p>}
          </div>
        )}

        {phase === 'scanning' && (
          <div className="space-y-2" role="status">
            <p className="flex items-center gap-2 text-sm text-foreground"><CircleNotch className="h-4 w-4 animate-spin motion-reduce:animate-none" />Quarantining and scanning {picked.length} {picked.length === 1 ? 'file' : 'files'}…</p>
            <ul className="space-y-1 text-xs text-muted-foreground">{picked.map((f) => <li key={f.name} className="truncate">{f.name}</li>)}</ul>
          </div>
        )}

        {phase === 'result' && response && <ScanResults response={response} />}

        <DialogFooter className="gap-2 sm:gap-0">
          {phase === 'result' ? (
            <Button onClick={close}>Done</Button>
          ) : (
            <>
              <Button variant="outline" onClick={close}>Cancel</Button>
              {phase === 'review' && <Button onClick={() => void run()} disabled={!fit.ok}>Scan {picked.length || ''} {picked.length === 1 ? 'file' : 'files'}</Button>}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
