import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowClockwise, Database, MagnifyingGlass } from '@phosphor-icons/react';
import { Link } from 'react-router';
import { backendUrl } from '@/config/endpoints';
import { loadMasterTabs } from '@/lib/masterExcel';
import { getSessionToken } from '@/lib/session';

/**
 * Cognee, live: the memory service's status, every dataset with its document count, each dataset's documents and graph
 * inventory, a search over one RFQ's memory, and the jobs as they run. Jobs arrive on the daemon's event stream (memory:job),
 * and the numbers are re-read from Cognee after each job ends, so the page never shows a count it did not read.
 */

interface Job {
  jobId: string;
  rfqId: string;
  version: number;
  source: string;
  state: string;
  startedAt?: string;
  finishedAt?: string;
  items?: number;
  llm?: string;
}

interface Overview {
  status: { writesEnabled: boolean; provider: string; running: number; queued: number; recent: Job[] };
  datasets: Array<{ name: string; id: string; documents: number }>;
}

const authHeaders = (): Record<string, string> => {
  const token = getSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(backendUrl(`/api/admin/cognee${path}`), { ...init, headers: { ...authHeaders(), ...(init?.headers ?? {}) } });
  const body = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok) throw new Error(body.error ?? `request failed (${res.status})`);
  return body as T;
}

const STATE_STYLE: Record<string, string> = {
  running: 'bg-primary/10 text-primary',
  ok: 'bg-emerald-500/10 text-emerald-600',
  stale_version_rejected: 'bg-amber-500/10 text-amber-600',
  empty: 'bg-muted text-muted-foreground',
  error: 'bg-destructive/10 text-destructive',
};

// The company masters as shipped. The browser parses them; the memory service cannot see the workbooks itself.
const MASTERS = [
  { master: 'Organization Master', url: '/data/organization-master.xlsx' },
  { master: 'Project Master', url: '/data/project-master.xlsx' },
  { master: 'Quote Master', url: '/data/quote-master.xlsx' },
  { master: 'CAM Masters', url: '/data/cam-masters.xlsx' },
];

/** Sends every tab of the four masters to Cognee. Shows the shipped workbooks, not edits made in the editor this session. */
async function syncMasters(): Promise<{ sheets: number; rows: number }> {
  const sheets: Array<{ master: string; tab: string; columns: string[]; rows: string[][] }> = [];
  for (const m of MASTERS) {
    const tabs = await loadMasterTabs(m.url);
    for (const t of tabs) {
      sheets.push({ master: m.master, tab: t.label, columns: t.columns, rows: t.rows.map((r) => t.columns.map((c) => String(r[c] ?? ''))) });
    }
  }
  const rows = sheets.reduce((n, s) => n + s.rows.length, 0);
  await api('/sync-masters', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sheets }) });
  return { sheets: sheets.length, rows };
}

