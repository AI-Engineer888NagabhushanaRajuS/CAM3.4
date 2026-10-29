import { RoutingProfileCard } from './RoutingProfileCard';
import { useRoutingProfilePanel } from './useRoutingProfilePanel';

interface RoutingProfilePanelProps {
  refreshTrigger?: number;
}

// Replaces SkillsPanel.tsx's role for this tab. No search bar, no filter
// bar, no refresh spinner (8 fixed items, changes are already live/
// optimistic) -- a vertical list, not SkillsPanel's 2-col grid, since
// execution order is part of what this page communicates.
export function RoutingProfilePanel({ refreshTrigger }: RoutingProfilePanelProps) {
  const { loading, skills, pendingSkillCode, error, handleToggle } = useRoutingProfilePanel(refreshTrigger);

  if (loading) {
    return (
      <div className="flex h-[480px] items-center justify-center text-sm text-muted-foreground">
        Loading routing profile...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        These toggles govern every future RFQ run until changed again -- this is a shared, app-wide setting, not per-RFQ.
      </p>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex max-h-[480px] flex-col gap-2 overflow-y-auto pr-1">
        {skills.map((skill) => (
          <RoutingProfileCard
            key={skill.skillCode}
            skill={skill}
            disabled={pendingSkillCode === skill.skillCode}
            onToggle={(code) => { void handleToggle(code); }}
          />
        ))}
      </div>
    </div>
  );
}
