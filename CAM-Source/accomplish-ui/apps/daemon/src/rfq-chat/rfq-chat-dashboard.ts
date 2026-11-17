/**
 * The Reports & Analytics dashboard, as the chat sees it: rules that read "change the dashboard" into view settings the UI
 * applies (no model decides them), and the dashboard's own numbers as citable evidence for "explain this chart".
 */
import type { MessageCitation } from '@accomplish_ai/agent-core';

export const DASHBOARD_SECTIONS = ['bom_matrix', 'cost_3d', 'live_feed', 'formula_check'] as const;
export type DashboardSection = (typeof DASHBOARD_SECTIONS)[number];
export const MATRIX_TOP = [10, 25, 50, 100, 0] as const; // 0 = all parts

export interface DashboardPrefs {
  matrixView?: 'line' | 'heat';
  matrixTop?: (typeof MATRIX_TOP)[number];
  sections?: Partial<Record<DashboardSection, boolean>>;
}

/** Any dashboard word: a question with one of these is about the dashboard's charts and figures. */
export const DASHBOARD_NOUN = /\b(dashboards?|charts?|graphs?|matrix|heat ?map|3d|bars?|cards?|live (feed|view)|see your work|formula (engine )?check|reports? (view|page|screen|dashboard)|analytics)\b/i;
/** A dashboard word plus a change word, or a view setting named outright: "switch the matrix to heat map", "hide the 3D chart". */
export const DASHBOARD_CHANGE = /\b(change|switch|hide|remove|turn (on|off)|bring back|collapse|use|top\s*\d+|all parts|show)\b[^.?!\n]{0,40}\b(dashboards?|charts?|graphs?|matrix|heat ?map|line chart|3d|bars?|live|feed|formula|parts)\b|\b(heat ?map|line chart)\b|\btop\s*(10|25|50|100)\b/i;

const SECTION_WORDS: Array<[DashboardSection, RegExp]> = [
  ['bom_matrix', /\b(bom matrix|matrix|heat ?map|line chart)\b/i],
  ['cost_3d', /\b(3d|cost (per set )?chart|volume bars?|bars?)\b/i],
  ['live_feed', /\b(live|see your work|feed|timeline|steps)\b/i],
  ['formula_check', /\bformula (engine )?check|formula\b/i],
];
const HIDE = /\b(hide|remove|close|turn off|collapse)\b/i;
const SHOW = /\b(show|unhide|bring back|turn on|display|add)\b/i;

const SECTION_LABEL: Record<DashboardSection, string> = {
  bom_matrix: 'BOM matrix',
  cost_3d: '3D cost chart',
  live_feed: 'live feed',
  formula_check: 'formula check',
};

/** The view settings a change sentence asks for, or null when it asks for none that the dashboard has. */
export function parseDashboardChange(question: string): { prefs: DashboardPrefs; summary: string } | null {
  const prefs: DashboardPrefs = {};
  const parts: string[] = [];
  if (/\bheat ?map\b/i.test(question)) {
    prefs.matrixView = 'heat';
    parts.push('the BOM matrix as a heat map');
  } else if (/\bline\b/i.test(question) && /\b(matrix|chart|graph|line chart)\b/i.test(question)) {
    prefs.matrixView = 'line';
    parts.push('the BOM matrix as a line chart');
  }
  const top = /\btop\s*(\d+)\b/i.exec(question);
  if (top && (MATRIX_TOP as readonly number[]).includes(Number(top[1]))) {
    prefs.matrixTop = Number(top[1]) as (typeof MATRIX_TOP)[number];
    parts.push(`the top ${top[1]} parts`);
  } else if (/\ball (parts|rows)\b/i.test(question)) {
    prefs.matrixTop = 0;
    parts.push('all parts');
  }
  // A section is shown or hidden only when the sentence says so: hide/remove wins, show/bring back/display shows it.
  for (const [section, word] of SECTION_WORDS) {
    if (!word.test(question) || (section === 'bom_matrix' && prefs.matrixView !== undefined)) continue;
    if (!HIDE.test(question) && !SHOW.test(question)) continue;
    const shown = !HIDE.test(question);
    prefs.sections = { ...prefs.sections, [section]: shown };
    parts.push(`${SECTION_LABEL[section]} ${shown ? 'shown' : 'hidden'}`);
  }
  if (parts.length === 0) return null;
  return { prefs, summary: parts.join(', ') };
}

