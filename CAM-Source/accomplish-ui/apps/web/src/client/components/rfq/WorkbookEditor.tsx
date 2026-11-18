import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, ModuleRegistry, type ColDef, type CellValueChangedEvent } from 'ag-grid-community';
import ExcelJS from 'exceljs';
import { WarningCircle, X } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { myTheme } from '@/lib/agGridTheme';
import { PYTHON_BRIDGE_URL, RFQ_UPLOAD_URL } from '@/config/endpoints';
import { authFetch } from '@/lib/apiAuth';
import { fetchCheck, submitFix, type CheckIssue, type CheckReport, type FixedAttachment } from '@/lib/inputFix';

ModuleRegistry.registerModules([AllCommunityModule]);

/**
 * The whole BOM workbook, full screen, every sheet, editable like a spreadsheet. The cells the pre-check flags are red; the ones you
 * change are yellow. Two ways out: "Save corrections" (the scanned copy is corrected and checked again) or "Force Run Anyway" (the run
 * goes ahead with the flagged cells as they are; the run is marked as forced).
 */
export interface WorkbookEditorProps {
  open: boolean;
  /** The RFQ the file belongs to. */
  rfqId: string;
  /** A scanned file held by the server (the scan dialog), or ... */
  attachmentId?: string;
  /** ... a file in the browser (the intake dialog). Exactly one of attachmentId / file is given. */
  file?: File;
  name: string;
  /** The pre-check of the file; read from the server when not given. */
  report?: CheckReport;
  onClose: () => void;
  /** Server copy corrected: the new copy replaces the old one. */
  onFixed?: (fixed: FixedAttachment, previousId: string) => void;
  /** Browser copy corrected: the caller replaces its file with this one. */
  onFileChange?: (file: File) => void;
  /** The run was started with Force Run Anyway. */
  onForced?: (unresolved: number) => void;
}

type Edit = { sheet: string; row: number; col: string; value: string };

const EMPTY_REPORT: CheckReport = { checked: false, ok: true, errors: 0, warnings: 0, rows: 0, issues: [], truncated: false };

