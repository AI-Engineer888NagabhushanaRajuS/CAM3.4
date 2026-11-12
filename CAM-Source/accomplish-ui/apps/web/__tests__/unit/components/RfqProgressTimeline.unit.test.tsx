import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RfqProgressTimeline } from '@/components/rfq/RfqProgressTimeline';

const step = (over: Record<string, unknown>) => ({ skillCode: 'c', skillName: 'Step', macroCategory: 1, stepStatus: 'completed', ...over });

describe('progress timeline says what each step really did', () => {
  it('a skipped step shows its reason, never reads as done', () => {
    render(<RfqProgressTimeline entries={[step({ skillName: 'Standardize Costing Sheet', stepStatus: 'skipped', detail: 'no Costing Sheet uploaded' })]} />);
    expect(screen.getByText('Standardize Costing Sheet')).toBeTruthy();
    expect(screen.getByText('Skipped: no Costing Sheet uploaded')).toBeTruthy();
  });

  it('a step that ran but did nothing useful carries its detail as a warning', () => {
    render(<RfqProgressTimeline entries={[step({ skillName: 'Export', detail: '20 worksheets, 0 of 502 rows priced', warning: true })]} />);
    expect(screen.getByText('20 worksheets, 0 of 502 rows priced').className).toContain('amber');
  });

  it('a plain completed step with a detail shows it quietly', () => {
    render(<RfqProgressTimeline entries={[step({ skillName: 'Export', detail: '20 worksheets, 388 of 502 rows priced' })]} />);
    expect(screen.getByText('20 worksheets, 388 of 502 rows priced').className).toContain('muted');
  });

  it('with no entries it says there is no progress yet', () => {
    render(<RfqProgressTimeline entries={[]} />);
    expect(screen.getByText(/No progress yet/)).toBeTruthy();
  });
});
