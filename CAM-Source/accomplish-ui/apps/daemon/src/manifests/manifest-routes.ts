/**
 * SPEC-020 routes (all need a signed-in session; saving needs role admin):
 *   GET  /api/manifests               tree
 *   GET  /api/manifests/schema/:kind  JSON Schema (draft-07) for Monaco
 *   GET  /api/manifests/file?path=    one file + validation
 *   PUT  /api/manifests/file          { path, text, baseHash } -> saved file | 400 | 403 | 404 | 409 | 413
 */
import type http from 'node:http';
import { resolveManifestPath } from './manifest-paths.js';
import { manifestSchema, type SchemaKind } from './manifest-schemas.js';
import { listHistory, MAX_BYTES, readHistory, readManifest, saveManifest, type Reply } from './manifest-store.js';
import { buildTree } from './manifest-tree.js';
import { enabledBySkill } from './manifest-runtime.js';

export interface ManifestSession {
  email: string;
  role: string;
}

const KINDS = new Set<string>(['agent', 'skill', 'reporting', 'approved']);
/** JSON escaping can make the body a bit larger than the text it carries; the text itself is capped at MAX_BYTES. */
const MAX_BODY = MAX_BYTES * 3;

function send(res: http.ServerResponse, { code, body }: Reply): void {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

/** Collect the body in chunks; past the cap it keeps draining but stops storing, so a huge upload cannot fill memory. */
function readBody(req: http.IncomingMessage): Promise<{ text: string; tooBig: boolean }> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let tooBig = false;
    req.on('data', (c: Buffer) => {
      size += c.length;
      if (size > MAX_BODY) {
        tooBig = true;
        chunks.length = 0;
      } else if (!tooBig) {
        chunks.push(c);
      }
    });
    req.on('end', () => resolve({ text: Buffer.concat(chunks).toString('utf8'), tooBig }));
    req.on('error', reject);
  });
}

/** SPEC-025: switches the pipeline tools of one skill on or off; returns the tool names it touched. */
export type SkillRuntime = (skillId: string, enabled: boolean) => Promise<string[]>;

async function put(req: http.IncomingMessage, session: ManifestSession, runtime?: SkillRuntime): Promise<Reply> {
  const { text, tooBig } = await readBody(req);
  if (tooBig) {
    return { code: 413, body: { error: `Request is larger than ${MAX_BYTES / 1024} KB` } };
  }
  let parsed: { path?: unknown; text?: unknown; baseHash?: unknown };
  try {
    parsed = JSON.parse(text);
  } catch {
    return { code: 400, body: { error: 'Request body must be JSON { path, text, baseHash }' } };
  }
  const p = resolveManifestPath(parsed?.path);
  if (!p || p.readOnly) {
    return { code: 403, body: { error: p ? 'Runtime manifests are read-only here: change them with scripts/import_manifest.py' : 'Path not allowed' } };
  }
  if (typeof parsed.text !== 'string' || typeof parsed.baseHash !== 'string') {
    return { code: 400, body: { error: 'text and baseHash must be strings' } };
  }
  const before = enabledBySkill();
  const saved = saveManifest(p, parsed.text, parsed.baseHash, session.email);
  if (saved.code !== 200 || !runtime) {
    return saved;
  }
  // The file is saved; now make the pipeline follow every skill whose flag this save changed. A database error is reported, not hidden.
  const applied: Record<string, string[]> = {};
  const errors: string[] = [];
  for (const [id, on] of enabledBySkill()) {
    if (before.has(id) && before.get(id) !== on) {
      try {
        applied[id] = await runtime(id, on);
      } catch (e) {
        errors.push(`${id}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  }
  return { code: 200, body: { ...(saved.body as object), runtime: { applied, errors } } };
}

/** True when the URL belongs to this module (the caller then stops). Never throws and never awaits in the caller. */
export function handleManifestRoute(req: http.IncomingMessage, res: http.ServerResponse, session: ManifestSession | null, runtime?: SkillRuntime): boolean {
  const url = new URL(req.url ?? '/', 'http://localhost');
  const path = url.pathname;
  if (path !== '/api/manifests' && !path.startsWith('/api/manifests/')) {
    return false;
  }
  void (async () => {
    try {
      if (!session) {
        send(res, { code: 401, body: { error: 'Not signed in' } });
        return;
      }
      const method = req.method;
      if (method === 'GET' && path === '/api/manifests') {
        send(res, { code: 200, body: { tree: buildTree() } });
      } else if (method === 'GET' && path.startsWith('/api/manifests/schema/')) {
        const kind = path.slice('/api/manifests/schema/'.length);
        send(res, KINDS.has(kind) ? { code: 200, body: manifestSchema(kind as SchemaKind) } : { code: 404, body: { error: 'Unknown kind (agent | skill | reporting | approved)' } });
      } else if (method === 'GET' && path === '/api/manifests/file') {
        const p = resolveManifestPath(url.searchParams.get('path'));
        const view = p ? readManifest(p) : null;
        if (!p) {
          send(res, { code: 403, body: { error: 'Path not allowed' } });
        } else {
          send(res, view ? { code: 200, body: view } : { code: 404, body: { error: 'No such manifest' } });
        }
      } else if (method === 'GET' && (path === '/api/manifests/history' || path === '/api/manifests/history/file')) {
        const p = resolveManifestPath(url.searchParams.get('path'));
        if (!p) {
          send(res, { code: 403, body: { error: 'Path not allowed' } });
        } else if (path === '/api/manifests/history') {
          send(res, { code: 200, body: { path: p.rel, versions: listHistory(p) } });
        } else {
          const v = readHistory(p, url.searchParams.get('stamp'));
          send(res, v ? { code: 200, body: v } : { code: 404, body: { error: 'No such saved version' } });
        }
      } else if (method === 'PUT' && path === '/api/manifests/file') {
        // Role is on the session (admin | user | fde); same rule as the user-admin routes. Not-admin gets 403 before any body is read.
        if (session.role !== 'admin') {
          req.resume();
          send(res, { code: 403, body: { error: 'Forbidden: admin role required to save manifests' } });
          return;
        }
        send(res, await put(req, session, runtime));
      } else {
        send(res, { code: 404, body: { error: 'Not found' } });
      }
    } catch (e) {
      if (!res.headersSent) {
        send(res, { code: 500, body: { error: `Manifest service error: ${e instanceof Error ? e.message : String(e)}` } });
      }
    }
  })();
  return true;
}
