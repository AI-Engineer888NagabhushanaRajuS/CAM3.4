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
  /** What is missing as buttons: pressing one sends `send`, and the next turn is read together with the earlier ones. */
  ask?: { prompt: string; options: Array<{ id: string; label: string; send: string }> };
}

const MAX_BUTTONS = 8;
const customerButtons = (cs: Array<{ customerId: string; customerName: string }>): NonNullable<PartyResult['ask']> => ({
  prompt: 'Which customer is this RFQ for?',
  options: cs.slice(0, MAX_BUTTONS).map((c) => ({ id: `customer:${c.customerId}`, label: c.customerName, send: `customer ${c.customerName}` })),
});
const projectButtons = (ps: Array<{ projectId: string; projectName: string }>): NonNullable<PartyResult['ask']> => ({
  prompt: 'Which project?',
  options: ps.slice(0, MAX_BUTTONS).map((p) => ({ id: `project:${p.projectId}`, label: p.projectName, send: `project ${p.projectName}` })),
});

export async function resolveParties(request: string, deps: ActionDeps): Promise<PartyResult> {
  const [customers, projects] = await Promise.all([deps.listCustomers(), deps.listProjects()]);
  const out: PartyResult = { missing: [] };
  const cHits = mentioned(request, customers, (c) => c.customerName);
  if (cHits.length > 1) {
    out.missing.push(`Which customer: ${list(cHits.map((c) => c.customerName))}?`);
    out.ask = customerButtons(cHits);
    return out;
  }
  const pool = cHits[0] ? projects.filter((p) => p.customerId === cHits[0].customerId) : projects;
  const pHits = mentioned(request, pool, (p) => p.projectName);
  if (pHits.length > 1) {
    out.missing.push(`Which project: ${list(pHits.map((p) => p.projectName))}?`);
    out.ask = projectButtons(pHits);
    return out;
  }
  const customer = cHits[0] ?? customers.find((c) => c.customerId === pHits[0]?.customerId);
  if (customer) {
    out.customer = { id: customer.customerId, name: customer.customerName };
  } else {
    out.missing.push(`Which customer? Known customers: ${list(customers.map((c) => c.customerName)) || 'none yet'}.`);
    out.ask = customerButtons(customers);
  }
  if (pHits[0]) {
    out.project = { id: pHits[0].projectId, name: pHits[0].projectName };
  } else if (customer) {
    const own = projects.filter((p) => p.customerId === customer.customerId);
    out.missing.push(`Which project of ${customer.customerName}? ${own.length ? `Known projects: ${list(own.map((p) => p.projectName))}.` : 'It has no projects yet; create one first.'}`);
    if (own.length) {
      out.ask = projectButtons(own);
    }
  }
  return out;
}

export interface FileResult {
  files: FileParam[];
  missing: string[];
  /** Set when a file was not released by both engines: nothing may proceed with it. */
  blocked: string[];
  /** One line on what was chosen and what was left out, shown with the confirmation card. */
  note: string;
}

/** What the bridge found inside a file, in the words the chat uses. */
const ROLE_TEXT: Record<string, string> = {
  scrub_bom: 'the BOM workbook',
  bom: 'a BOM without a SCRUB BOM sheet',
  volume: 'a volume file',
  quotewin: 'a QuoteWin export',
  document: 'a reference document',
  unknown: 'not a BOM, volume or QuoteWin layout',
};
const roleText = (role?: string): string => ROLE_TEXT[role ?? 'unknown'] ?? ROLE_TEXT.unknown;

/**
 * BOM and Volume must be released attachments (passed BOTH engines); a quarantined or held file is never in that list.
 * A pick can be a whole folder dump: only spreadsheets are looked at (what is INSIDE decides, not the name) and the other
 * files are left out, not refused.
 */