/** The dashboard's figures for one RFQ as evidence rows: each card's stored numbers, cited to the dashboard. */
const CARDS: Array<[string, string]> = [
  ['price_control', 'Who set the price'],
  ['lead_time', 'Lead time'],
  ['cashflow', 'Final buy by payment term'],
  ['cashflow_totals', 'Cashflow totals'],
  ['excess_cost', 'Excess cost per volume'],
  ['commodity_excess', 'Excess cost per commodity'],
  ['uncosted_parts', 'Uncosted parts'],
  ['exceptions', 'Exceptions'],
  ['currency', 'Currency'],
  ['manifest', 'Workbook check'],
];

type Citation = MessageCitation;
type Chunk = { text: string; citation: Citation };
const cite = (rfqId: string, key: string, title: string): Citation => ({ sourceType: 'excel_export', identifier: { rfqId, dashboard: key }, label: `Dashboard: ${title}` });

/** One step of the live feed ("See your work"), as evidence: what ran, its status, and what it reported. */
export function stepChunks(rfqId: string, steps: Array<{ name: string; status: string; detail: string | null; at: string }>): Chunk[] {
  return steps.slice(-40).map((s) => ({
    text: `Live feed, ${s.at}: ${s.name} is ${s.status}${s.detail ? `: ${s.detail}` : ''}.`.slice(0, 400),
    citation: { sourceType: 'excel_export', identifier: { rfqId, dashboard: 'live_feed' }, label: `Live feed: ${s.name}` },
  }));
}

/** The dashboard's figures for one RFQ as evidence rows: each 3D-chart row, each card's stored numbers, the matrix; cited to the dashboard. */
export function dashboardChunks(rfqId: string, analytics: Record<string, unknown>): Chunk[] {
  const out: Chunk[] = [];
  const summary = analytics.summary as { volumes?: string[]; fgs?: Array<Record<string, unknown>>; totals?: unknown; moq_cost?: unknown; ext_vol_conv_price?: unknown } | undefined;
  // The 3D chart plots these rows: one cost-per-set figure per assembly and volume.
  for (const row of summary?.fgs ?? []) {
    const name = String(row.assembly ?? 'assembly');
    out.push({ text: `Dashboard, cost per set (3D chart) for ${name}: ${JSON.stringify(row).slice(0, 400)}`, citation: cite(rfqId, 'cost_3d', `Cost per set, ${name}`) });
  }
  if (summary) {
    out.push({
      text: `Dashboard, summary: volumes ${JSON.stringify(summary.volumes ?? [])}; totals ${JSON.stringify(summary.totals ?? null).slice(0, 300)}; MOQ cost ${JSON.stringify(summary.moq_cost ?? null)}; extended volume cost ${JSON.stringify(summary.ext_vol_conv_price ?? null)}.`.slice(0, 600),
      citation: cite(rfqId, 'summary', 'Summary cards'),
    });
  }
  for (const [key, title] of CARDS) {
    const value = analytics[key];
    if (value === undefined || value === null) continue;
    out.push({ text: `Dashboard, ${title}: ${JSON.stringify(value).slice(0, 700)}`, citation: cite(rfqId, key, title) });
  }
  const matrix = analytics.bom_matrix as { assemblies?: string[]; parts?: Array<{ part: string; grand_total: number | null }> } | undefined;
  if (matrix?.parts) {
    const top = [...matrix.parts].sort((a, b) => (b.grand_total ?? 0) - (a.grand_total ?? 0)).slice(0, 10);
    out.push({
      text: `Dashboard, BOM matrix: ${matrix.parts.length} parts across ${matrix.assemblies?.length ?? 0} assemblies. Top parts by total quantity: ${top.map((p) => `${p.part} (${p.grand_total ?? 0})`).join(', ')}.`,
      citation: { sourceType: 'excel_export', identifier: { rfqId, dashboard: 'bom_matrix' }, label: 'Dashboard: BOM matrix' },
    });
  }
  return out;
}
