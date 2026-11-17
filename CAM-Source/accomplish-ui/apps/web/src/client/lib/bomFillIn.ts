/**
 * The Excel fill-in for a BOM the pre-flight refused (422 `input_invalid`): a copy of the user's own workbook with every flagged cell filled
 * red and a note on it, plus a "Fix list" tab. Built here in the browser from the issues the server returned, so no file leaves the machine.
 * The copy is what the user fixes in Excel; the fixed file goes back into the BOM bucket and is checked again.
 */
import ExcelJS from 'exceljs';

export interface FillInIssue {
  sheet: string | null;
  col: string | null;
  row: number | null;
  message: string;
  code?: string;
  value?: string | null;
}

const RED = 'FFF8D7DA';

/** The same workbook with each flagged cell marked red (and noted), and a 'Fix list' tab. Cells the file does not have are listed, not skipped. */
export async function markUpBom(file: File, issues: FillInIssue[]): Promise<{ blob: Blob; marked: number; unplaced: FillInIssue[] }> {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(await file.arrayBuffer());
  let marked = 0;
  const unplaced: FillInIssue[] = [];
  for (const issue of issues) {
    const ws = issue.sheet ? wb.getWorksheet(issue.sheet) : undefined;
    if (!ws || !issue.col || !issue.row) {
      unplaced.push(issue);
      continue;
    }
    const cell = ws.getCell(`${issue.col}${issue.row}`);
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: RED } };
    cell.note = issue.message;
    marked += 1;
  }
  const fix = wb.addWorksheet('Fix list');
  fix.columns = [
    { header: 'Sheet', key: 'sheet', width: 22 },
    { header: 'Cell', key: 'cell', width: 12 },
    { header: 'Value now', key: 'value', width: 24 },
    { header: 'What is wrong', key: 'message', width: 90 },
  ];
  fix.getRow(1).font = { bold: true };
  for (const i of issues) {
    fix.addRow({ sheet: i.sheet ?? '', cell: i.col && i.row ? `${i.col}${i.row}` : '', value: i.value ?? '', message: i.message });
  }
  const buffer = await wb.xlsx.writeBuffer();
  return { blob: new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), marked, unplaced };
}

/** Saves a blob through a hidden link, the same way the reports download. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The file name of a marked-up copy: "<name> - to fill in.xlsx". */
export function markedName(name: string): string {
  const dot = name.lastIndexOf('.');
  return `${dot > 0 ? name.slice(0, dot) : name} - to fill in.xlsx`;
}
