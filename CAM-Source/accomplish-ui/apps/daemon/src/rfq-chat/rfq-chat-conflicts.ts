/**
 * Conflicts between evidence rows: the same part number carrying different values for the same field, in different RFQs
 * or in two rows of the same sheet. Pure string work on the rows the bridge returned ("CBOM, row 5: Part Number=X; MOQ=5000"),
 * so a conflict is always shown with the exact cells on both sides.
 * ponytail: rows are parsed by their "key=value; key=value" shape; a sheet written another way is not compared (no conflict
 * is reported for it), never a false one. Upgrade path: have the bridge return the cells as structured fields.
 */
import type { MessageCitation } from '@accomplish_ai/agent-core';

export interface EvidenceRow {
  rfqId: string;
  text: string;
  citation: MessageCitation;
}

export interface Conflict {
  part: string;
  field: string;
  sides: Array<{ rfqId: string; value: string; citation: MessageCitation }>;
}

// A running number says which row it is, not what the part is: it differs by design.
const POSITION_FIELD = /^(s\.?\s?no\.?|sr\.?(\s?no\.?)?|item(\s?no\.?)?|line|row|index|#)$/i;

export function parseRow(text: string): { sheet: string; fields: Map<string, string> } {
  const at = text.indexOf(': ');
  const head = at >= 0 ? text.slice(0, at) : '';
  const fields = new Map<string, string>();
  for (const pair of (at >= 0 ? text.slice(at + 2) : text).split(/;\s+/)) {
    const eq = pair.indexOf('=');
    if (eq > 0) {
      fields.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
    }
  }
  return { sheet: head.replace(/,\s*row\s+\d+.*$/i, '').trim(), fields };
}

export function findConflicts(rows: EvidenceRow[], parts: string[]): Conflict[] {
  const out: Conflict[] = [];
  for (const part of parts) {
    const hits = rows.filter((r) => r.text.toLowerCase().includes(part.toLowerCase())).map((r) => ({ r, ...parseRow(r.text) }));
    for (const sheet of new Set(hits.map((h) => h.sheet))) {
      const same = hits.filter((h) => h.sheet === sheet);
      const keys = new Set(same.flatMap((h) => [...h.fields.keys()]));
      for (const field of keys) {
        if (POSITION_FIELD.test(field)) {
          continue;
        }
        const sides = new Map<string, Conflict['sides'][number]>();
        for (const h of same) {
          const value = h.fields.get(field);
          if (value !== undefined && !sides.has(value)) {
            sides.set(value, { rfqId: h.r.rfqId, value, citation: h.r.citation });
          }
        }
        if (sides.size > 1) {
          out.push({ part, field, sides: [...sides.values()] });
        }
      }
    }
  }
  return out;
}
