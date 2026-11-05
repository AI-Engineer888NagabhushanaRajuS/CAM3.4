/**
 * SPEC-020: the values the assistant may change and how a sentence is read as an edit. The nine fields are the allow-list
 * of the bridge route PUT /api/bom/batch-update/{rfq_id} (duck_db_api.py EDITABLE_FIELDS); the bridge enforces it again.
 * Deterministic: no model reads the sentence. Synonyms are exact phrases, never fuzzy matches.
 */
export interface EditField {
  name: string;
  label: string;
  kind: 'price' | 'quantity' | 'days' | 'currency' | 'text';
  synonyms: string[];
}

export const EDIT_FIELDS: EditField[] = [
  { name: 'final_price_conv', label: 'Unit price (converted)', kind: 'price', synonyms: ['price', 'unit price', 'converted price', 'converted unit price', 'price conv', 'price converted', 'unit price converted'] },
  { name: 'final_price_original', label: 'Unit price (original currency)', kind: 'price', synonyms: ['original price', 'price original', 'unit price original', 'original unit price', 'price in original currency'] },
  { name: 'final_currency_original', label: 'Original currency', kind: 'currency', synonyms: ['currency', 'original currency', 'currency original'] },
  { name: 'final_mfg_name', label: 'Manufacturer', kind: 'text', synonyms: ['manufacturer', 'manufacturer name', 'mfg', 'mfg name', 'mfr', 'mfr name'] },
  { name: 'final_unit_of_measure', label: 'Unit of measure', kind: 'text', synonyms: ['uom', 'unit of measure', 'unit of measurement'] },
  { name: 'final_supp_name', label: 'Supplier', kind: 'text', synonyms: ['supplier', 'supplier name', 'supp name', 'vendor', 'vendor name', 'distributor'] },
  { name: 'final_pkg_qty', label: 'Package quantity', kind: 'quantity', synonyms: ['package quantity', 'package qty', 'pkg qty', 'pkg quantity', 'pack qty', 'pack quantity', 'packaging quantity', 'spq'] },
  { name: 'final_moq', label: 'MOQ', kind: 'quantity', synonyms: ['moq', 'minimum order quantity', 'min order quantity', 'min order qty', 'minimum order qty'] },
  { name: 'final_lead_time', label: 'Lead time (days)', kind: 'days', synonyms: ['lead time', 'leadtime', 'lead time days', 'lead days'] },
];

const norm = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

export function resolveField(text: string): EditField | null {
  const t = norm(text).replace(/^the /, '').replace(/^final /, '');
  return EDIT_FIELDS.find((f) => norm(f.label) === t || norm(f.name).replace(/^final /, '') === t || f.synonyms.includes(t)) ?? null;
}

export const editableList = (): string => EDIT_FIELDS.map((f) => `${f.label} (${f.name})`).join(', ');

/** The value as the bridge stores it: a number for the numeric fields, a string otherwise; an error text when it does not fit. */
export function coerceValue(field: EditField, raw: string): { value: number | string } | { error: string } {
  const v = raw.trim().replace(/^["']|["']$/g, '').trim();
  if (!v) {
    return { error: `There is no new value for ${field.label}.` };
  }
  if (field.kind === 'text' || field.kind === 'currency') {
    if (field.kind === 'currency' && !/^[A-Za-z]{3}$/.test(v)) {
      return { error: `${field.label} must be a three-letter currency code such as USD or INR, not "${v}".` };
    }
    return v.length > 120 || /[\u0000-\u001f]/.test(v) ? { error: `That ${field.label} value is too long or has control characters.` } : { value: field.kind === 'currency' ? v.toUpperCase() : v };
  }
  let n = v.replace(/^[$€£₹]\s*/, '');
  if (field.kind === 'days') {
    n = n.replace(/\s*(days?|d)$/i, '');
  }
  if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(n)) {
    n = n.replace(/,/g, '');
  }
  const num = /^\d+(\.\d+)?$/.test(n) ? Number(n) : NaN;
  if (!Number.isFinite(num)) {
    return { error: `${field.label} must be a plain non-negative number, not "${v}".` };
  }
  if (field.kind === 'days' && !Number.isInteger(num)) {
    return { error: `${field.label} must be a whole number of days, not "${v}".` };
  }
  return { value: num };
}

export interface EditRequest {
  fieldText: string;
  /** Part number (CPN or manufacturer part number) or bom item id; empty when the sentence names none. */
  target: string;
  value: string;
}

const ID = String.raw`RFQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*`;
const NAMED_RFQ = new RegExp(String.raw`\b(?:in|for|on|of|from)\s+(?:the\s+)?(?:rfq\s+)?${ID}`, 'gi');
const EDIT = /^(?:(?:please|can you|could you|would you|i want to|i would like to|i'd like to)\s+)*(?:set|change|update|edit|modify)\s+(?:the\s+)?(.+?)(?:\s+(?:of|for)\s+(?:(?:part|item|bom item|cpn|pn)(?:\s+(?:number|id|no\.?))?\s+)?("[^"]+"|'[^']+'|\S+))?\s+to\s+(.+)$/i;

/** "set the moq of PN-100 to 500 in RFQ-00007" -> { fieldText: 'moq', target: 'PN-100', value: '500' }; null when it is not that shape. */
export function parseEdit(question: string): EditRequest | null {
  const q = question.replace(NAMED_RFQ, ' ').replace(/\s+/g, ' ').trim();
  const m = EDIT.exec(q);
  if (!m) {
    return null;
  }
  return { fieldText: m[1].trim(), target: (m[2] ?? '').replace(/^["']|["']$/g, ''), value: m[3].trim().replace(/[.!?]+$/, '') };
}

/** An edit when the sentence has the shape and names a known field or a part: "change the model to x" stays a settings question. */
export function isEditRequest(question: string): boolean {
  const e = parseEdit(question);
  return e !== null && (e.target !== '' || resolveField(e.fieldText) !== null);
}
