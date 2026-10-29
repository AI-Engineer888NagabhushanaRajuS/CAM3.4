import { memo, useState, useCallback } from 'react';
import { DotsThreeVertical } from '@phosphor-icons/react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

interface CustomerProjectCardProps {
  id: string;
  name: string;
  selected?: boolean;
  onClick?: () => void;
  onRename: (id: string, name: string) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
}

/** Shared row card for both Customers and Projects in the Project Tracking
 * settings tab -- same shape as SkillCard.tsx's rename/delete menu pattern,
 * simplified (no toggle, no source badges -- master data has neither). */
export const CustomerProjectCard = memo(function CustomerProjectCard({
  id,
  name,
  selected,
  onClick,
  onRename,
  onDelete,
}: CustomerProjectCardProps) {
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState(name);
  const [busy, setBusy] = useState(false);

  const startEdit = useCallback(() => {
    setDraftName(name);
    setEditing(true);
  }, [name]);

  const commitEdit = useCallback(async () => {
    const trimmed = draftName.trim();
    if (!trimmed || trimmed === name) { setEditing(false); return; }
    setBusy(true);
    const ok = await onRename(id, trimmed);
    setBusy(false);
    if (ok) { setEditing(false); }
  }, [draftName, name, id, onRename]);

  const handleDelete = useCallback(async () => {
    setBusy(true);
    await onDelete(id);
    setBusy(false);
  }, [id, onDelete]);

  if (editing) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-primary/40 bg-card px-3 py-2">
        <input
          autoFocus
          value={draftName}
          onChange={(e) => setDraftName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { void commitEdit(); }
            if (e.key === 'Escape') { setEditing(false); }
          }}
          disabled={busy}
          className="min-w-0 flex-1 bg-transparent text-[13px] text-foreground outline-none"
        />
        <button
          type="button"
          onClick={() => { void commitEdit(); }}
          disabled={busy}
          className="text-[11px] font-medium text-primary hover:underline disabled:opacity-50"
        >
          Save
        </button>
        <button type="button" onClick={() => setEditing(false)} className="text-[11px] text-muted-foreground hover:underline">
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div
      onClick={onClick}
      className={`group flex items-center justify-between gap-2 rounded-lg border px-3 py-2 transition-colors ${
        selected ? 'border-primary bg-primary/10' : 'border-border bg-card hover:border-primary/40'
      } ${onClick ? 'cursor-pointer' : ''}`}
    >
      <span className="truncate text-[13px] text-foreground">{name}</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            onClick={(e) => e.stopPropagation()}
            className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-colors group-hover:opacity-100 hover:bg-muted hover:text-foreground"
            aria-label="Options"
          >
            <DotsThreeVertical weight="bold" className="h-4 w-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={startEdit}>Rename</DropdownMenuItem>
          <DropdownMenuItem onClick={() => { void handleDelete(); }} variant="destructive">
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
});
