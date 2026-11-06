import { describe, it, expect } from 'vitest';
import { intakeReadiness, type FileRole, type ScanResult } from '@/lib/rfqAttachments';

const r = (name: string, role?: FileRole, over: Partial<ScanResult> = {}): ScanResult => ({
  name, size: 1, sha256: name, clamav: { verdict: 'clean' }, repel: { verdict: 'clean' }, decision: 'released', attachment_id: name, role, ...over,
});

describe('intakeReadiness (mirrors the daemon create_rfq choice)', () => {
  it('one BOM workbook is enough; its Settings sheet carries the volumes, a volume file is named when there is one', () => {
    expect(intakeReadiness([r('a.xlsx', 'scrub_bom')])).toMatchObject({ ready: true, message: expect.stringContaining('Settings sheet carries the volumes') });
    expect(intakeReadiness([r('a.xlsx', 'scrub_bom'), r('v.xlsx', 'volume')])).toMatchObject({ ready: true, message: expect.stringContaining('v.xlsx the volume file') });
  });
  it('two BOM workbooks or two volume files need a decision', () => {
    expect(intakeReadiness([r('a.xlsx', 'scrub_bom'), r('b.xlsx', 'scrub_bom')]).ready).toBe(false);
    expect(intakeReadiness([r('a.xlsx', 'scrub_bom'), r('v1.xlsx', 'volume'), r('v2.xlsx', 'volume')]).ready).toBe(false);
  });
  it('a plain BOM is refused with its own reason', () => {
    expect(intakeReadiness([r('b.xlsx', 'bom', { problems: ['No sheet named SCRUB BOM'] })])).toEqual({ ready: false, message: 'b.xlsx cannot start the pipeline: No sheet named SCRUB BOM' });
  });
  it('QuoteWin alone is not a way to create an RFQ; nothing released says so; files that were not released do not count', () => {
    expect(intakeReadiness([r('q.xlsx', 'quotewin')]).message).toContain('ERP & Quoting tools');
    expect(intakeReadiness([]).message).toBe('No file was released yet.');
    expect(intakeReadiness([r('a.xlsx', 'scrub_bom', { decision: 'quarantined' })]).ready).toBe(false);
    expect(intakeReadiness([r('n.txt', 'document')]).message).toContain('None of the released files is a BOM workbook');
  });
});
