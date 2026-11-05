import { describe, it, expect } from 'vitest';
import { classify, rfqMentions } from '../src/rfq-chat/rfq-chat-intent.js';
import { dataClaims } from '../src/rfq-chat/rfq-chat-general.js';
import { parseScope } from '../src/rfq-chat/rfq-chat-scope.js';
import { findConflicts, parseRow } from '../src/rfq-chat/rfq-chat-conflicts.js';
import { loadGuide, pickSections } from '../src/rfq-chat/rfq-chat-guide.js';

describe('intent rules (no model involved)', () => {
  it.each([
    ['HAI HOW TO USE THIS TOOL ?', 'guide'],
    ['hi', 'guide'],
    ['hello there', 'guide'],
    ['how do I create an RFQ?', 'guide'],
    ['what can you do', 'guide'],
    ['help', 'guide'],
  ])('"%s" is answered from the guide', (text, intent) => {
    expect(classify(text)).toBe(intent);
  });

  it.each([
    ['what is the go / no-go status?', 'data'],
    ['which RFQs do I have?', 'data'],
    ['MOQ of UBR03225?', 'data'],
    ['what is the total spend', 'data'],
    ['how many parts have no price', 'data'],
    ['how do I see the MOQ in RFQ-00001', 'data'], // names an RFQ: data, not a how-to
  ])('"%s" is a data question', (text, intent) => {
    expect(classify(text)).toBe(intent);
  });

  it.each(['create an RFQ from this BOM', 'please make a new RFQ for Centum', 'upload this file and create the rfq'])('"%s" is the create action', (text) => {
    expect(classify(text)).toBe('create');
  });

  it.each(['tell me a joke', 'thanks!', 'ok cool', 'what is the capital of France'])('"%s" is left to the ordinary conversation', (text) => {
    expect(classify(text)).toBe('unsure');
  });
});

describe('RFQ mentions', () => {
  const known = ['RFQ-00001', 'RFQ-00010', 'RFQ-CENTUM-PROOF-24'];
  it('finds known ids case-insensitively and does not confuse a prefix with a longer id', () => {
    expect(rfqMentions('status of rfq-00001 please', known)).toEqual({ known: ['RFQ-00001'], unknown: [] });
    expect(rfqMentions('RFQ-00010 and RFQ-CENTUM-PROOF-24.', known).known.sort()).toEqual(['RFQ-00010', 'RFQ-CENTUM-PROOF-24']);
  });
  it('reports an RFQ-looking id that does not exist', () => {
    expect(rfqMentions('what about RFQ-99999?', known)).toEqual({ known: [], unknown: ['RFQ-99999'] });
  });
});

describe('no-data-claims check', () => {
  it('passes plain talk and small counts', () => {
    expect(dataClaims('Sure, there are 3 ways to do that. CAM 3.4 can help.', 'how many ways?')).toEqual([]);
  });
  it('flags RFQ ids, part numbers and figures the user did not write', () => {
    const bad = dataClaims('RFQ-00001 has UBR03225 at an MOQ of 5000 and a margin of 12.5%.', 'tell me something');
    expect(bad).toEqual(expect.arrayContaining(['RFQ-00001', 'UBR03225', '5000', '12.5%']));
  });
  it('lets the model echo what the user wrote', () => {
    expect(dataClaims('You wrote RFQ-00001 and 5000.', 'RFQ-00001 has an MOQ of 5000?')).toEqual([]);
  });
});

describe('scope parsing', () => {
  it('accepts the three modes and drops malformed input', () => {
    expect(parseScope({ mode: 'all' })).toEqual({ mode: 'all' });
    expect(parseScope({ mode: 'none' })).toEqual({ mode: 'none' });
    expect(parseScope({ mode: 'rfqs', rfqIds: ['A', 3, '', 'B'] })).toEqual({ mode: 'rfqs', rfqIds: ['A', 'B'] });
    expect(parseScope({ mode: 'rfqs' })).toBeUndefined();
    expect(parseScope('all')).toBeUndefined();
  });
});

describe('conflicts between rows', () => {
  const cite = (label: string) => ({ sourceType: 'excel_export' as const, label, identifier: {} });
  const row = (rfqId: string, text: string) => ({ rfqId, text, citation: cite(`${rfqId} · ${text.slice(0, 8)}`) });
  it('parses key=value rows and the sheet name', () => {
    const r = parseRow('CBOM, row 5: Part Number=UBR03225; MOQ=5000');
    expect(r.sheet).toBe('CBOM');
    expect(r.fields.get('MOQ')).toBe('5000');
  });
  it('reports a part whose value differs between RFQs, and ignores row numbers and equal values', () => {
    const rows = [
      row('RFQ-1', 'CBOM, row 5: Item=1; Part Number=UBR03225; Supplier=YAGEO; MOQ=5000'),
      row('RFQ-2', 'CBOM, row 9: Item=7; Part Number=UBR03225; Supplier=YAGEO; MOQ=7000'),
    ];
    const found = findConflicts(rows, ['ubr03225']);
    expect(found.map((c) => c.field)).toEqual(['MOQ']);
    expect(found[0].sides.map((s) => s.rfqId)).toEqual(['RFQ-1', 'RFQ-2']);
  });
  it('does not compare rows of different sheets', () => {
    const rows = [row('RFQ-1', 'CBOM, row 5: Part Number=UBR03225; Qty=1'), row('RFQ-2', 'BOM, row 2: Part Number=UBR03225; Qty=9')];
    expect(findConflicts(rows, ['UBR03225'])).toEqual([]);
  });
});

describe('the user guide', () => {
  it('loads from the repo docs and has the sections the assistant cites', () => {
    const sections = loadGuide();
    expect(sections).not.toBeNull();
    expect(sections!.map((s) => s.heading).join('|')).toContain('Create an RFQ');
    const picked = pickSections('how do I upload the BOM and volume file', sections!);
    expect(picked[0].heading).toMatch(/Upload the BOM/);
  });
  it('falls back to the overview and the assistant section for a bare greeting', () => {
    const picked = pickSections('hai', loadGuide()!);
    expect(picked.map((s) => s.heading).join('|')).toMatch(/What CAM 3\.4 does.*Ask the assistant/);
  });
});
