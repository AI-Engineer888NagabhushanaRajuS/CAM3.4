/**
 * Works out what the user asked for in a "create an RFQ" request, deterministically: customer and project are matched by
 * name against the real lists, files by the released-attachment list. Anything missing or unclear comes back as a plain
 * line the assistant can relay and ask about. Nothing is guessed: the confirmation card shows every value anyway.
 */
import type { ActionDeps, Attachment, FileParam } from './rfq-chat-actions-types.js';

const SAFE_SCOPE = /^[A-Za-z0-9_-]{1,64}$/;
const BOM_EXT = /\.(xlsx|xls|csv)$/i;
const norm = (s: string): string => ` ${s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()} `;
const list = (names: string[]): string => names.slice(0, 15).join(', ') + (names.length > 15 ? `, and ${names.length - 15} more` : '');

/** Items whose name appears in the text as whole words; a name inside a longer matching name does not count. */
function mentioned<T>(text: string, items: T[], name: (t: T) => string): T[] {
  const hay = norm(text);
  const hits = items.filter((i) => name(i).trim() !== '' && hay.includes(norm(name(i))));
  return hits.filter((a) => !hits.some((b) => b !== a && norm(name(b)).includes(norm(name(a))) && norm(name(b)) !== norm(name(a))));
}

export interface PartyResult {
  customer?: { id: string; name: string };
  project?: { id: string; name: string };
  missing: string[];
}

export async function resolveParties(request: string, deps: ActionDeps): Promise<PartyResult> {
  const [customers, projects] = await Promise.all([deps.listCustomers(), deps.listProjects()]);
  const out: PartyResult = { missing: [] };
  const cHits = mentioned(request, customers, (c) => c.customerName);
  if (cHits.length > 1) {
    out.missing.push(`Which customer: ${list(cHits.map((c) => c.customerName))}?`);
    return out;
  }
  const pool = cHits[0] ? projects.filter((p) => p.customerId === cHits[0].customerId) : projects;
  const pHits = mentioned(request, pool, (p) => p.projectName);
  if (pHits.length > 1) {
    out.missing.push(`Which project: ${list(pHits.map((p) => p.projectName))}?`);
    return out;
  }
  const customer = cHits[0] ?? customers.find((c) => c.customerId === pHits[0]?.customerId);
  if (customer) {
    out.customer = { id: customer.customerId, name: customer.customerName };
  } else {
    out.missing.push(`Which customer? Known customers: ${list(customers.map((c) => c.customerName)) || 'none yet'}.`);
  }
  if (pHits[0]) {
    out.project = { id: pHits[0].projectId, name: pHits[0].projectName };
  } else if (customer) {
    const names = projects.filter((p) => p.customerId === customer.customerId).map((p) => p.projectName);
    out.missing.push(`Which project of ${customer.customerName}? ${names.length ? `Known projects: ${list(names)}.` : 'It has no projects yet; create one first.'}`);
  }
  return out;
}

export interface FileResult {
  files: FileParam[];
  missing: string[];
  /** Set when a file was not released by both engines: nothing may proceed with it. */
  blocked: string[];
}

/** BOM and Volume must be released attachments (passed BOTH engines); a quarantined or held file is never in that list. */
export async function resolveFiles(
  stagingId: string,
  refs: Array<{ attachmentId: string; name: string; rfqId?: string }>,
  deps: ActionDeps,
): Promise<FileResult> {
  const out: FileResult = { files: [], missing: [], blocked: [] };
  if (refs.length === 0) {
    out.missing.push('Attach the BOM file and the Volume file (.xlsx, .xls or .csv) first; they are scanned by both security engines before anything is created.');
    return out;
  }
  const released = new Map<string, Attachment[]>();
  const found: Array<{ ref: (typeof refs)[number]; scope: string; att: Attachment }> = [];
  for (const ref of refs) {
    const scope = ref.rfqId ?? stagingId;
    if (!SAFE_SCOPE.test(scope)) {
      out.blocked.push(`${ref.name}: invalid attachment scope.`);
      continue;
    }
    if (!released.has(scope)) {
      released.set(scope, await deps.listAttachments(scope));
    }
    const att = released.get(scope)?.find((a) => a.attachmentId === ref.attachmentId);
    if (!att) {
      out.blocked.push(`${ref.name} is not a released attachment (it did not pass both security engines, or it was removed), so I cannot use it.`);
    } else if (!BOM_EXT.test(att.name)) {
      out.blocked.push(`${att.name} is not .xlsx, .xls or .csv.`);
    } else {
      found.push({ ref, scope, att });
    }
  }
  if (out.blocked.length > 0) {
    return out;
  }
  const isVolume = (n: string): boolean => /vol/i.test(n);
  if (found.length === 1) {
    out.missing.push(isVolume(found[0].att.name)
      ? `I have the Volume file (${found[0].att.name}); attach the BOM file too.`
      : `I have ${found[0].att.name}; attach the Volume file too (the pipeline needs both).`);
    return out;
  }
  const vols = found.filter((f) => isVolume(f.att.name));
  if (found.length !== 2 || vols.length !== 1) {
    out.missing.push(`Which attached file is the BOM and which is the Volume file? Include "bom" or "volume" in the file names (only these two files are used; I got ${found.length}).`);
    return out;
  }
  const bom = found.find((f) => f !== vols[0]);
  for (const [role, f] of [['BOM', bom], ['VOLUME', vols[0]]] as const) {
    if (f) {
      out.files.push({ role, name: f.att.name, attachmentId: f.att.attachmentId, sha256: f.att.sha256, sourceScope: f.scope });
    }
  }
  return out;
}
