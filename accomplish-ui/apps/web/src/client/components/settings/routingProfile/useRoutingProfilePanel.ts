import { useCallback, useEffect, useState } from 'react';
import { getAccomplish, type RoutingProfileSkill } from '@/lib/accomplish';

export interface UseRoutingProfilePanelResult {
  loading: boolean;
  skills: RoutingProfileSkill[]; // already sorted by skillIndex from the daemon
  pendingSkillCode: string | null; // which row has an in-flight toggle, for per-row disabling
  error: string | null;
  handleToggle: (skillCode: string) => Promise<void>;
}

// Mirrors useSkillsPanel.ts's shape but far simpler -- no search/filter/
// resync, this is a fixed list of exactly 8 DB-backed rows, not an
// open-ended filesystem-scanned collection.
export function useRoutingProfilePanel(refreshTrigger?: number): UseRoutingProfilePanelResult {
  const [skills, setSkills] = useState<RoutingProfileSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingSkillCode, setPendingSkillCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isCurrent = true;
    setLoading(true);
    getAccomplish()
      .rfqGetRoutingProfileSkills()
      .then(({ skills: fetched }) => {
        // Hide Standard_BOM_Flow's centum_* skills from this panel -- this
        // project only runs RFQ_Flow (intake__*/distributor__*) through this
        // UI, so surfacing toggles for a pipeline that never executes here
        // just invites confusion. The RPC itself still returns the full set
        // unfiltered (App.tsx's own call to rfqGetRoutingProfileSkills
        // relies on the complete list for its sidebar lock-state logic).
        const rfqFlowOnly = fetched.filter((s) => !s.skillCode.startsWith('centum_'));
        if (isCurrent) { setSkills(rfqFlowOnly); }
      })
      .catch((err: unknown) => {
        if (isCurrent) { setError(err instanceof Error ? err.message : 'Failed to load'); }
      })
      .finally(() => {
        if (isCurrent) { setLoading(false); }
      });
    return () => { isCurrent = false; };
  }, [refreshTrigger]);

  const handleToggle = useCallback(async (skillCode: string) => {
    const target = skills.find((s) => s.skillCode === skillCode);
    if (!target) { return; }
    const nextEnabled = !target.isEnabled;
    setPendingSkillCode(skillCode);
    // Optimistic update -- the toggle takes effect on the very next pipeline
    // execute call regardless, and the rollback below reconciles any drift.
    setSkills((prev) => prev.map((s) => (s.skillCode === skillCode ? { ...s, isEnabled: nextEnabled } : s)));
    try {
      await getAccomplish().rfqSetRoutingProfileSkillEnabled({ skillCode, enabled: nextEnabled });
    } catch (err) {
      setSkills((prev) => prev.map((s) => (s.skillCode === skillCode ? { ...s, isEnabled: !nextEnabled } : s)));
      setError(err instanceof Error ? err.message : 'Failed to toggle');
    } finally {
      setPendingSkillCode(null);
    }
  }, [skills]);

  return { loading, skills, pendingSkillCode, error, handleToggle };
}
