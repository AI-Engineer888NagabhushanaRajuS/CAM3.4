import * as XLSX from 'xlsx';

export interface MasterRow {
  id: string;
  [key: string]: string | number | boolean;
}

export interface MasterTab {
  id: string;
  label: string;
  columns: string[];
  rows: MasterRow[];
}

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

// Display-only: the sheet "Triode Employees & Competencies" reads as just
// "Employees & Competencies" in the tab strip -- the customer name doesn't
// need repeating in every tab label. Doesn't touch the id (still derived
// from the real sheet name) or any cell data, only what's shown on the tab.
function displayTabLabel(sheetName: string): string {
  return sheetName.replace(/\bTriode\b\s*/gi, '').trim();
}

// Excel's date epoch is 1899-12-30; 25569 is the day-count offset to the Unix
// epoch (1970-01-01), used to convert a raw serial number into a real Date.
function excelSerialToISODate(serial: number): string {
  return new Date(Math.round((serial - 25569) * 86400 * 1000)).toISOString().split('T')[0];
}

// Excel date serials for any plausible year (~1990-2100) land in this range --
// used together with a column-name hint so numeric non-date columns (rates,
// counts) are never misread as dates.
function looksLikeDateSerial(value: unknown): value is number {
  return typeof value === 'number' && value > 25000 && value < 55000;
}

function coerceCellValue(column: string, value: unknown): string | number | boolean {
  if (looksLikeDateSerial(value) && /date|due|received/i.test(column)) {
    return excelSerialToISODate(value);
  }
  if (typeof value === 'boolean' || typeof value === 'number') {
    return value;
  }
  return value === undefined || value === null ? '' : String(value);
}

/**
 * Every sheet this app reads from -- both the 3 master workbooks and any
 * user-uploaded bulk-import file -- follows the same "SUB-TABLE: X" marker
 * row (only its first cell populated) followed by the real header row, then
 * data. Detected generically here (a real header row has more than one
 * populated cell; a marker row has exactly one) so a plain file with a real
 * header in row 0 -- no marker -- still parses correctly either way.
 */
function isRowBlank(row: unknown[]): boolean {
  return row.every((cell) => String(cell ?? '').trim() === '');
}

function sheetRowsWithHeaders(worksheet: XLSX.WorkSheet): { headers: string[]; dataRows: unknown[][] } {
  const rawRows = XLSX.utils.sheet_to_json<unknown[]>(worksheet, { header: 1, defval: '' });
  if (rawRows.length === 0) {
    return { headers: [], dataRows: [] };
  }

  const firstRowPopulatedCount = rawRows[0].filter((cell) => String(cell).trim() !== '').length;
  const hasSubTableMarker = firstRowPopulatedCount <= 1 && rawRows.length > 1;

  // `header: 1` faithfully reproduces the sheet's *declared* dimension, which
  // Excel/exporters often over-state (formatting applied to a big range with
  // no real content) -- filter out rows that are entirely blank rather than
  // trusting the declared range, or a sheet with 1 real row can come back
  // with hundreds of phantom trailing rows.
  if (hasSubTableMarker) {
    // The header is the first row after the marker that has more than one filled cell: a blank separator row in between is skipped,
    // not taken as the header (the CAM Masters workbook has one).
    const headerIndex = rawRows.findIndex((row, i) => i > 0 && row.filter((cell) => String(cell).trim() !== '').length > 1);
    if (headerIndex > 0) {
      return { headers: rawRows[headerIndex].map((h) => String(h)), dataRows: rawRows.slice(headerIndex + 1).filter((row) => !isRowBlank(row)) };
    }
    return { headers: rawRows[1].map((h) => String(h)), dataRows: rawRows.slice(2).filter((row) => !isRowBlank(row)) };
  }
  return { headers: rawRows[0].map((h) => String(h)), dataRows: rawRows.slice(1).filter((row) => !isRowBlank(row)) };
}

function parseSheetToTab(sheetName: string, worksheet: XLSX.WorkSheet): MasterTab {
  const id = slugify(sheetName);
  const label = displayTabLabel(sheetName);
  const { headers: columns, dataRows } = sheetRowsWithHeaders(worksheet);

  const rows: MasterRow[] = dataRows.map((dataRow, rowIndex) => {
    const row: MasterRow = { id: `${id}-${rowIndex}` };
    columns.forEach((column, colIndex) => {
      row[column] = coerceCellValue(column, dataRow[colIndex]);
    });
    return row;
  });

  return { id, label, columns, rows };
}

export async function loadMasterTabs(excelUrl: string): Promise<MasterTab[]> {
  const response = await fetch(excelUrl);
  if (!response.ok) {
    throw new Error(`Failed to load ${excelUrl}: HTTP ${response.status}`);
  }
  const buffer = await response.arrayBuffer();
  const workbook = XLSX.read(buffer, { type: 'array' });
  return workbook.SheetNames.map((sheetName) => parseSheetToTab(sheetName, workbook.Sheets[sheetName]));
}

/** Parses a user-uploaded bulk-import file against an existing tab's column
 * list -- works whether the file has a "SUB-TABLE" marker row (e.g. a copy
 * of one tab's own sheet, re-uploaded) or a plain real header in row 0 (see
 * sheetRowsWithHeaders' detection). Looks columns up by matching header
 * name, not position, so an uploaded file's columns can be in any order or
 * even a subset of the tab's own columns. */
export function parseBulkUploadRows(file: ArrayBuffer, columns: string[], tabId: string): MasterRow[] {
  const workbook = XLSX.read(file, { type: 'array' });
  const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
  const { headers, dataRows } = sheetRowsWithHeaders(firstSheet);

  return dataRows.map((dataRow, index) => {
    const record: Record<string, unknown> = {};
    headers.forEach((header, colIndex) => { record[header] = dataRow[colIndex]; });

    const row: MasterRow = { id: `${tabId}-import-${Date.now()}-${index}` };
    columns.forEach((column) => {
      row[column] = coerceCellValue(column, record[column]);
    });
    return row;
  });
}
