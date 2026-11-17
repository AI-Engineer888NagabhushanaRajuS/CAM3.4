// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { fixQueueOf, type ScanResult } from '@/lib/rfqAttachments';

const file = (name: string, errors: number, extra: Partial<ScanResult> = {}): ScanResult => ({
  name,
  size: 1,
  sha256: name,
  clamav: { verdict: 'clean' },
  repel: { verdict: 'clean' },
  decision: 'released',
  attachment_id: `id-${name}`,
  check: { checked: true, ok: errors === 0, errors, warnings: 0, rows: 1, issues: [], truncated: false },
  ...extra,
} as ScanResult);

describe('fixQueueOf: one workbook popup per file that needs fixing, in upload order', () => {
  it('one flagged file gives one popup', () => {
    expect(fixQueueOf([file('a.xlsx', 2)], new Set())).toEqual([{ attachmentId: 'id-a.xlsx', name: 'a.xlsx' }]);
  });

  it('three flagged files give three popups, back to back, in upload order', () => {
    const q = fixQueueOf([file('a.xlsx', 1), file('b.xlsx', 3), file('c.xlsx', 1)], new Set());
    expect(q.map((x) => x.name)).toEqual(['a.xlsx', 'b.xlsx', 'c.xlsx']);
  });

  it('all files flagged give all popups', () => {
    const files = ['1', '2', '3', '4'].map((n) => file(`f${n}.xlsx`, 1));
    expect(fixQueueOf(files, new Set())).toHaveLength(4);
  });

  it('a file already closed or saved leaves the queue, the rest stay', () => {
    const files = [file('a.xlsx', 1), file('b.xlsx', 1)];
    expect(fixQueueOf(files, new Set(['id-a.xlsx'])).map((x) => x.name)).toEqual(['b.xlsx']);
    expect(fixQueueOf(files, new Set(['id-a.xlsx', 'id-b.xlsx']))).toEqual([]);
  });

  it('clean files, files not checked, rejected files and files without an id never queue', () => {
    const files = [
      file('clean.xlsx', 0),
      file('unchecked.xlsx', 5, { check: undefined }),
      file('quarantined.xlsx', 5, { decision: 'quarantined' }),
      file('noid.xlsx', 5, { attachment_id: null }),
      file('flagged.xlsx', 2),
    ];
    expect(fixQueueOf(files, new Set()).map((x) => x.name)).toEqual(['flagged.xlsx']);
  });

  it('no results, no popups', () => {
    expect(fixQueueOf([], new Set())).toEqual([]);
  });
});