const colLetter = (n: number): string => {
  let s = '';
  let x = n;
  while (x > 0) {
    const m = (x - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    x = Math.floor((x - 1) / 26);
  }
  return s;
};

const addrKey = (sheet: string, col: string, row: number) => `${sheet}!${col}${row}`;

async function loadWorkbook(props: Pick<WorkbookEditorProps, 'rfqId' | 'attachmentId' | 'file'>): Promise<ExcelJS.Workbook> {
  const wb = new ExcelJS.Workbook();
  if (props.file) {
    await wb.xlsx.load(await props.file.arrayBuffer());
    return wb;
  }
  const res = await authFetch(`${PYTHON_BRIDGE_URL}/api/rfq/${encodeURIComponent(props.rfqId)}/attachments/${encodeURIComponent(props.attachmentId ?? '')}/content`, props.rfqId);
  if (!res.ok) throw new Error(`The file could not be opened (status ${res.status}).`);
  await wb.xlsx.load(await res.arrayBuffer());
  return wb;
}

export function WorkbookEditor({ open, rfqId, attachmentId, file, name, report, onClose, onFixed, onFileChange, onForced }: WorkbookEditorProps) {
  const [wb, setWb] = useState<ExcelJS.Workbook | null>(null);
  const [sheetName, setSheetName] = useState<string>('');
  const [current, setCurrent] = useState({ id: attachmentId ?? '', name, report: report ?? EMPTY_REPORT });
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmForce, setConfirmForce] = useState(false);
  const [version, setVersion] = useState(0);

  // Reads the workbook again whenever the copy changes (a corrected server copy, or a new browser file).
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setError(null);
    setEdits({});
    setConfirmForce(false);
    setCurrent({ id: attachmentId ?? '', name, report: report ?? EMPTY_REPORT });
    if (attachmentId && !report) {
      fetchCheck(rfqId, attachmentId).then((r) => { if (alive) setCurrent((c) => ({ ...c, report: r })); }).catch(() => undefined);
    }
    loadWorkbook({ rfqId, attachmentId: current.id || attachmentId, file })
      .then((loaded) => {
        if (!alive) return;
        setWb(loaded);
        setSheetName((s) => (loaded.worksheets.some((w) => w.name === s) ? s : loaded.worksheets[0]?.name ?? ''));
      })
      .catch((err: unknown) => { if (alive) setError(err instanceof Error ? err.message : 'The file could not be opened.'); });
    return () => { alive = false; };
    // The copy's identity and the file object decide when to read it again; the report is the server's and comes with them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, attachmentId, file, version]);

  const issueKeys = useMemo(() => {
    const keys = new Map<string, string>();
    for (const i of current.report.issues as CheckIssue[]) {
      if (i.sheet && i.col && i.row) keys.set(addrKey(i.sheet, i.col, i.row), i.message);
    }
    return keys;
  }, [current.report]);

  const sheet = wb?.getWorksheet(sheetName) ?? null;

  const { columnDefs, rowData } = useMemo(() => {
    if (!sheet) return { columnDefs: [] as ColDef[], rowData: [] as Record<string, unknown>[] };
    const cols = sheet.columnCount;
    const defs: ColDef[] = [{ headerName: '#', field: '__row', pinned: 'left', width: 70, editable: false, cellStyle: { color: '#64748b' } }];
    for (let c = 1; c <= cols; c += 1) {
      const letter = colLetter(c);
      const header = sheet.getRow(1).getCell(c).text || letter;
      defs.push({
        headerName: `${letter} · ${header}`,
        field: letter,
        editable: true,
        minWidth: 110,
        cellStyle: (p) => {
          const row = Number(p.data?.__row);
          const key = addrKey(sheetName, letter, row);
          if (edits[key]) return { background: '#fff3cd' };
          if (issueKeys.has(key)) return { background: '#f8d7da' };
          return null;
        },
      });
    }
    const rows: Record<string, unknown>[] = [];
    for (let r = 1; r <= sheet.rowCount; r += 1) {
      const row: Record<string, unknown> = { __row: r };
      for (let c = 1; c <= cols; c += 1) {
        const letter = colLetter(c);
        const key = addrKey(sheetName, letter, r);
        row[letter] = edits[key] ? edits[key].value : sheet.getRow(r).getCell(c).text;
      }
      rows.push(row);
    }
    return { columnDefs: defs, rowData: rows };
  }, [sheet, sheetName, edits, issueKeys]);

  const onCellChanged = (e: CellValueChangedEvent) => {
    const field = e.colDef.field;
    if (!field || field === '__row') return;
    const row = Number(e.data.__row);
    const value = String(e.newValue ?? '');
    const key = addrKey(sheetName, field, row);
    const original = sheet?.getRow(row).getCell(field.charCodeAt(0) - 64).text ?? '';
    setEdits((prev) => {
      const next = { ...prev };
      if (value === original) delete next[key];
      else next[key] = { sheet: sheetName, row, col: field, value };
      return next;
    });
  };

  const editList = Object.values(edits);
  const flagged = current.report.errors;

  // Corrections as the file would hold them: a number typed as a number, anything else as text.
  const applyEdits = (book: ExcelJS.Workbook) => {
    for (const ed of editList) {
      const cell = book.getWorksheet(ed.sheet)?.getCell(`${ed.col}${ed.row}`);
      if (!cell) continue;
      const trimmed = ed.value.trim();
      cell.value = trimmed === '' ? null : /^-?\d+(\.\d+)?$/.test(trimmed) ? Number(trimmed) : ed.value;
    }
  };

  const saveCorrections = async () => {
    setBusy(true);
    setError(null);
    try {
      if (file) {
        // Browser copy: the corrections go into the file the caller holds; its intake then checks it again on upload.
        const book = wb ?? new ExcelJS.Workbook();
        applyEdits(book);
        const buf = await book.xlsx.writeBuffer();
        onFileChange?.(new File([buf], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
        onClose();
        return;
      }
      const previous = current.id;
      const fixed = await submitFix(rfqId, previous, editList.map(({ sheet: s, row, col, value }) => ({ sheet: s, row, col, value })));
      setCurrent({ id: fixed.attachment_id, name: fixed.name, report: fixed.report });
      onFixed?.(fixed, previous);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Saving failed');
    } finally {
      setBusy(false);
    }
  };

  // Force Run Anyway: the workbook as it is now (corrections included) goes to the upload with the force flag; the run goes ahead.
  const forceRun = async () => {
    setBusy(true);
    setError(null);
    try {
      const book = wb ?? new ExcelJS.Workbook();
      applyEdits(book);
      const buf = await book.xlsx.writeBuffer();
      const bom = new File([buf], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const body = new FormData();
      body.append('bom_file', bom);
      body.append('rfq_id', rfqId.trim());
      body.append('force_run', 'true');
      const res = await authFetch(`${RFQ_UPLOAD_URL}/api/rfq/upload`, rfqId.trim(), { method: 'POST', body });
      if (!res.ok) {
        const detail = ((await res.json().catch(() => null)) as { detail?: { message?: string } | string } | null)?.detail;
        throw new Error(typeof detail === 'string' ? detail : detail?.message ?? `The run did not start (status ${res.status}).`);
      }
      onForced?.(flagged);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The run did not start');
    } finally {
      setBusy(false);
      setConfirmForce(false);
    }
  };

  if (!open) return null;

  // Rendered into the body: a full-screen layer inside a dialog would be clipped by the dialog's own box.
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`Workbook ${current.name}`} className="fixed inset-0 z-[90] flex flex-col bg-background" style={{ pointerEvents: 'auto' }} data-testid="workbook-editor">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{current.name}</p>
          <p className="text-xs text-muted-foreground" data-testid="editor-summary">
            {flagged} to fill in in red · {editList.length} changed in yellow · click a cell and type
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </header>

      {error && (
        <p role="alert" className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/5 px-5 py-2 text-xs text-foreground">
          <WarningCircle className="h-4 w-4 text-destructive" /> {error}
        </p>
      )}

      <nav className="flex gap-1 overflow-x-auto border-b border-border px-3 py-1.5" aria-label="Sheets">
        {(wb?.worksheets ?? []).map((w) => (
          <button
            key={w.name}
            type="button"
            onClick={() => setSheetName(w.name)}
            aria-pressed={w.name === sheetName}
            className={`shrink-0 rounded-md px-3 py-1 text-xs font-semibold ${w.name === sheetName ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
          >
            {w.name}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 p-2" style={{ height: '100%', width: '100%' }}>
        {!wb && !error && <p role="status" className="p-4 text-sm text-muted-foreground">Opening the workbook…</p>}
        {wb && sheet && (
          <AgGridReact
            theme={myTheme}
            columnDefs={columnDefs}
            rowData={rowData}
            defaultColDef={{ resizable: true, sortable: false, filter: false }}
            onCellValueChanged={onCellChanged}
            singleClickEdit
            stopEditingWhenCellsLoseFocus
          />
        )}
      </div>

      <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3">
        {confirmForce ? (
          <>
            <span className="mr-auto text-xs text-foreground">
              The run goes ahead with {flagged} flagged cell{flagged === 1 ? '' : 's'} as they are. The run is marked as forced, with that count.
            </span>
            <Button variant="outline" onClick={() => setConfirmForce(false)} disabled={busy}>Back</Button>
            <Button variant="destructive" onClick={() => void forceRun()} disabled={busy}>Confirm Force Run</Button>
          </>
        ) : (
          <>
            <Button variant="outline" onClick={onClose} disabled={busy}>Not now</Button>
            <Button variant="outline" onClick={() => setConfirmForce(true)} disabled={busy}>Force Run Anyway</Button>
            <Button onClick={() => void saveCorrections()} disabled={busy || editList.length === 0}>
              {busy ? 'Saving…' : `Save ${editList.length || ''} ${editList.length === 1 ? 'correction' : 'corrections'}${file ? '' : ' and check again'}`}
            </Button>
          </>
        )}
      </footer>
    </div>,
    document.body,
  );
}
