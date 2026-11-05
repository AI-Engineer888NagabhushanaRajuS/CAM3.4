import { useEffect, useMemo, useRef, useState } from 'react';
import { CircleNotch, FileText, ShieldCheck, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { formatBytes, MAX_PICK, planWaves, REJECT_TEXT, triageFiles, type ScanResponse } from '@/lib/rfqAttachments';
import { scanInWaves, type WaveOutcome } from '@/lib/scanWaves';
import { PerimeterSteps, type Phase } from './PerimeterSteps';
import { ScanResults } from './ScanResults';

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

const LIST_CAP = 200; // rows drawn; a folder drop can hold thousands

/** Select or reject what was picked, then run both security engines on the rest. Nothing reaches the assistant before that. */
export function AttachFilesDialog({ open, rfqId, files, alreadyAttached, onClose, onReleased }: AttachFilesDialogProps) {
  // Triage only when a NEW pick arrives. A release refreshes `alreadyAttached`; recomputing then would reset the dialog
  // to "review" and show the just-released files as "already attached", hiding their verdicts.
  const attached = useRef(alreadyAttached);
  attached.current = alreadyAttached;
  const triage = useMemo(() => triageFiles(files, attached.current), [files]);
  const [chosen, setChosen] = useState<Set<File>>(new Set());
  const [phase, setPhase] = useState<Phase>('review');
  const [response, setResponse] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wave, setWave] = useState({ n: 1, of: 1 });
  const [failure, setFailure] = useState<WaveOutcome['failure']>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    setChosen(new Set(triage.usable.slice(0, MAX_PICK)));
    setPhase('review');
    setResponse(null);
    setError(null);
    setFailure(null);
  }, [triage]);

  const picked = triage.usable.filter((f) => chosen.has(f));
  const waves = planWaves(picked).waves.length;
  const fit = picked.length === 0 ? { ok: false, reason: 'Select at least one file' }
    : picked.length > MAX_PICK ? { ok: false, reason: `${picked.length} selected; at most ${MAX_PICK} at a time. Untick ${picked.length - MAX_PICK}.` }
    : { ok: true, reason: '' };
  const toggle = (f: File) => setChosen((s) => { const n = new Set(s); if (!n.delete(f)) n.add(f); return n; });

  const run = async () => {
    const controller = new AbortController();
    abort.current = controller;
    setError(null);
    setFailure(null);
    setWave({ n: 1, of: waves });
    setPhase('scanning');
    try {
      const out = await scanInWaves(rfqId, picked, { signal: controller.signal, onWave: (n, of) => setWave({ n, of }) });
      if (out.response?.results.some((r) => r.decision === 'released')) onReleased();
      if (out.failure && !out.response) throw new Error(out.failure.message);
      setResponse(out.response);
      setFailure(out.failure);
      setPhase('result');
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
        <PerimeterSteps phase={phase} engines={response?.engines} />

        {phase === 'review' && (
          <div className="space-y-3">
            {error && (
              <p role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
                <WarningCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                {error}. Nothing was released.
              </p>
            )}
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{picked.length} of {triage.usable.length} selected{triage.rejected.length > 0 && ` · ${triage.rejected.length} rejected`}{waves > 1 && ` · sent in ${waves} waves`}</span>
              <span className="flex gap-3">
                <button type="button" className="hover:text-foreground" onClick={() => setChosen(new Set(triage.usable.slice(0, MAX_PICK)))}>Select all</button>
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
              {triage.usable.length > LIST_CAP && <li className="px-3 py-2 text-center text-xs text-muted-foreground">{triage.usable.length - LIST_CAP} more not listed: at most {MAX_PICK} are sent at a time.</li>}
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
            <p className="flex items-center gap-2 text-sm text-foreground"><CircleNotch className="h-4 w-4 animate-spin motion-reduce:animate-none" />{wave.of > 1 ? `Wave ${wave.n} of ${wave.of}: ` : ''}Quarantining and scanning {picked.length} {picked.length === 1 ? 'file' : 'files'}…</p>
            <ul className="space-y-1 text-xs text-muted-foreground">{(wave.of > 1 ? planWaves(picked).waves[wave.n - 1] ?? [] : picked).map((f) => <li key={f.name} className="truncate">{f.name}</li>)}</ul>
          </div>
        )}

        {phase === 'result' && response && <ScanResults response={response} />}
        {phase === 'result' && failure && (
          <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
            <p className="flex items-start gap-2"><WarningCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />Wave {failure.wave} of {failure.waves} failed: {failure.message}. The remaining waves were not run. These {failure.unsent.length} files were never scanned or released:</p>
            <ul className="mt-1 max-h-24 overflow-y-auto pl-6">{failure.unsent.map((f) => <li key={f.name} className="truncate">{f.name}</li>)}</ul>
          </div>
        )}

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
