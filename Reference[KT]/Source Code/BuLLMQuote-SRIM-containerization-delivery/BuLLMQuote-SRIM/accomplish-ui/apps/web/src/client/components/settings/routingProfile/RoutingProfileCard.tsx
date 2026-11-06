import { memo, useCallback } from 'react';
import type { RoutingProfileSkill } from '@/lib/accomplish';

interface RoutingProfileCardProps {
  skill: RoutingProfileSkill;
  onToggle: (skillCode: string) => void;
  disabled?: boolean; // true while an in-flight toggle request is pending for this row
}

// Visually modeled on SkillCard.tsx's header (title + toggle switch) and
// footer badge row, but simplified for this DB-backed concept: no dropdown
// menu, no delete/edit, no source-based badge/logo (none of those apply to a
// routing-profile skill). Badge shows macroCategoryName instead of source.
// Order number badge (skillIndex) is shown since execution order is a
// first-class part of this page's meaning, unlike generic skills.
export const RoutingProfileCard = memo(function RoutingProfileCard({
  skill,
  onToggle,
  disabled,
}: RoutingProfileCardProps) {
  const handleToggle = useCallback(() => {
    onToggle(skill.skillCode);
  }, [onToggle, skill.skillCode]);

  return (
    <div className="group rounded-xl border border-border bg-card p-3.5 transition-all duration-200 hover:border-primary hover:shadow-md">
      <div className="mb-1.5 flex items-start justify-between">
        <span className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
          <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border text-[10px] text-muted-foreground">
            {skill.skillIndex}
          </span>
          {skill.skillName}
        </span>
        <button
          onClick={handleToggle}
          disabled={disabled}
          className={`relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50 ${
            skill.isEnabled ? 'bg-primary' : 'bg-muted'
          }`}
          aria-label={skill.isEnabled ? `Disable ${skill.skillName}` : `Enable ${skill.skillName}`}
        >
          <span
            className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
              skill.isEnabled ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      <p className="mb-2.5 text-[11px] text-muted-foreground">{skill.skillCode}</p>

      <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
        {skill.macroCategoryName}
      </span>
    </div>
  );
});
