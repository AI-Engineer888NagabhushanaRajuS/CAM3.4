import { useRef } from 'react';
import { UploadSimple } from '@phosphor-icons/react';
import { parseBulkUploadRows, type MasterRow } from '../../lib/masterExcel';

interface BulkUploadButtonProps {
  tabId: string;
  columns: string[];
  onImport: (importedRows: MasterRow[]) => void;
}

/** Parses an uploaded Excel file into rows matching the active tab's columns
 * and hands them to the caller -- the caller APPENDS them to existing rows
 * (`[...existingRows, ...importedRows]`), it never replaces the table. */
export function BulkUploadButton({ tabId, columns, onImport }: BulkUploadButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) { return; }
    const buffer = await file.arrayBuffer();
    const importedRows = parseBulkUploadRows(buffer, columns, tabId);
    onImport(importedRows);
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx,.xls,.csv"
        className="hidden"
        onChange={(e) => { void handleFileChange(e); }}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium text-foreground/85 transition hover:bg-muted/50 dark:border-white/10 dark:bg-white/[0.03] dark:hover:bg-white/[0.06]"
      >
        <UploadSimple className="h-4 w-4" />
        Bulk Upload
      </button>
    </>
  );
}
