import { describe, expect, it } from 'vitest';
import { toRow } from '@/components/execution/ConflictPopup';

describe('conflict rows', () => {
  it('preselects QuoteWin where it has a price, and marks a row whose sources disagree', () => {
    const r = toRow({
      conflict_id: 'c1', cpn: 'R01', volume_no: '1',
      available_sources: { costing: { price_conv: 1.5 }, qw: { price_conv: 1.7 } },
    });
    expect(r.choice).toBe('qw');
    expect(r.differs).toBe(true);
    expect(r.prices).toEqual({ costing: 1.5, erp: null, qw: 1.7 });
  });

  it('leaves a row with no QuoteWin price unpicked, so a person must choose', () => {
    const r = toRow({ conflict_id: 'c2', cpn: 'R02', volume_no: '2', available_sources: { costing: { price_conv: 2 }, erp: { price_conv: 2 } } });
    expect(r.choice).toBe('');
    expect(r.differs).toBe(false);
  });

  it('ignores a source with no numeric price', () => {
    const r = toRow({ conflict_id: 'c3', cpn: 'R03', volume_no: '1', available_sources: { costing: { price_conv: null }, qw: { price_conv: 'n/a' } } });
    expect(r.prices).toEqual({ costing: null, erp: null, qw: null });
    expect(r.differs).toBe(false);
  });
});
