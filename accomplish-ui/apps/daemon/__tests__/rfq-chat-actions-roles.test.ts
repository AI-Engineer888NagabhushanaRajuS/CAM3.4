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
    // notes.txt is not a spreadsheet extension: it is turned away before roles matter
    expect(out.blocked).toEqual([expect.stringContaining('notes.txt is not .xlsx')]);
    const ok = await run([att('a1', 'scrub.xlsx', 'scrub_bom'), att('a2', 'v.xlsx', 'volume')]);
    expect(ok.files.map((f) => [f.role, f.name])).toEqual([['BOM', 'scrub.xlsx'], ['VOLUME', 'v.xlsx']]);
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
