import type { ManifestTree } from '@/lib/manifestsApi';

export interface TreeNode {
  key: string;
  label: string;
  /** Secondary text, e.g. "3 steps" or "port 8088". */
  detail?: string;
  status?: string;
  version?: string;
  /** Selectable file; absent for groups, sub-skills and missing files. */
  path?: string;
  kind: 'group' | 'file' | 'sub' | 'note';
  children?: TreeNode[];
}

export interface Row { node: TreeNode; level: number; parentKey: string | null }

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

export function buildNodes(tree: ManifestTree): TreeNode[] {
  const { agent, reporting, approved, runtime } = tree;
  const agentNode: TreeNode = agent
    ? {
      key: `file:${agent.path}`, kind: 'file', path: agent.path, label: agent.name || 'Agent manifest', status: agent.status, version: agent.version,
      detail: plural(agent.skills.length, 'skill'),
      children: [...agent.skills].sort((a, b) => a.sequence - b.sequence).map((s) => ({
        key: `file:${s.path}`, kind: 'file' as const, path: s.missing ? undefined : s.path,
        label: `${s.sequence}. ${s.name}`, status: s.status, version: s.version, detail: s.missing ? 'file missing' : plural(s.subSkills.length, 'sub-skill'),
        children: s.subSkills.map((u) => ({ key: `sub:${s.path}:${u.id}`, kind: 'sub' as const, label: u.name, detail: `${u.type}, ${plural(u.stepCount, 'step')}` })),
      })),
    }
    : { key: 'note:agent', kind: 'note', label: 'No agent manifest found' };
  const reportingNode: TreeNode = reporting
    ? { key: `file:${reporting.path}`, kind: 'file', path: reporting.path, label: reporting.name || 'Reporting manifest', status: reporting.status, version: reporting.version, detail: plural(reporting.reportCount, 'report') }
    : { key: 'note:reporting', kind: 'note', label: 'No reporting manifest found' };
  return [
    agentNode,
    reportingNode,
    {
      key: 'group:approved', kind: 'group', label: 'As-built (approved)', detail: String(approved.length),
      children: approved.map((a) => ({ key: `file:${a.path}`, kind: 'file' as const, path: a.path, label: a.name || a.id, version: a.version, status: 'approved', detail: a.active ? 'active' : undefined })),
    },
    {
      key: 'group:runtime', kind: 'group', label: 'Live routing manifests (read-only)', detail: String(runtime.length),
      children: runtime.map((r) => ({ key: `file:${r.path}`, kind: 'file' as const, path: r.path, label: r.name || r.id, version: r.version, detail: r.port ? `port ${r.port}` : undefined })),
    },
  ];
}

/** Depth-first list of the rows that are currently visible. */
export function flatten(nodes: TreeNode[], expanded: ReadonlySet<string>): Row[] {
  const out: Row[] = [];
  const walk = (list: TreeNode[], level: number, parentKey: string | null) => {
    for (const node of list) {
      out.push({ node, level, parentKey });
      if (node.children?.length && expanded.has(node.key)) walk(node.children, level + 1, node.key);
    }
  };
  walk(nodes, 1, null);
  return out;
}
