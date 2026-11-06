import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { CaretDown, CaretRight, FileText, FolderSimple, LockSimple, ListBullets, Warning } from '@phosphor-icons/react';
import { cn } from '@/lib/utils';
import type { ManifestTree as Tree } from '@/lib/manifestsApi';
import { StatusBadge } from './StatusBadge';
import { buildNodes, flatten, type Row } from './treeModel';

interface Props { tree: Tree; selectedPath: string | null; onSelect: (path: string) => void }

/** WAI-ARIA tree: roving tabindex, Up/Down move, Right/Left expand/collapse, Enter selects (or toggles a group). */
export function ManifestTree({ tree, selectedPath, onSelect }: Props) {
  const nodes = useMemo(() => buildNodes(tree), [tree]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(nodes[0]?.children?.length ? [nodes[0].key] : []));
  const rows = useMemo(() => flatten(nodes, expanded), [nodes, expanded]);
  const selectedKey = selectedPath ? `file:${selectedPath}` : null;
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const refs = useRef(new Map<string, HTMLDivElement>());
  const activeKey = rows.some((r) => r.node.key === focusKey) ? focusKey : rows.some((r) => r.node.key === selectedKey) ? selectedKey : rows[0]?.node.key;

  const toggle = (key: string, open?: boolean) => setExpanded((prev) => {
    const next = new Set(prev);
    if (open ?? !next.has(key)) next.add(key); else next.delete(key);
    return next;
  });
  const focusRow = (key: string | undefined) => {
    if (!key) return;
    setFocusKey(key);
    refs.current.get(key)?.focus();
  };
  const activate = (row: Row) => {
    if (row.node.path) onSelect(row.node.path);
    if (row.node.kind === 'group') toggle(row.node.key);
  };

  const onKeyDown = (e: KeyboardEvent, i: number) => {
    const row = rows[i];
    const hasKids = !!row.node.children?.length;
    const open = expanded.has(row.node.key);
    const keys: Record<string, () => void> = {
      ArrowDown: () => focusRow(rows[i + 1]?.node.key),
      ArrowUp: () => focusRow(rows[i - 1]?.node.key),
      Home: () => focusRow(rows[0]?.node.key),
      End: () => focusRow(rows[rows.length - 1]?.node.key),
      ArrowRight: () => (hasKids && !open ? toggle(row.node.key, true) : hasKids ? focusRow(rows[i + 1]?.node.key) : undefined),
      ArrowLeft: () => (hasKids && open ? toggle(row.node.key, false) : focusRow(row.parentKey ?? undefined)),
      Enter: () => activate(row),
      ' ': () => activate(row),
    };
    if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
  };

  return (
    <div role="tree" aria-label="Manifests: agent, skills, sub-skills, reporting, as-built and live routing" className="flex flex-col py-1 text-sm">
      {rows.map((row, i) => {
        const { node, level } = row;
        const hasKids = !!node.children?.length;
        const open = expanded.has(node.key);
        const selected = node.key === selectedKey;
        const Icon = node.kind === 'group' ? FolderSimple : node.kind === 'sub' ? ListBullets : node.kind === 'note' ? Warning : FileText;
        return (
          <div
            key={node.key}
            ref={(el) => { if (el) refs.current.set(node.key, el); else refs.current.delete(node.key); }}
            role="treeitem"
            aria-level={level}
            aria-selected={node.path ? selected : undefined}
            aria-expanded={hasKids ? open : undefined}
            tabIndex={node.key === activeKey ? 0 : -1}
            onFocus={() => setFocusKey(node.key)}
            onKeyDown={(e) => onKeyDown(e, i)}
            onClick={() => activate(row)}
            style={{ paddingLeft: 8 + (level - 1) * 16 }}
            className={cn(
              'flex min-h-7 cursor-default items-center border-l-[3px] border-transparent gap-1.5 rounded-md py-1 pr-2 outline-none focus-visible:ring-2 focus-visible:ring-ring',
              node.path || node.kind === 'group' ? 'cursor-pointer hover:bg-accent' : 'text-muted-foreground',
              selected && 'border-primary bg-primary/10 font-semibold text-foreground',
            )}
          >
            {hasKids ? (
              <span
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded hover:bg-muted"
                onClick={(e) => { e.stopPropagation(); toggle(node.key); }}
                aria-hidden="true"
              >
                {open ? <CaretDown className="h-3 w-3" weight="bold" /> : <CaretRight className="h-3 w-3" weight="bold" />}
              </span>
            ) : <span className="w-5 shrink-0" aria-hidden="true" />}
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate" title={node.label}>{node.label}</span>
            {node.detail && <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline">{node.detail}</span>}
            {node.version && <span className="hidden shrink-0 font-mono text-[11px] text-muted-foreground sm:inline">v{node.version}</span>}
            {node.status && <StatusBadge status={node.status} />}
            {node.kind === 'file' && !node.status && node.path && (
              <LockSimple className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="read-only" />
            )}
          </div>
        );
      })}
    </div>
  );
}
