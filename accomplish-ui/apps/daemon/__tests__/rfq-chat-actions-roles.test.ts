import { describe, expect, it } from 'vitest';
import { resolveFiles } from '../src/rfq-chat/rfq-chat-actions-parse.js';
import type { ActionDeps, Attachment } from '../src/rfq-chat/rfq-chat-actions-types.js';

/** SPEC-022: what the bridge read INSIDE the released files wins over their names. */
const att = (id: string, name: string, role?: string, problems?: string[]): Attachment => ({ attachmentId: id, name, sha256: null, role, problems });
const run = async (list: Attachment[]) =>
  resolveFiles('CHAT-1', list.map((a) => ({ attachmentId: a.attachmentId, name: a.name })), { listAttachments: async () => list } as unknown as ActionDeps);

describe('create_rfq file choice by role', () => {
  it('uses the SCRUB BOM workbook as BOM whatever it is called, and the workbook itself as the volume when there is no volume file', async () => {
    const out = await run([att('a1', 'Centum_Export_final.xlsx', 'scrub_bom')]);
    expect(out.missing).toEqual([]);
    expect(out.files.map((f) => [f.role, f.name])).toEqual([['BOM', 'Centum_Export_final.xlsx'], ['VOLUME', 'Centum_Export_final.xlsx']]);
  });

  it('takes a recognised volume file as the volume, and ignores other files', async () => {
    const out = await run([att('a1', 'scrub.xlsx', 'scrub_bom'), att('a2', 'v.xlsx', 'volume'), att('a3', 'notes.txt', 'document')]);
    // notes.txt is not a spreadsheet: it is left out as reference, it does not block the others
    expect(out.blocked).toEqual([]);
    expect(out.files.map((f) => [f.role, f.name])).toEqual([['BOM', 'scrub.xlsx'], ['VOLUME', 'v.xlsx']]);
    expect(out.note).toContain('Left out as reference only: notes.txt');
  });

  it('picks the one BOM workbook out of a folder dump and says what it left out', async () => {
    const out = await run([
      att('d1', 'QCAD - Download.pdf', 'document'), att('d2', 'WORK_REPORT.md', 'document'), att('d3', 'Gerber_Files_1_pcb_info.pdf', 'document'),
      att('x1', 'Master Capture Checklists.xlsx', 'unknown'), att('b1', 'Triode_Master.xlsx', 'scrub_bom'), att('q1', 'quote_export.xlsx', 'quotewin'),
    ]);
    expect(out.missing).toEqual([]);
    expect(out.files.map((f) => f.name)).toEqual(['Triode_Master.xlsx', 'Triode_Master.xlsx']);
    expect(out.note).toContain('Not used: Master Capture Checklists.xlsx, quote_export.xlsx');
    expect(out.note).toContain('Left out as reference only: QCAD - Download.pdf, WORK_REPORT.md');
  });

  it('with no BOM workbook among them, names what each spreadsheet is and what to attach', async () => {
    const out = await run([att('d1', 'QCAD.pdf', 'document'), att('x1', 'Checklists.xlsx', 'unknown'), att('q1', 'quote_export.xlsx', 'quotewin')]);
    expect(out.files).toEqual([]);
    expect(out.missing[0]).toContain('Checklists.xlsx: not a BOM, volume or QuoteWin layout');
    expect(out.missing[0]).toContain('quote_export.xlsx: a QuoteWin export');
    expect(out.missing[0]).toContain('SCRUB BOM');
    expect(out.missing[0]).toContain('Left out as reference only: QCAD.pdf');
  });

  it('only documents: says none is a spreadsheet', async () => {
    const out = await run([att('d1', 'a.pdf', 'document'), att('d2', 'b.docx', 'document')]);
    expect(out.missing[0]).toContain('None of the 2 attached files is a spreadsheet');
  });

  it('refuses a plain BOM with the reason and issues no files', async () => {
    const reason = "No sheet named SCRUB BOM (sheets: BOM). The first pipeline step would reject this file as invalid input; use the Scrub BOM workbook.";
    const out = await run([att('a1', 'Centum_BOM.xlsx', 'bom', [reason]), att('a2', 'Volume_File.xlsx', 'volume')]);
    expect(out.files).toEqual([]);
    expect(out.missing[0]).toContain('Centum_BOM.xlsx cannot be used');
    expect(out.missing[0]).toContain('SCRUB BOM');
  });

  it('asks which one when two files both have a SCRUB BOM sheet', async () => {
    const out = await run([att('a1', 'one.xlsx', 'scrub_bom'), att('a2', 'two.xlsx', 'scrub_bom')]);
    expect(out.files).toEqual([]);
    expect(out.missing[0]).toContain('Which of one.xlsx and two.xlsx is the BOM');
  });

  it('falls back to the old name rule when no role is known (older bridge or unknown layouts)', async () => {
    const out = await run([att('a1', 'my_bom.xlsx'), att('a2', 'my_volume.xlsx', 'unknown')]);
    expect(out.files.map((f) => [f.role, f.name])).toEqual([['BOM', 'my_bom.xlsx'], ['VOLUME', 'my_volume.xlsx']]);
  });
});
