import { describe, expect, it } from 'vitest';
import { NO_FILTERS, applyFilters, summarise, toCsv, type PortfolioRow } from '@/components/execution/portfolioSummary';

const BUCKETS = ['up to 8 weeks', '9 to 16 weeks'];

const rows: PortfolioRow[] = [
  { rfq_id: 'RFQ-1', customer: 'Acme', project: 'P1', currency: 'USD', buy: 100, final_buy: 150, excess_cost: 10, rows: 10, priced: 8, critical: 2, go_no_go: 'GO',
    lead_time: { 'up to 8 weeks': 3, '9 to 16 weeks': 1 }, commodity_excess: { PASSIVE: 6, ACTIVE: 4 } },
  { rfq_id: 'RFQ-2', customer: 'Acme', project: 'P2', currency: 'USD', buy: 200, final_buy: 210, excess_cost: 5, rows: 20, priced: 10, critical: 0, go_no_go: 'NO GO',
    lead_time: { 'up to 8 weeks': 2 }, commodity_excess: { PASSIVE: 5 } },
  { rfq_id: 'RFQ-3', customer: 'Beta', project: 'P3', currency: 'EUR', buy: 999, final_buy: 999, excess_cost: 999, rows: 99, priced: 99, critical: 9, go_no_go: 'GO',
    lead_time: { 'up to 8 weeks': 99 }, commodity_excess: { PASSIVE: 999 } },
  { rfq_id: 'RFQ-4', error: 'could not be read' },
];

describe('applyFilters', () => {
  it('keeps every row with no filter', () => {
    expect(applyFilters(rows, NO_FILTERS)).toHaveLength(4);
  });

  it('filters by customer, go/no-go and RFQ text together', () => {
    expect(applyFilters(rows, { ...NO_FILTERS, customer: 'Acme' }).map((r) => r.rfq_id)).toEqual(['RFQ-1', 'RFQ-2']);
    expect(applyFilters(rows, { ...NO_FILTERS, go: 'NO GO' }).map((r) => r.rfq_id)).toEqual(['RFQ-2']);
    expect(applyFilters(rows, { ...NO_FILTERS, customer: 'Acme', query: '2' }).map((r) => r.rfq_id)).toEqual(['RFQ-2']);
    expect(applyFilters(rows, { ...NO_FILTERS, query: '  rfq-3 ' }).map((r) => r.rfq_id)).toEqual(['RFQ-3']);
  });
});

describe('summarise', () => {
  it('adds only RFQs in the main currency and counts the others apart', () => {
    const s = summarise(rows, 'USD', BUCKETS);
    expect(s.total).toBe(3);
    expect(s.counted.map((r) => r.rfq_id)).toEqual(['RFQ-1', 'RFQ-2']);
    expect(s.otherCurrency).toBe(1);
    expect(s.buy).toBe(300);
    expect(s.finalBuy).toBe(360);
    expect(s.excess).toBe(15);
    expect(s.critical).toBe(2);
  });

  it('computes the variance and costing share the way the server does', () => {
    const s = summarise(rows, 'USD', BUCKETS);
    expect(s.buyVariance).toBeCloseTo((360 - 300) / 300, 10);
    expect(s.costingPct).toBeCloseTo(18 / 30, 10);
  });

  it('sums lead time and commodity excess over the main-currency RFQs only', () => {
    const s = summarise(rows, 'USD', BUCKETS);
    expect(s.lead).toEqual({ 'up to 8 weeks': 5, '9 to 16 weeks': 1 });
    expect(s.commodity).toEqual({ PASSIVE: 11, ACTIVE: 4 });
  });

  it('gives no variance when there is no baseline buy value', () => {
    const s = summarise([{ rfq_id: 'R', currency: 'USD', buy: 0, final_buy: 5 }], 'USD', BUCKETS);
    expect(s.buyVariance).toBeNull();
    expect(s.costingPct).toBeNull();
  });

  it('counts a missing final buy as not stored, not as zero', () => {
    const s = summarise([{ rfq_id: 'R', currency: 'USD', buy: 10, final_buy: null }], 'USD', BUCKETS);
    expect(s.cashRfqs).toBe(0);
  });
});

describe('toCsv', () => {
  it('writes one line per readable RFQ, quoting values that need it', () => {
    const csv = toCsv([{ rfq_id: 'RFQ-9', customer: 'Acme, Ltd', project: 'say "hi"', currency: 'USD', buy: 1.5, go_no_go: 'GO' }, { rfq_id: 'RFQ-10', error: 'x' }]);
    const [head, line, ...rest] = csv.split('\n');
    expect(head.startsWith('RFQ,Customer,Project,Currency')).toBe(true);
    expect(line).toBe('RFQ-9,"Acme, Ltd","say ""hi""",USD,,1.5,,,,,,,GO');
    expect(rest).toEqual([]);
  });
});
