import { describe, it, expect } from 'vitest';
import { parseDashboardChange, dashboardChunks, stepChunks } from '../src/rfq-chat/rfq-chat-dashboard.js';
import { classify, controlIntent } from '../src/rfq-chat/rfq-chat-intent.js';

describe('parseDashboardChange', () => {
  it('reads a matrix view and size into prefs', () => {
    expect(parseDashboardChange('switch the BOM matrix to heat map')?.prefs).toEqual({ matrixView: 'heat' });
    expect(parseDashboardChange('show the matrix as a line chart, top 25')?.prefs).toEqual({ matrixView: 'line', matrixTop: 25 });
  });

  it('hides and shows named sections, and refuses a size the dashboard does not offer', () => {
    expect(parseDashboardChange('hide the 3D chart')?.prefs).toEqual({ sections: { cost_3d: false } });
    expect(parseDashboardChange('bring back the live feed')?.prefs).toEqual({ sections: { live_feed: true } });
    expect(parseDashboardChange('show top 7 parts in the matrix')?.prefs.matrixTop).toBeUndefined();
  });

  it('returns null when the sentence changes nothing the dashboard has', () => {
    expect(parseDashboardChange('change the colour of the moon')).toBeNull();
  });
});

describe('routing', () => {
  it('a dashboard change is a control, not a data question', () => {
    expect(controlIntent('switch the BOM matrix to heat map')).toBe('dashboard');
    expect(classify('switch the BOM matrix to heat map')).toBe('dashboard');
  });

  it('an explain question about a chart goes to the grounded data path', () => {
    expect(controlIntent('explain the cost per set chart')).toBeNull();
    expect(classify('explain the cost per set chart')).toBe('data');
  });

  it('a list-of-top-parts question with no dashboard word is still data', () => {
    expect(controlIntent('which are the top 10 parts by cost?')).toBeNull();
  });
});

describe('dashboardChunks', () => {
  it('cites each 3D-chart row, the summary, each card and the matrix to the dashboard', () => {
    const chunks = dashboardChunks('RFQ-1', {
      summary: { volumes: ['VL-1'], fgs: [{ assembly: 'HCV_BMS_MB', 'CBOM Cost VL-1': 70.91603 }] },
      currency: 'USD',
      bom_matrix: { assemblies: ['A'], parts: [{ part: 'P1', quantities: { A: 2 }, grand_total: 2, commodity: null }] },
    });
    expect(chunks.map((c) => c.citation.label)).toEqual([
      'Dashboard: Cost per set, HCV_BMS_MB',
      'Dashboard: Summary cards',
      'Dashboard: Currency',
      'Dashboard: BOM matrix',
    ]);
    expect(chunks[0].text).toContain('70.91603');
  });

  it('adds one live-feed row per step, with its status and what it reported', () => {
    const rows = stepChunks('RFQ-1', [{ name: 'Analyze Feasibility', status: 'completed', detail: '56 high risk', at: '2026-11-17T00:00:00.000Z' }]);
    expect(rows[0].text).toContain('Analyze Feasibility is completed: 56 high risk');
    expect(rows[0].citation.label).toBe('Live feed: Analyze Feasibility');
  });
});
