import { useCallback, useEffect, useState } from 'react';
import { CheckCircle, DownloadSimple, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { cellAddress, cellKey, collectEdits, downloadAttachment, fetchCheck, submitFix, type CheckIssue, type CheckReport, type FixedAttachment } from '@/lib/inputFix';

interface InputFixDialogProps {
  open: boolean;
  /** Where the file was scanned (the RFQ id, or the chat's staging scope). */
  scope: string;
  attachmentId: string;
  name: string;
  onClose: () => void;
  /** The corrected copy replaced the original (new id and name): refresh whatever lists files. */
  onFixed?: (fixed: FixedAttachment, previousId: string) => void;
  /** "Continue" after a clean result: the host carries on with the process. */
  onContinue?: () => void;
}

const PROBLEM_WORD: Record<string, string> = {
  cpn_blank: 'Fill in', fg_blank: 'Fill in', quantity_blank: 'Fill in', volume_blank: 'Fill in',
  quantity_text: 'Type the number', volume_not_number: 'Type the number', batch_not_number: 'Type the number',
  cell_error: 'Replace the error', formula_unsaved: 'Type the value',
};

/**
 * The BOM would give NaN / errors in the output (SPEC-023). Only the flagged cells are shown, each with its own box; Save
 * writes them into a scanned copy, checks again, and when it is clean downloads the corrected file to the computer.
 */
export function InputFixDialog({ open, scope, attachmentId, name, onClose, onFixed, onContinue }: InputFixDialogProps) {
  const [current, setCurrent] = useState({ id: attachmentId, name });
  const [report, setReport] = useState<CheckReport | null>(null);
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ name: string; downloaded: boolean } | null>(null);

  const load = useCallback(async (id: string) => {
    setError(null);
    try {
      setReport(await fetchCheck(scope, id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The check failed');
    }
  }, [scope]);

  useEffect(() => {
    if (!open) return;
    setCurrent({ id: attachmentId, name });
    setTyped({});
    setSaved(null);
    setReport(null);
    void load(attachmentId);
  }, [open, attachmentId, name, load]);

  const issues = report?.issues ?? [];
  const errors = issues.filter((i) => i.severity === 'error' && i.fixable);
  const warnings = issues.filter((i) => i.severity === 'warning' && i.fixable);
  const needsExcel = issues.filter((i) => !i.fixable);
  const edits = collectEdits(issues, typed);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const previousId = current.id;
      const fixed = await submitFix(scope, previousId, edits);
      setCurrent({ id: fixed.attachment_id, name: fixed.name });
      setReport(fixed.report);
      setTyped({});
      onFixed?.(fixed, previousId);
      if (fixed.report.ok) {
        // A click started this, so the browser lets the file save without asking.
        let downloaded = true;
        try {
          await downloadAttachment(scope, fixed.attachment_id, fixed.name);
        } catch {
          downloaded = false;
        }
        setSaved({ name: fixed.name, downloaded });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Saving failed');
    } finally {
      setBusy(false);
    }
  };

  const redownload = async () => {
    try {
      await downloadAttachment(scope, current.id, current.name);
      setSaved((s) => (s ? { ...s, downloaded: true } : s));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The download failed');
    }
  };

  const row = (i: CheckIssue) => {
    const key = cellKey(i);
    return (
      <li key={key + i.code} className="rounded-lg border border-border p-3" data-testid="fix-row">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-foreground">{i.sheet} · {cellAddress(i)}</span>
          <span className="text-muted-foreground">{i.column}</span>
        </div>
        <p className="mt-1 text-sm text-foreground">{i.message}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Input
            className="h-9 max-w-[16rem]"
            aria-label={`${PROBLEM_WORD[i.code] ?? 'New value'} for ${i.sheet} ${cellAddress(i)}`}
            placeholder={PROBLEM_WORD[i.code] ?? 'New value'}
            value={typed[key] ?? i.value ?? ''}
            onChange={(e) => setTyped((t) => ({ ...t, [key]: e.target.value }))}
          />
          {i.suggestion !== undefined && (
            <Button type="button" size="sm" variant="outline" onClick={() => setTyped((t) => ({ ...t, [key]: i.suggestion ?? '' }))}>Use {i.suggestion}</Button>
          )}
        </div>
      </li>
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto [&>*]:min-w-0">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {saved ? <CheckCircle className="h-5 w-5 text-emerald-600" weight="fill" aria-hidden /> : <WarningCircle className="h-5 w-5 text-amber-600" weight="fill" aria-hidden />}
            {saved ? 'The BOM is clean' : 'Fix the BOM before it runs'}
          </DialogTitle>
          <DialogDescription>
            {saved
              ? 'Nothing in it would turn into NaN or an error in the output.'
              : `${current.name}: these cells would turn into NaN, empty values or errors in the output. Fill them in here; the check runs again when you save.`}
          </DialogDescription>
        </DialogHeader>

        {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">{error}</p>}
        {!report && !error && <p role="status" className="text-sm text-muted-foreground">Checking {current.name}…</p>}

        {saved && (
          <div role="status" className="space-y-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-sm text-foreground" data-testid="fix-saved">
            <p>
              <b>{saved.name}</b> is the file the run will use.{' '}
              {saved.downloaded ? 'It was downloaded to your computer.' : 'The download did not start; use the button.'}
            </p>
            <Button type="button" size="sm" variant="outline" onClick={() => void redownload()}><DownloadSimple className="mr-1.5 h-4 w-4" aria-hidden />Download again</Button>
          </div>
        )}

        {!saved && report && (
          <>
            <p className="text-xs text-muted-foreground" data-testid="fix-summary">
              {report.errors} to fix{report.warnings > 0 && ` · ${report.warnings} optional`}{report.truncated && ' · the first ones are shown; save and the rest appear'}
            </p>
            {errors.length > 0 && <ul className="space-y-2">{errors.map(row)}</ul>}
            {needsExcel.length > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-foreground" data-testid="fix-needs-excel">
                <p className="font-medium">These need Excel (no single cell fixes them):</p>
                <ul className="mt-1 list-disc space-y-1 pl-5">{needsExcel.map((i) => <li key={i.code + i.message}>{i.message}</li>)}</ul>
              </div>
            )}
            {warnings.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer select-none text-muted-foreground">Optional: {warnings.length} blank or odd values that will not stop the run</summary>
                <ul className="mt-2 space-y-2">{warnings.map(row)}</ul>
              </details>
            )}
          </>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          {saved ? (
            <>
              <Button variant="outline" onClick={onClose}>Close</Button>
              {onContinue && <Button onClick={() => { onClose(); onContinue(); }}>Continue with this file</Button>}
            </>
          ) : (
            <>
              <Button variant="outline" onClick={onClose}>Not now</Button>
              <Button onClick={() => void save()} disabled={busy || edits.length === 0}>
                {busy ? 'Saving…' : `Save ${edits.length || ''} ${edits.length === 1 ? 'correction' : 'corrections'} and check again`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
