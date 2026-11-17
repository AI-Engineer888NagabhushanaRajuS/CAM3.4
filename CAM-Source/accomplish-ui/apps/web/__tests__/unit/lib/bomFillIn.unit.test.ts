import ExcelJS from 'exceljs';
import { describe, expect, it } from 'vitest';
import { markUpBom, markedName } from '@/lib/bomFillIn';

async function bomFile(): Promise<File> {
  const wb = new ExcelJS.Workbook();
  const ws = wb.addWorksheet('Scrub BOM');
  ws.addRow(['FG', 'CPN', 'Quantity']);
  ws.addRow(['FG_A', 'C-1', 5]);
  ws.addRow(['FG_A', '', 'x']);
  const buf = await wb.xlsx.writeBuffer();
  return new File([buf], 'customer bom.xlsx');
}

describe('markUpBom', () => {
  it('marks each flagged cell red, keeps the others, and lists every issue on a Fix list tab', async () => {
    const file = await bomFile();
    const issues = [
      { sheet: 'Scrub BOM', col: 'B', row: 3, message: 'cpn is blank' },
      { sheet: 'Scrub BOM', col: 'C', row: 3, message: 'quantity is text', value: 'x' },
      { sheet: 'No such tab', col: 'A', row: 1, message: 'sheet missing' },
    ];
    const { blob, marked, unplaced } = await markUpBom(file, issues);
    expect(marked).toBe(2);
    expect(unplaced.map((u) => u.message)).toEqual(['sheet missing']);

    const out = new ExcelJS.Workbook();
    await out.xlsx.load(await blob.arrayBuffer());
    const ws = out.getWorksheet('Scrub BOM')!;
    expect(ws.getCell('B3').fill).toMatchObject({ type: 'pattern', fgColor: { argb: 'FFF8D7DA' } });
    expect((ws.getCell('A2').fill as { fgColor?: { argb?: string } } | undefined)?.fgColor?.argb).not.toBe('FFF8D7DA');
    expect(ws.getCell('B2').value).toBe('C-1');
    const fix = out.getWorksheet('Fix list')!;
    expect(fix.rowCount).toBe(4);
    expect(fix.getRow(2).getCell(2).value).toBe('B3');
  });

  it('names the marked copy after the file', () => {
    expect(markedName('customer bom.xlsx')).toBe('customer bom - to fill in.xlsx');
    expect(markedName('bom')).toBe('bom - to fill in.xlsx');
  });
});
