import { useMemo, useSyncExternalStore } from 'react';

/**
 * How the Reports & Analytics dashboard is laid out for this viewer: the BOM matrix view and size, and which sections show.
 * The dashboard's own selectors and the chat ("switch the matrix to heat map") both write here, so they never disagree.
 * Browser storage only: a view preference, never data. Unreadable storage means the defaults.
 */
export const DASHBOARD_SECTIONS = ['bom_matrix', 'cost_3d', 'live_feed', 'formula_check'] as const;
export type DashboardSection = (typeof DASHBOARD_SECTIONS)[number];

export interface DashboardPrefs {
  matrixView?: 'line' | 'heat';
  matrixTop?: 10 | 25 | 50 | 100 | 0;
  sections?: Partial<Record<DashboardSection, boolean>>;
}

const KEY = 'cam-dashboard-prefs';
const EVENT = 'cam:dashboard-prefs';

function readRaw(): string {
  try {
    return localStorage.getItem(KEY) ?? '';
  } catch {
    return '';
  }
}

export function readPrefs(): DashboardPrefs {
  try {
    return (JSON.parse(readRaw() || '{}') as DashboardPrefs) ?? {};
  } catch {
    return {};
  }
}

/** Merges the given settings into the saved ones, then tells every mounted dashboard. */
export function applyPrefs(next: DashboardPrefs): void {
  const current = readPrefs();
  const merged: DashboardPrefs = { ...current, ...next, sections: { ...current.sections, ...next.sections } };
  try {
    localStorage.setItem(KEY, JSON.stringify(merged));
  } catch {
    // Storage blocked: the change still applies to the open dashboard below.
  }
  window.dispatchEvent(new Event(EVENT));
}

const subscribe = (onChange: () => void) => {
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
};

/** The current settings; re-renders when applyPrefs runs. The raw string is the snapshot, so the hook stays stable between changes. */
export function useDashboardPrefs(): DashboardPrefs {
  const raw = useSyncExternalStore(subscribe, readRaw, () => '');
  return useMemo(() => {
    try {
      return (JSON.parse(raw || '{}') as DashboardPrefs) ?? {};
    } catch {
      return {};
    }
  }, [raw]);
}

export const sectionShown = (prefs: DashboardPrefs, section: DashboardSection): boolean => prefs.sections?.[section] !== false;
