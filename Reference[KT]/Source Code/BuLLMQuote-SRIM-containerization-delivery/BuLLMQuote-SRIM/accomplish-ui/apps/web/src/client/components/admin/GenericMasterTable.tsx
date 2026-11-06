import { useEffect, useRef, useState } from 'react';
import { Trash } from '@phosphor-icons/react';
import type { MasterRow } from '../../lib/masterExcel';

interface GenericMasterTableProps {
  columns: string[];
  rows: MasterRow[];
  onCellChange: (rowId: string, column: string, value: string | boolean) => void;
  onDeleteRow: (rowId: string) => void;
}

interface EditingCell {
  rowId: string;
  column: string;
}

/** True/False values (real Excel booleans, not "YES"/"NO" text) render as a
 * dropdown -- like Excel's own data-validation cells -- instead of a text
 * field. Click opens the native select, pick True or False. */
function BooleanFlagCell({ value, onChange }: { value: boolean; onChange: (next: boolean) => void }) {
  return (
    <select
      value={value ? 'true' : 'false'}
      onChange={(e) => onChange(e.target.value === 'true')}
      className={`w-full cursor-pointer rounded-md border px-2 py-1 text-xs font-semibold outline-none transition focus:ring-1 focus:ring-primary/30 ${
        value
          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
          : 'border-border bg-muted text-muted-foreground dark:border-white/10'
      }`}
    >
      <option value="true">True</option>
      <option value="false">False</option>
    </select>
  );
}

/** Description/notes/use-case-style fields hold free-form prose that's often
 * far longer than a cell is wide (e.g. an "RFQ Automation Use Case" or "AI
 * Context" narrative) -- wrap it onto multiple lines within the cell instead
 * of forcing the whole row wider (or clipping it) like every other
 * short-value column does. Column name is a hint, but the real signal is the
 * value itself being long prose -- a column can hold short values in most
 * rows and one long paragraph in another. */
const LONG_TEXT_COLUMN_HINT = /description|notes?|remarks?|comments?|use case|context|summary|scope|details?/i;
const LONG_TEXT_VALUE_THRESHOLD = 40;

function shouldWrapCell(column: string, value: string | number | boolean): boolean {
  if (typeof value === 'string' && value.length > LONG_TEXT_VALUE_THRESHOLD) { return true; }
  return LONG_TEXT_COLUMN_HINT.test(column);
}

/** Display-only formatting: a non-integer number (cost/rate columns) shows
 * exactly 2 decimal places, matching how these figures are meant to be read
 * -- the underlying value/edit draft keeps its full precision, only the
 * read view is rounded. */
function formatCellDisplay(value: string | number | boolean): string {
  if (typeof value === 'number' && !Number.isInteger(value)) {
    return value.toFixed(2);
  }
  return String(value ?? '');
}

/** One click on a cell turns it into a text input in place -- no separate
 * edit modal or per-row Actions column. Enter/blur commits, Escape cancels. */
function EditableCell({
  row,
  column,
  isEditing,
  onStartEdit,
  onCommit,
  onCancel,
}: {
  row: MasterRow;
  column: string;
  isEditing: boolean;
  onStartEdit: () => void;
  onCommit: (value: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(() => String(row[column] ?? ''));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing) {
      setDraft(String(row[column] ?? ''));
      inputRef.current?.focus();
      inputRef.current?.select();
    }
    // Only re-seed the draft when this cell newly becomes the active edit
    // target, not on every parent re-render while it's open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing]);

  if (isEditing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => onCommit(draft)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { onCommit(draft); }
          if (e.key === 'Escape') { onCancel(); }
        }}
        className="w-full min-w-[120px] rounded-md border border-primary/50 bg-background px-2 py-1 text-sm outline-none ring-1 ring-primary/30"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={onStartEdit}
      className="w-full rounded-md px-2 py-1 text-left text-foreground/90 transition hover:bg-primary/5"
    >
      {formatCellDisplay(row[column])}
    </button>
  );
}

/** A thin scrollbar mirrored above the table, kept in sync with the table's
 * own bottom scrollbar -- lets a user see/scroll a wide table's horizontal
 * position without first scrolling all the way down to find the real one. */