export async function resolveFiles(
  stagingId: string,
  refs: Array<{ attachmentId: string; name: string; rfqId?: string }>,
  deps: ActionDeps,
): Promise<FileResult> {
  const out: FileResult = { files: [], missing: [], blocked: [], note: '' };
  if (refs.length === 0) {
    out.missing.push('Attach the BOM workbook (.xlsx, .xls or .csv) first; it is scanned by both security engines before anything is created.');
    return out;
  }
  const released = new Map<string, Attachment[]>();
  const found: Array<{ ref: (typeof refs)[number]; scope: string; att: Attachment }> = [];
  const ignored: string[] = [];
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
      ignored.push(att.name);
    } else {
      found.push({ ref, scope, att });
    }
  }
  if (out.blocked.length > 0) {
    return out;
  }
  const left = ignored.length ? ` Left out as reference only: ${list(ignored)}.` : '';
  const looked = found.map((f) => `${f.att.name}: ${roleText(f.att.role)}`);
  // SPEC-022: what the bridge read INSIDE the released files wins over their names. The pipeline's first step reads only a
  // workbook with a SCRUB BOM sheet, so a plain BOM is refused here, with the reason, instead of failing a minute later.
  const byRole = (role: string) => found.filter((f) => f.att.role === role);
  const scrubs = byRole('scrub_bom');
  if (scrubs.length > 1) {
    out.missing.push(`Which of ${scrubs.map((f) => f.att.name).join(' and ')} is the BOM? Each has a SCRUB BOM sheet; only one can be used.`);
    return out;
  }
  if (scrubs.length === 0 && byRole('bom').length > 0) {
    out.missing.push(`${byRole('bom')[0].att.name} cannot be used: ${byRole('bom')[0].att.problems?.[0] ?? 'it has no SCRUB BOM sheet.'}`);
    return out;
  }
  if (scrubs.length === 1) {
    // /api/rfq/upload still requires a volume file; this step reads the volumes from the workbook's own Settings sheet, so a
    // separate Volume file is optional and the workbook itself stands in when there is none.
    const vol = byRole('volume');
    if (vol.length > 1) {
      out.missing.push(`Which of ${vol.map((f) => f.att.name).join(' and ')} is the Volume file?`);
      return out;
    }
    for (const [role, f] of [['BOM', scrubs[0]], ['VOLUME', vol[0] ?? scrubs[0]]] as const) {
      out.files.push({ role, name: f.att.name, attachmentId: f.att.attachmentId, sha256: f.att.sha256, sourceScope: f.scope });
    }
    const others = found.filter((f) => f !== scrubs[0] && f !== vol[0]).map((f) => f.att.name);
    out.note = `Using ${scrubs[0].att.name} as the BOM${vol[0] ? ` and ${vol[0].att.name} as the volume file` : ' (its Settings sheet carries the volumes)'}.${others.length ? ` Not used: ${list(others)}.` : ''}${left}`;
    return out;
  }
  // No role found a BOM. Two spreadsheets, one named like a volume file, is the old name rule (older bridge, unknown layouts).
  const isVolume = (n: string): boolean => /vol/i.test(n);
  const vols = found.filter((f) => isVolume(f.att.name));
  if (found.length === 2 && vols.length === 1 && found.every((f) => !f.att.role || f.att.role === 'unknown' || f.att.role === 'volume')) {
    const bom = found.find((f) => f !== vols[0]);
    for (const [role, f] of [['BOM', bom], ['VOLUME', vols[0]]] as const) {
      if (f) {
        out.files.push({ role, name: f.att.name, attachmentId: f.att.attachmentId, sha256: f.att.sha256, sourceScope: f.scope });
      }
    }
    out.note = `Using ${bom?.att.name} as the BOM and ${vols[0].att.name} as the volume file (chosen by name; I could not read a layout in them).${left}`;
    return out;
  }
  out.missing.push(found.length === 0
    ? `None of the ${refs.length} attached file${refs.length === 1 ? ' is a spreadsheet' : 's is a spreadsheet'}, so there is no BOM to start from. Attach the BOM workbook (a workbook with a sheet named SCRUB BOM).`
    : `I looked inside ${found.length === 1 ? 'the spreadsheet' : `the ${found.length} spreadsheets`}: ${looked.join('; ')}. None is the BOM workbook the pipeline starts from (a workbook with a sheet named SCRUB BOM). Attach it and say go again.${left}`);
  return out;
}
