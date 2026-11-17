import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import { ArrowClockwise } from '@phosphor-icons/react';
import { backendUrl } from '@/config/endpoints';
import { getSessionToken } from '@/lib/session';

/**
 * The Centum Knowledge Graph: your company's knowledge graph, built over time from the RFQ results and the masters, to improve
 * the app and for future integrations. The nodes and relations are read from Cognee's own graph engine, laid out left to right,
 * and re-read after each memory job finishes (the same memory:job stream the Cognee page uses).
 */

interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties: Record<string, string | number | boolean | null>;
}
interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}
interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  counts: Record<string, number>;
  total: { nodes: number; edges: number };
}

const TYPE_COLOUR: Record<string, string> = {
  Entity: '#22a8c9',
  EntityType: '#3300aa',
  NodeSet: '#8b5cf6',
  TextSummary: '#10b981',
  DocumentChunk: '#94a3b8',
  TextDocument: '#f59e0b',
};
const colourOf = (type: string) => TYPE_COLOUR[type] ?? '#64748b';

const NODE_W = 190;
const NODE_H = 46;

function laidOut(graph: GraphResponse): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 22, ranksep: 120, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of graph.nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of graph.edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  const nodes: Node[] = graph.nodes.map((n) => {
    const p = g.node(n.id) as { x: number; y: number };
    return {
      id: n.id,
      position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 },
      data: { label: n.label, type: n.type },
      style: {
        width: NODE_W,
        borderRadius: 10,
        border: `2px solid ${colourOf(n.type)}`,
        background: 'var(--card, #fff)',
        color: 'var(--foreground, #111)',
        fontSize: 12,
        padding: '6px 8px',
      },
    };
  });
  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `${e.source}-${e.relation}-${e.target}-${i}`,
    source: e.source,
    target: e.target,
    label: e.relation,
    labelStyle: { fontSize: 10, fill: '#64748b' },
    style: { stroke: '#94a3b8' },
  }));
  return { nodes, edges };
}

async function readGraph(limit: number): Promise<GraphResponse> {
  const token = getSessionToken();
  const res = await fetch(backendUrl(`/api/admin/cognee/graph?limit=${limit}`), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  const body = (await res.json().catch(() => ({}))) as GraphResponse & { error?: string };
  if (!res.ok) throw new Error(body.error ?? `the graph could not be read (${res.status})`);
  return body;
}

export function CentumGraphPage() {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(150);
  const [picked, setPicked] = useState<GraphNode | null>(null);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      setGraph(await readGraph(limit));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'the graph could not be read');
    }
  }, [limit]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Realtime: a finished memory job means the graph may have new entities, so it is re-read a moment after.
  useEffect(() => {
    const es = new EventSource(backendUrl('/events'));
    es.addEventListener('memory:job', (e) => {
      const job = JSON.parse((e as MessageEvent).data) as { state?: string };
      if (job.state && job.state !== 'running') {
        if (timer.current) window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => void refresh(), 800);
      }
    });
    return () => {
      es.close();
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [refresh]);

  const flow = useMemo(() => (graph ? laidOut(graph) : { nodes: [], edges: [] }), [graph]);
  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setPicked(graph?.nodes.find((n) => n.id === node.id) ?? null);
  }, [graph]);
  const related = useMemo(() => {
    if (!graph || !picked) return [];
    const names = new Map(graph.nodes.map((n) => [n.id, n.label]));
    return graph.edges
      .filter((e) => e.source === picked.id || e.target === picked.id)
      .slice(0, 40)
      .map((e) => (e.source === picked.id ? { out: true, relation: e.relation, other: names.get(e.target) ?? e.target } : { out: false, relation: e.relation, other: names.get(e.source) ?? e.source }));
  }, [graph, picked]);

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-xl font-semibold text-foreground">Centum Knowledge Graph</h1>
          <p className="text-sm text-muted-foreground">
            Your company&apos;s knowledge graph, built over time from RFQ results and the masters, to improve the app and for future integrations.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <label className="flex items-center gap-1.5">
            Show
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="rounded-md border border-border bg-card px-1.5 py-1 text-xs text-foreground">
              {[60, 150, 400, 800].map((n) => <option key={n} value={n}>{n} most connected</option>)}
            </select>
          </label>
          <button type="button" onClick={() => void refresh()} className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 hover:text-foreground">
            <ArrowClockwise className="h-3.5 w-3.5" /> Refresh
          </button>
        </div>
      </header>

      {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">{error}</p>}

      <div className="grid min-h-[560px] flex-1 gap-4 lg:grid-cols-[1fr_300px]">
        <div className="relative min-h-[560px] overflow-hidden rounded-xl border border-border bg-card" aria-label="Knowledge graph canvas" role="img">
          {graph && graph.nodes.length === 0 ? (
            <p className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
              No entities yet. They appear here once an RFQ or the masters have been written to Cognee and the graph has been built.
            </p>
          ) : (
            <ReactFlow nodes={flow.nodes} edges={flow.edges} onNodeClick={onNodeClick} fitView minZoom={0.05} colorMode="light">
              <MiniMap pannable zoomable />
              <Controls />
              <Background />
            </ReactFlow>
          )}
        </div>

        <aside className="space-y-4 overflow-y-auto rounded-xl border border-border bg-card p-4 text-xs">
          <section aria-label="Legend">
            <h2 className="text-sm font-semibold text-foreground">Nodes</h2>
            {graph && (
              <p className="mt-1 text-muted-foreground">
                Showing {graph.nodes.length} of {graph.total.nodes} graph nodes, {graph.edges.length} relations.
              </p>
            )}
            <ul className="mt-2 space-y-1">
              {Object.entries(graph?.counts ?? {}).map(([type, n]) => (
                <li key={type} className="flex items-center justify-between">
                  <span className="flex items-center gap-2"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: colourOf(type) }} />{type}</span>
                  <span className="tabular-nums text-muted-foreground">{n}</span>
                </li>
              ))}
            </ul>
          </section>

          <section aria-label="Selected node" className="border-t border-border pt-4">
            {!picked ? (
              <p className="text-muted-foreground">Click a node to see what it is and what it connects to.</p>
            ) : (
              <>
                <h2 className="text-sm font-semibold text-foreground">{picked.label}</h2>
                <p className="text-muted-foreground">{picked.type}</p>
                <dl className="mt-2 space-y-1">
                  {Object.entries(picked.properties).filter(([k]) => !['id', 'source_task', 'source_user', 'ontology_uri'].includes(k)).slice(0, 12).map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[90px_1fr] gap-2">
                      <dt className="text-muted-foreground">{k}</dt>
                      <dd className="break-all text-foreground">{v === null ? '' : String(v)}</dd>
                    </div>
                  ))}
                </dl>
                <h3 className="mt-3 font-semibold text-foreground">Connected to</h3>
                <ul className="mt-1 space-y-1">
                  {related.map((r, i) => (
                    <li key={i} className="text-muted-foreground">
                      {r.out ? '→' : '←'} <span className="text-foreground">{r.relation}</span> {r.other}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