export function GenericMasterTable({ columns, rows, onCellChange, onDeleteRow }: GenericMasterTableProps) {
  const topScrollRef = useRef<HTMLDivElement>(null);
  const topSpacerRef = useRef<HTMLDivElement>(null);
  const tableWrapperRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef<'top' | 'bottom' | null>(null);
  const [editingCell, setEditingCell] = useState<EditingCell | null>(null);

  useEffect(() => {
    const tableWrapper = tableWrapperRef.current;
    const topSpacer = topSpacerRef.current;
    if (!tableWrapper || !topSpacer) { return; }

    const syncSpacerWidth = () => {
      topSpacer.style.width = `${tableWrapper.scrollWidth}px`;
    };
    syncSpacerWidth();

    const resizeObserver = new ResizeObserver(syncSpacerWidth);
    resizeObserver.observe(tableWrapper);
    return () => resizeObserver.disconnect();
  }, [columns, rows]);

  const handleTopScroll = () => {
    if (syncingRef.current === 'bottom') { return; }
    syncingRef.current = 'top';
    if (tableWrapperRef.current && topScrollRef.current) {
      tableWrapperRef.current.scrollLeft = topScrollRef.current.scrollLeft;
    }
    syncingRef.current = null;
  };

  const handleBottomScroll = () => {
    if (syncingRef.current === 'top') { return; }
    syncingRef.current = 'bottom';
    if (tableWrapperRef.current && topScrollRef.current) {
      topScrollRef.current.scrollLeft = tableWrapperRef.current.scrollLeft;
    }
    syncingRef.current = null;
  };

  const commitEdit = (rowId: string, column: string, value: string) => {
    onCellChange(rowId, column, value);
    setEditingCell(null);
  };

  const setBoolean = (rowId: string, column: string, next: boolean) => {
    onCellChange(rowId, column, next);
  };

  if (rows.length === 0) {
    return (
      <div className="flex min-h-[160px] items-center justify-center rounded-xl border border-dashed border-border text-sm text-muted-foreground dark:border-white/10">
        No records in this tab yet.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border dark:border-white/10">
      <div
        ref={topScrollRef}
        onScroll={handleTopScroll}
        className="overflow-x-auto overflow-y-hidden rounded-t-xl border-b border-border dark:border-white/10"
        style={{ height: 12 }}
      >
        <div ref={topSpacerRef} style={{ height: 1 }} />
      </div>

      <div ref={tableWrapperRef} onScroll={handleBottomScroll} className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-muted/60 dark:bg-white/[0.04]">
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  className={`border-b border-border px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground dark:border-white/10 dark:text-white/50 ${
                    column.length > 20 ? 'whitespace-normal break-words' : 'whitespace-nowrap'
                  }`}
                  style={column.length > 20 ? { minWidth: 140, maxWidth: 220 } : undefined}
                >
                  {column}
                </th>
              ))}
              <th className="sticky right-0 z-10 w-10 border-b border-l border-border bg-muted/60 dark:border-white/10 dark:bg-white/[0.04]" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr
                key={row.id}
                className={`group border-b border-border/70 last:border-b-0 dark:border-white/[0.06] ${
                  rowIndex % 2 === 1 ? 'bg-muted/[0.15] dark:bg-white/[0.012]' : ''
                }`}
              >
                {columns.map((column) => {
                  const cellValue = row[column];
                  const wrapLongText = shouldWrapCell(column, cellValue);
                  return (
                    <td
                      key={column}
                      className={`px-1 py-1 align-top ${wrapLongText ? 'min-w-[220px] max-w-[360px] whitespace-normal break-words' : 'whitespace-nowrap'}`}
                    >
                      {typeof cellValue === 'boolean' ? (
                        <BooleanFlagCell value={cellValue} onChange={(next) => setBoolean(row.id, column, next)} />
                      ) : (
                        <EditableCell
                          row={row}
                          column={column}
                          isEditing={editingCell?.rowId === row.id && editingCell.column === column}
                          onStartEdit={() => setEditingCell({ rowId: row.id, column })}
                          onCommit={(value) => commitEdit(row.id, column, value)}
                          onCancel={() => setEditingCell(null)}
                        />
                      )}
                    </td>
                  );
                })}
                <td
                  className={`sticky right-0 border-l border-border px-1 py-1 text-center dark:border-white/10 ${
                    rowIndex % 2 === 1 ? 'bg-muted/[0.15] dark:bg-white/[0.012]' : 'bg-background'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onDeleteRow(row.id)}
                    aria-label="Delete row"
                    className="rounded-md p-1.5 text-muted-foreground opacity-0 transition hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                  >
                    <Trash className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
