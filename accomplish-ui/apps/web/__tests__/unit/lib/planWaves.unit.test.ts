import { describe, it, expect } from 'vitest';
import { MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, planWaves } from '@/lib/rfqAttachments';

const sized = (name: string, size: number) => Object.defineProperty(new File(['x'], name), 'size', { value: size }) as File;
const names = (waves: File[][]) => waves.map((w) => w.map((f) => f.name));
const many = (n: number, size = 1000) => Array.from({ length: n }, (_, i) => sized(`f${i}.csv`, size));

describe('planWaves: an over-limit pick becomes sequential waves', () => {
  it('makes no wave for no files', () => {
    expect(planWaves([])).toEqual({ waves: [], rejected: [] });
  });

  it('keeps a pick exactly at the limits in one wave', () => {
    expect(planWaves(many(MAX_FILES)).waves).toHaveLength(1);
    const exact = [sized('a.pdf', MAX_FILE_BYTES), sized('b.pdf', MAX_FILE_BYTES), sized('c.pdf', MAX_TOTAL_BYTES - 2 * MAX_FILE_BYTES)];
    expect(planWaves(exact).waves).toHaveLength(1);
  });

  it('splits 23 small files into 3 waves, in order', () => {
    const { waves } = planWaves(many(23));
    expect(waves.map((w) => w.length)).toEqual([10, 10, 3]);
    expect(waves.flat().map((f) => f.name)).toEqual(many(23).map((f) => f.name));
  });

  it('opens a new wave when the bytes would pass 60 MB', () => {
    const mb = 1024 * 1024;
    expect(names(planWaves([sized('a', 25 * mb), sized('b', 25 * mb), sized('c', 25 * mb), sized('d', mb)]).waves)).toEqual([['a', 'b'], ['c', 'd']]);
  });

  it('rejects a file over 25 MB with the usual reason instead of giving it a wave', () => {
    const huge = sized('huge.pdf', MAX_FILE_BYTES + 1);
    const out = planWaves([huge]);
    expect(out.waves).toEqual([]);
    expect(out.rejected).toEqual([{ file: huge, reason: 'too_large' }]);
    expect(names(planWaves([sized('a.csv', 10), huge, sized('b.csv', 10)]).waves)).toEqual([['a.csv', 'b.csv']]);
  });
});
