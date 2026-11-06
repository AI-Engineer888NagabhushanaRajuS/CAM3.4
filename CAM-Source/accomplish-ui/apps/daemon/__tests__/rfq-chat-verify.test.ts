import { describe, it, expect } from 'vitest';
import { unverifiedFigures, unverifiedByLine, resolveCitations, evidenceOnlyAnswer } from '../src/rfq-chat/rfq-chat-verify.js';

const chunk = (label: string, text: string) => ({ text, citation: { label } });
const evidence = [
  chunk('A CLASS PARTS!A185:AL185', 'A CLASS PARTS, row 185: Part Number=AC0603FR-0762KL; Mfg Name=YAGEO CO.; MOQ=5000; Lead Time=22; Cost #1=15.03888889; Share=0.05'),
  chunk('Manifest!A32:C32', 'Manifest, row 32: Field=Go / no-go; Value=GO'),
];

describe('the assistant may only say what the evidence says', () => {
  it('accepts figures and part numbers that are in the evidence, however they are formatted', () => {
    expect(unverifiedFigures('AC0603FR-0762KL has an MOQ of 5,000 [1] and a lead time of 22 weeks [1].', evidence)).toEqual([]);
    expect(unverifiedFigures('Cost #1 is 15.04 [1] (15.0389 to four places).', evidence)).toEqual([]); // rounding of a stored value
    expect(unverifiedFigures('The share is 5% [1].', evidence)).toEqual([]); // 0.05 stored
  });

  it('flags a figure the evidence does not contain', () => {
    expect(unverifiedFigures('The lead time is 8 weeks [1].', evidence)).toEqual(['8']);
    expect(unverifiedFigures('The MOQ is 6000 [1].', evidence)).toEqual(['6000']);
  });

  it('flags an invented part number', () => {
    expect(unverifiedFigures('Part ZZ9999-X has MOQ 5000 [1].', evidence)).toEqual(['ZZ9999-X']);
  });

  it('does not mistake list numbering, citation markers or a count of cited rows for figures', () => {
    expect(unverifiedFigures('1. MOQ 5000 [1]\n2. Lead time 22 [1]', evidence)).toEqual([]);
    expect(unverifiedFigures('Two rows match [1] [2].', evidence)).toEqual([]);
  });

  it('flags arithmetic the model did itself: a total that is not stated', () => {
    expect(unverifiedFigures('Together that is 5022 [1].', evidence)).toEqual(['5022']);
  });
});

describe('citations', () => {
  it('turns [n] into the cell it points at and reports which chunks were cited', () => {
    const out = resolveCitations('MOQ is 5000 [1]. Status GO [2].', evidence);
    expect(out.text).toBe('MOQ is 5000 (A CLASS PARTS!A185:AL185). Status GO (Manifest!A32:C32).');
    expect(out.cited).toEqual([0, 1]);
  });

  it('drops a marker that points at nothing', () => {
    const out = resolveCitations('Fact [9].', evidence);
    expect(out.cited).toEqual([]);
    expect(out.text).toBe('Fact .');
  });
});

describe('evidence-only answer', () => {
  it('lists the matched rows verbatim under the preface', () => {
    const out = evidenceOnlyAnswer(evidence, 'Here is exactly what the results contain:');
    expect(out).toContain('Here is exactly what the results contain:');
    expect(out).toContain('**Manifest!A32:C32**: Field=Go / no-go; Value=GO');
  });
});

describe('line by line: a figure must come from the row the line cites', () => {
  const two = [chunk('A!1', 'A, row 1: Part=AAA111; MOQ=5000'), chunk('B!2', 'B, row 2: Part=BBB222; MOQ=7000')];

  it('rejects a number that exists in the results but belongs to another row', () => {
    expect(unverifiedByLine('AAA111 has MOQ 7000 [1]', two)).toEqual(['7000']);
    expect(unverifiedByLine('AAA111 has MOQ 5000 [1]\nBBB222 has MOQ 7000 [2]', two)).toEqual([]);
  });

  it('checks a line without a citation against all the evidence', () => {
    expect(unverifiedByLine('The MOQs are 5000 and 7000', two)).toEqual([]);
    expect(unverifiedByLine('The MOQ is 9000', two)).toEqual(['9000']);
  });

  it('lets the answer repeat what the user typed in the question', () => {
    expect(unverifiedByLine('For 250 pcs: AAA111 [1]', two, 'price for 250 pcs')).toEqual([]);
    expect(unverifiedByLine('For 250 pcs: AAA111 [1]', two)).toEqual(['250']);
  });
});
