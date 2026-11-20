import { useEffect, useMemo, useRef, useState } from 'react';
import type Uppy from '@uppy/core';
import { RocketLaunch, ShieldCheck, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { PYTHON_BRIDGE_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { fixQueueOf, intakeReadiness, MAX_PICK, planWaves, REJECT_TEXT, triageFiles, type ScanResponse } from '@/lib/rfqAttachments';
import { scanInWaves, type WaveOutcome } from '@/lib/scanWaves';
import { stageInput, type StagedRole } from '@/lib/intakeInputs';
import { IntakeDashboard } from './IntakeDashboard';
import { InputBuckets, type Assignment } from './InputBuckets';
import { PerimeterSteps, type Phase } from './PerimeterSteps';
import { ScanProgress } from './ScanProgress';
import { WorkbookEditor } from './WorkbookEditor';
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
  /** "Create RFQ from these files": the pane sends the sentence to the assistant, whose confirmation card still comes first. */
  onCreateRfq?: () => void;
  /** The Create RFQ window: hand over the scanned, released BOM workbook (and volume, quotewin, costing when present) as real Files. */
  onUseFiles?: (use: { bom: File; volume: File | null; quotewin?: File | null; costing?: File | null }) => void;
}

/** Pick on the Uppy dashboard (tiles you can remove or add to), then run both security engines on the rest. Nothing reaches the assistant before that. */
export function AttachFilesDialog({ open, rfqId, files, alreadyAttached, onClose, onReleased, onCreateRfq, onUseFiles }: AttachFilesDialogProps) {
  // Triage only when a NEW pick arrives. A release refreshes `alreadyAttached`; recomputing then would reset the dialog
  // to "review" and show the just-released files as "already attached", hiding their verdicts.
  const attached = useRef(alreadyAttached);
  attached.current = alreadyAttached;
  const triage = useMemo(() => triageFiles(files, attached.current), [files]);
  const [picked, setPicked] = useState<File[]>([]);
  const uppy = useRef<Uppy | null>(null);
  const [phase, setPhase] = useState<Phase>('review');
  const [response, setResponse] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wave, setWave] = useState({ n: 1, of: 1 });
  // What the progress list shows: every picked file on a scan, only the flagged ones on "Run anyway" (it never re-scans the clean ones,
  // but the list used to show all of them as scanning again, 2026-11-19).
  const [scanning, setScanning] = useState<File[]>([]);
  const [failure, setFailure] = useState<WaveOutcome['failure']>(null);
  // The files that need a workbook fix, one popup each, back to back: one file = one popup, three = three, all = all.
  // A file leaves the queue once its popup is closed or its corrected copy is saved (previousId marks it done).
  const [fixDone, setFixDone] = useState<Set<string>>(new Set());
  const fixQueue = phase === 'result' && response ? fixQueueOf(response.results, fixDone) : [];
  const fixTarget = fixQueue[0] ?? null;
  const [assignment, setAssignment] = useState<Assignment>({});
  const [kept, setKept] = useState<{ names: string[]; failed: string[] } | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    setPhase('review');
    setResponse(null);
    setError(null);
    setFailure(null);
  }, [triage]);

  const waves = planWaves(picked).waves.length;
  const fit = picked.length === 0 ? { ok: false, reason: 'Add at least one file' }
    : picked.length > MAX_PICK ? { ok: false, reason: `${picked.length} selected; at most ${MAX_PICK} at a time. Remove ${picked.length - MAX_PICK}.` }
    : { ok: true, reason: '' };
  const readiness = response ? intakeReadiness(response.results) : null;

  const run = async () => {
    const controller = new AbortController();
    abort.current = controller;
    setError(null);
    setFailure(null);
    setWave({ n: 1, of: waves });
    setScanning(picked);
    setPhase('scanning');
    try {
      const out = await scanInWaves(rfqId, picked, { signal: controller.signal, onWave: (n, of) => setWave({ n, of }) });
      if (out.response?.results.some((r) => r.decision === 'released')) onReleased();
      if (out.failure && !out.response) throw new Error(out.failure.message);
      if (out.response) setKept(await keepReleasedInputs(out.response));
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

  /**
   * A released QuoteWin or costing sheet (by its bucket, or by the role the scan gave it) is kept for the RFQ on the server, so the run
   * attaches it to its BOM and never asks for it again. Only released files are kept: a held file never reaches the RFQ.
   */
  /** Which kept input a released file is: the bucket it was dropped in, else what the scan recognised (a QuoteWin), else its name. */
  const keptKeyOf = (r: ScanResponse['results'][number]): StagedRole | undefined => {
    const assigned = assignment[r.name];
    if (assigned === 'quotewin' || assigned === 'costing') return assigned;
    if (assigned) return undefined;
    // A costing sheet can be recognised as a QuoteWin export, so its name is checked first.
    if (/costing/i.test(r.name)) return 'costing';
    if (r.role === 'quotewin') return 'quotewin';
    return undefined;
  };

  const keepReleasedInputs = async (resp: ScanResponse): Promise<{ names: string[]; failed: string[] }> => {
    const names: string[] = [];
    const failed: string[] = [];
    for (const r of resp.results) {
      if (r.decision !== 'released') continue;
      const key = keptKeyOf(r);
      if (!key) continue;
      const file = picked.find((f) => f.name === r.name);
      if (!file) continue;
      try {
        await stageInput(rfqId, key, file);
        names.push(r.name);
      } catch (err) {
        failed.push(err instanceof Error ? err.message : String(err));
      }
    }
    return { names, failed };
  };

  // Files Repel Shield warned about (ClamAV clean): held until the user decides. Shown with their flags, never removed by us.
  const warned = response?.results.filter((r) => r.decision === 'quarantined' && r.clamav.verdict === 'clean' && r.repel.verdict === 'threat') ?? [];

  /** "Run anyway": scans only the warned files again, with their hashes marked as accepted; ClamAV still decides virus hits. */
  const acceptAndRun = async () => {
    const chosen = picked.filter((f) => warned.some((w) => w.name === f.name));
    const digests = warned.map((w) => w.sha256.slice(0, 12));
    setError(null);
    setScanning(chosen);
    setPhase('scanning');
    setWave({ n: 1, of: 1 });
    try {
      const out = await scanInWaves(rfqId, chosen, { acceptRisk: digests, onWave: (n, of) => setWave({ n, of }) });
      if (out.response) {
        // The re-scan covers only the flagged files, so the merged list is what is kept: the QuoteWin released in the first scan too.
        const fresh = new Map(out.response.results.map((r) => [r.name, r]));
        const merged = response
          ? { ...response, results: response.results.map((r) => fresh.get(r.name) ?? r) }
          : out.response;
        setKept(await keepReleasedInputs(merged));
        setResponse(merged);
        if (merged.results.some((r) => r.decision === 'released')) onReleased();
      }
      setPhase('result');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The scan failed');
      setPhase('result');
    }
  };

  const close = () => {
    abort.current?.abort();
    onClose();
  };

  /** The File of a released result: the one that was picked, or (after "Fix in place") the corrected copy the service now holds. */
  const fileOf = async (r: ScanResponse['results'][number]): Promise<File> => {
    const original = picked.find((f) => f.name === r.name);
    if (original) return original;
    const res = await authFetch(`${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(rfqId)}/attachments/${encodeURIComponent(r.attachment_id ?? '')}/content`, rfqId);
    if (!res.ok) throw new Error(`The corrected copy of ${r.name} could not be fetched (status ${res.status}).`);
    return new File([await res.blob()], r.name);
  };
  const useThese = async () => {
    const released = response?.results.filter((r) => r.decision === 'released') ?? [];
    const bom = released.find((r) => r.role === 'scrub_bom' || assignment[r.name] === 'scrub_bom');
    const volume = released.find((r) => r.role === 'volume' || assignment[r.name] === 'volume');
    const quotewin = released.find((r) => r.role === 'quotewin' || assignment[r.name] === 'quotewin' || /quotewin/i.test(r.name));
    const costing = released.find((r) => r.role === 'costing' || assignment[r.name] === 'costing' || /costing/i.test(r.name));
    if (!bom || !onUseFiles) return;
    try {
      onUseFiles({
        bom: await fileOf(bom),
        volume: volume ? await fileOf(volume) : null,
        quotewin: quotewin ? await fileOf(quotewin) : null,
        costing: costing ? await fileOf(costing) : null,
      });
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The files could not be used');
    }
  };

  return (
    <>
    <Dialog open={open && !fixTarget} onOpenChange={(o) => { if (!o) close(); }}>
      <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto [&>*]:min-w-0">
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

        {/* Stays mounted while scanning, so a failed scan returns to the same tiles. */}
        <div className={phase === 'review' ? 'space-y-3' : 'hidden'}>
          {error && (
            <p role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
              <WarningCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              {error}. Nothing was released.
            </p>
          )}
          <IntakeDashboard files={files} alreadyAttached={attached.current} onChange={setPicked} onReady={(u) => { uppy.current = u; }} />
          <InputBuckets
            names={picked.map((f) => f.name)}
            assignment={assignment}
            onAssign={(name, key) => setAssignment((a) => ({ ...a, [name]: key }))}
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{picked.length} selected{triage.rejected.length > 0 && ` · ${triage.rejected.length} rejected`}{waves > 1 && ` · sent in ${waves} waves`}</span>
            <button type="button" className="hover:text-foreground" onClick={() => uppy.current?.cancelAll()}>Remove all</button>
          </div>
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

        {phase === 'scanning' && (
          <ScanProgress files={wave.of > 1 ? planWaves(scanning).waves[wave.n - 1] ?? [] : scanning} wave={wave} total={scanning.length} />
        )}

        {phase === 'result' && response && <ScanResults response={response} />}
        {phase === 'result' && warned.length > 0 && (
          <section role="alert" aria-label="Security flags" data-testid="security-flags" className="space-y-2 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-xs text-foreground">
            <p className="flex items-center gap-2 font-semibold">
              <WarningCircle className="h-4 w-4 shrink-0 text-amber-600" aria-hidden />
              Security flags on {warned.length} {warned.length === 1 ? 'file' : 'files'}: not released yet
            </p>
            <ul className="space-y-1 pl-6">
              {warned.map((w) => (
                <li key={w.sha256}>
                  <span className="font-medium">{w.name}</span>: {(w.repel.flags ?? []).join(', ') || w.repel.detail}
                </li>
              ))}
            </ul>
            <p className="text-muted-foreground">Nothing is removed from these files. Fix them yourself and attach the fixed copy, or run anyway if you accept the risk.</p>
            <Button variant="outline" onClick={() => void acceptAndRun()} data-testid="accept-risk-run">Run anyway: I accept the risk</Button>
          </section>
        )}

        {phase === 'result' && kept && (kept.names.length > 0 || kept.failed.length > 0) && (
          <div role="status" className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-foreground" data-testid="kept-inputs">
            {kept.names.length > 0 && <p>Kept for this RFQ, to attach to its BOM: {kept.names.join(', ')}.</p>}
            {kept.failed.map((m) => <p key={m} className="text-destructive">{m}</p>)}
          </div>
        )}
        {phase === 'result' && readiness && (
          <p role="note" className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-foreground" data-testid="intake-readiness">
            <RocketLaunch className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            {readiness.message}
          </p>
        )}
        {phase === 'result' && readiness?.fix && (
          <Button variant="outline" onClick={() => setFixDone((s) => { const n = new Set(s); n.delete(readiness.fix!.attachmentId); return n; })} className="w-fit">
            Fix {readiness.fix.errors} {readiness.fix.errors === 1 ? 'cell' : 'cells'} in {readiness.fix.name}
          </Button>
        )}
        {phase === 'result' && failure && (
          <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">
            <p className="flex items-start gap-2"><WarningCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />Wave {failure.wave} of {failure.waves} failed: {failure.message}. The remaining waves were not run. These {failure.unsent.length} files were never scanned or released:</p>
            <ul className="mt-1 max-h-24 overflow-y-auto pl-6">{failure.unsent.map((f) => <li key={f.name} className="truncate">{f.name}</li>)}</ul>
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          {phase === 'result' ? (
            <>
              {onCreateRfq && readiness?.ready && (
                <Button variant="outline" onClick={() => { close(); onCreateRfq(); }}>Create RFQ from these files</Button>
              )}
              {onUseFiles && readiness?.ready && (
                <Button onClick={() => void useThese()} data-testid="use-scanned-files">Use these files</Button>
              )}
              <Button onClick={close}>Done</Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={close}>Cancel</Button>
              {phase === 'review' && <Button onClick={() => void run()} disabled={!fit.ok}>Scan {picked.length || ''} {picked.length === 1 ? 'file' : 'files'}</Button>}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
      {phase === 'result' && fixTarget && (
          // The whole workbook, full screen: the flagged cells in red, editable like a spreadsheet, and Force Run Anyway below it.
          <WorkbookEditor
            open
            rfqId={rfqId}
            attachmentId={fixTarget.attachmentId}
            name={fixTarget.name}
            report={undefined}
            onClose={() => setFixDone((s) => new Set(s).add(fixTarget.attachmentId))}
            onFixed={(fixed, previousId) => {
              // the corrected copy replaced the original: the result row and the readiness follow it; the next file's popup opens
              setFixDone((s) => new Set(s).add(previousId));
              setResponse((r) => r && ({ ...r, results: r.results.map((x) => (x.attachment_id === previousId
                ? { ...x, attachment_id: fixed.attachment_id, name: fixed.name, sha256: fixed.sha256, check: fixed.check }
                : x)) }));
              onReleased();
            }}
            onForced={(unresolved) => {
              setFixDone((s) => new Set(s).add(fixTarget.attachmentId));
              setKept({ names: [], failed: [`The run was started with ${unresolved} cell${unresolved === 1 ? '' : 's'} left as they are; the output is marked as a forced run.`] });
            }}
          />
        )}
    </>
  );
}
