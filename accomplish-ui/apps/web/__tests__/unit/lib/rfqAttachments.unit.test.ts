import { describe, it, expect } from 'vitest';
import { fitsOneScan, formatBytes, MAX_FILE_BYTES, MAX_FILES, triageFiles } from '@/lib/rfqAttachments';

const file = (name: string, size = 1000) => new File([new Uint8Array(Math.min(size, 16))], name, { type: '' }) as File & { size: number };
const sized = (name: string, size: number) => Object.defineProperty(new File(['x'], name), 'size', { value: size }) as File;

describe('which picked files may be sent', () => {
  it('keeps supported documents and turns the rest away with a reason', () => {
    const t = triageFiles([
      file('quote.xlsx'), file('terms.PDF'), file('notes.docx'), file('setup.exe'), file('~$quote.xlsx'), file('.DS_Store'), sized('empty.csv', 0), sized('huge.pdf', MAX_FILE_BYTES + 1),
    ]);
    expect(t.usable.map((f) => f.name)).toEqual(['quote.xlsx', 'terms.PDF', 'notes.docx']);
    expect(Object.fromEntries(t.rejected.map((r) => [r.file.name, r.reason]))).toEqual({
      'setup.exe': 'unsupported', '~$quote.xlsx': 'system', '.DS_Store': 'system', 'empty.csv': 'empty', 'huge.pdf': 'too_large',
    });
  });

  it('rejects a second copy, within the pick and against files already attached', () => {
    const t = triageFiles([file('a.csv'), file('A.csv'), file('b.csv')], ['b.CSV']);
    expect(t.usable.map((f) => f.name)).toEqual(['a.csv']);
    expect(t.rejected.map((r) => r.reason)).toEqual(['duplicate', 'duplicate']);
  });

  it('never throws on an empty pick', () => {
    expect(triageFiles([])).toEqual({ usable: [], rejected: [] });
  });
});

describe('what one scan may carry', () => {
  it('needs at least one file, at most ten, and a bounded total', () => {
    expect(fitsOneScan([]).ok).toBe(false);
    expect(fitsOneScan([file('a.csv')]).ok).toBe(true);
    expect(fitsOneScan(Array.from({ length: MAX_FILES + 1 }, (_, i) => file(`f${i}.csv`))).reason).toContain('Untick 1');
    expect(fitsOneScan([sized('a.pdf', 25 * 1024 * 1024), sized('b.pdf', 25 * 1024 * 1024), sized('c.pdf', 25 * 1024 * 1024)]).reason).toContain('per scan');
  });

  it('prints sizes people can read', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
});