export function CogneePage() {
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [docs, setDocs] = useState<Array<{ name: string; mime: string; created: string }>>([]);
  const [inventory, setInventory] = useState<Array<Record<string, unknown>>>([]);
  const [question, setQuestion] = useState('');
  const [rfqId, setRfqId] = useState('');
  const [hits, setHits] = useState<{ matched: boolean; warning: string | null; chunks: Array<{ text: string; citation: { label: string } }> } | null>(null);
  const refreshTimer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api<Overview>('/overview');
      setOverview(next);
      setJobs((prev) => {
        const byId = new Map(prev.map((j) => [j.jobId, j]));
        for (const j of next.status.recent) byId.set(j.jobId, { ...byId.get(j.jobId), ...j });
        return [...byId.values()].sort((a, b) => (b.startedAt ?? '').localeCompare(a.startedAt ?? ''));
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cognee could not be read');
    }
  }, []);

  // The live feed: each job event lands at once; the numbers are re-read a moment after the last one.
  useEffect(() => {
    void refresh();
    const es = new EventSource(backendUrl('/events'));
    es.addEventListener('memory:job', (e) => {
      const job = JSON.parse((e as MessageEvent).data) as Job;
      setJobs((prev) => {
        const rest = prev.filter((j) => j.jobId !== job.jobId);
        return [{ ...prev.find((j) => j.jobId === job.jobId), ...job }, ...rest].slice(0, 200);
      });
      if (job.state !== 'running') {
        if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
        refreshTimer.current = window.setTimeout(() => void refresh(), 500);
      }
    });
    return () => {
      es.close();
      if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    };
  }, [refresh]);

  const open = async (name: string) => {
    setSelected(name);
    setHits(null);
    try {
      const [d, i] = await Promise.all([
        api<{ documents: Array<{ name: string; mime: string; created: string }> }>(`/datasets/${encodeURIComponent(name)}/documents`),
        api<{ inventory: Array<Record<string, unknown>> }>(`/datasets/${encodeURIComponent(name)}/inventory`),
      ]);
      setDocs(d.documents);
      setInventory(i.inventory);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'the dataset could not be read');
    }
  };

  const search = async () => {
    if (!rfqId.trim() || !question.trim()) return;
    try {
      setHits(await api('/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rfq_id: rfqId.trim(), question: question.trim() }) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'the search failed');
    }
  };

  const status = overview?.status;
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Cognee memory</h1>
          <p className="text-sm text-muted-foreground">What the assistant can recall, dataset by dataset, updated as each write runs.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={async () => {
              setSyncNote('Sending the masters…');
              try {
                const r = await syncMasters();
                setSyncNote(`Sent ${r.rows} rows from ${r.sheets} tabs. They appear in the live jobs as they are written.`);
              } catch (err) {
                setSyncNote(err instanceof Error ? err.message : 'the masters could not be sent');
              }
            }}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground"
          >
            Sync company masters
          </button>
          <Link to="/knowledge-graph" className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">
            Open the knowledge graph
          </Link>
          <button type="button" onClick={() => void refresh()} className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">
            <ArrowClockwise className="h-3.5 w-3.5" /> Refresh
          </button>
        </div>
      </header>
      {syncNote && <p className="text-xs text-muted-foreground">{syncNote}</p>}

      {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-foreground">{error}</p>}

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Cognee status">
        <Stat label="Writes" value={status ? (status.writesEnabled ? 'On' : 'Off') : '…'} />
        <Stat label="Datasets" value={overview ? String(overview.datasets.length) : '…'} />
        <Stat label="Documents" value={overview ? String(overview.datasets.reduce((n, d) => n + d.documents, 0)) : '…'} />
        <Stat label="Jobs running" value={status ? `${status.running} running, ${status.queued} queued` : '…'} />
      </section>

      <section className="rounded-xl border border-border bg-card" aria-label="Live jobs">
        <h2 className="border-b border-border px-4 py-3 text-sm font-semibold text-foreground">Live jobs</h2>
        {jobs.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-muted-foreground">No writes yet. Each ingest appears here as it starts and when it ends.</p>
        ) : (
          <ul className="max-h-72 divide-y divide-border overflow-y-auto text-xs">
            {jobs.map((j) => (
              <li key={j.jobId} className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-2">
                <span className={`rounded px-1.5 py-0.5 font-medium ${STATE_STYLE[j.state] ?? STATE_STYLE.running}`}>{j.state}</span>
                <span className="min-w-0 truncate text-foreground">{j.rfqId} · {j.source}{j.items !== undefined ? ` · ${j.items} documents` : ''}{j.llm ? ` · ${j.llm}` : ''}</span>
                <span className="tabular-nums text-muted-foreground">{(j.finishedAt ?? j.startedAt ?? '').slice(11, 19)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-[1fr_1.2fr]" aria-label="Datasets">
        <div className="rounded-xl border border-border bg-card">
          <h2 className="flex items-center gap-2 border-b border-border px-4 py-3 text-sm font-semibold text-foreground"><Database className="h-4 w-4" /> Datasets</h2>
          <ul className="divide-y divide-border text-sm">
            {(overview?.datasets ?? []).map((d) => (
              <li key={d.id}>
                <button type="button" onClick={() => void open(d.name)} aria-pressed={selected === d.name} className={`flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-muted/50 ${selected === d.name ? 'bg-muted/60' : ''}`}>
                  <span className="truncate text-foreground">{d.name}</span>
                  <span className="tabular-nums text-muted-foreground">{d.documents} docs</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="text-sm font-semibold text-foreground">{selected ?? 'Choose a dataset'}</h2>
            {selected && (
              <>
                <p className="mt-1 text-xs text-muted-foreground">{docs.length} documents · {inventory.length} graph node types</p>
                <ul className="mt-2 max-h-40 divide-y divide-border overflow-y-auto text-xs">
                  {docs.map((x) => <li key={x.name} className="py-1.5 font-mono text-muted-foreground">{x.name}</li>)}
                </ul>
                {inventory.length > 0 && (
                  <table className="mt-3 w-full text-xs">
                    <thead className="text-left text-muted-foreground"><tr><th className="py-1">Node type</th><th className="py-1 text-right">Count</th></tr></thead>
                    <tbody>
                      {inventory.map((row, i) => (
                        <tr key={i} className="border-t border-border">
                          <td className="py-1 text-foreground">{String(row.type ?? row.name ?? 'node')}</td>
                          <td className="py-1 text-right tabular-nums">{String(row.count ?? '')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}
          </div>

          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="text-sm font-semibold text-foreground">Search an RFQ&apos;s memory</h2>
            <div className="mt-2 flex flex-wrap gap-2">
              <input value={rfqId} onChange={(e) => setRfqId(e.target.value)} placeholder="RFQ id" aria-label="RFQ id" className="w-36 rounded-md border border-border bg-background px-2 py-1.5 text-xs" />
              <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void search()} placeholder="What do you want to recall?" aria-label="Question" className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs" />
              <button type="button" onClick={() => void search()} className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground"><MagnifyingGlass className="h-3.5 w-3.5" /> Search</button>
            </div>
            {hits && (
              <div className="mt-3 space-y-2 text-xs">
                {hits.warning && <p className="text-muted-foreground">{hits.warning === 'no_memory_yet' ? 'No memory yet for this RFQ.' : hits.warning}</p>}
                {hits.chunks.map((c, i) => (
                  <p key={i} className="rounded-md border border-border p-2 text-foreground"><span className="block text-muted-foreground">{c.citation.label}</span>{c.text}</p>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold text-foreground">{value}</p>
    </div>
  );
}
