import { findNodeAtLocation, parseTree, type Node, type Segment } from 'jsonc-parser';

/** "/skills/0/id", "$.skills[0].id" or "skills.0.id" -> ['skills', '0', 'id'] */
export function splitJsonPath(path: string): string[] {
  const p = path.trim().replace(/^(#|\$)/, '');
  if (p.startsWith('/')) return p.slice(1).split('/').map((s) => s.replace(/~1/g, '/').replace(/~0/g, '~')).filter(Boolean);
  return p.replace(/\[(\d+)\]/g, '.$1').split('.').filter(Boolean);
}

/** Resolve the segments against a parsed tree; array parents take numeric segments. */
function resolve(root: Node, parts: string[]): Node | undefined {
  let node = root;
  for (const part of parts) {
    const seg: Segment = node.type === 'array' && /^\d+$/.test(part) ? Number(part) : part;
    const next = findNodeAtLocation(node, [seg]);
    if (!next) return undefined;
    node = next;
  }
  return node;
}

/** Offset of the value a validation path points at; falls back to the nearest existing ancestor, then 0. */
export function offsetForPath(text: string, path: string): number {
  const root = parseTree(text);
  if (!root) return 0;
  const parts = splitJsonPath(path);
  for (let n = parts.length; n >= 0; n--) {
    const node = resolve(root, parts.slice(0, n));
    if (node) return node.offset;
  }
  return 0;
}

/** 1-based line and column of an offset (what Monaco positions use). */
export function positionAt(text: string, offset: number): { line: number; column: number } {
  const before = text.slice(0, offset);
  const line = before.split('\n').length;
  return { line, column: offset - (before.lastIndexOf('\n') + 1) + 1 };
}
