/**
 * Deterministic checks that keep the RFQ assistant honest. A model's answer is only shown when every figure and every
 * part-number-like token in it appears in the evidence it was given, and it cites at least one evidence row. No model
 * is involved here: these are string and number comparisons.
 *
 * A figure on a line that cites rows must be in THOSE rows (a number that exists in the results but belongs to another
 * row is wrong, not verified). A line with no citation is checked against all the evidence. Figures and codes the user
 * typed in the question are allowed back: echoing them is not an invention.
 */

export interface EvidenceChunk {
  text: string;
  citation: { label: string };
}

// A number: optional sign, digits with thousands commas, optional decimals, optional %. Not part of a word or a code.
const NUMBER = /(?<![A-Za-z0-9_.+-])[-+]?\$?\d[\d,]*(?:\.\d+)?%?/g;
// A part-number-like token: letters and digits mixed (UBR03225, AC0603FR-0762KL) or a long hyphenated number.
const CODE = /(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9._/-]{3,}(?![A-Za-z0-9])/g;
const MARKER = /\[(\d+)\]/g;

function stripNoise(answer: string): string {
  return answer
    .replace(/\[\d+\]/g, ' ') // citation markers
    .replace(/^\s*(?:[-*•]|\d+[.)])\s+/gm, '') // list markers
    .replace(/\|?\s*:?-{3,}:?\s*(?=\|)/g, ' '); // markdown table rules
}

function parse(raw: string): { value: number; decimals: number; percent: boolean } {
  const percent = raw.endsWith('%');
  const clean = raw.replace(/[$,%+]/g, '');
  return { value: Number(clean), decimals: clean.includes('.') ? clean.split('.')[1].length : 0, percent };
}

function numbersIn(text: string): number[] {
  return (text.match(NUMBER) ?? []).map((m) => parse(m).value).filter((n) => Number.isFinite(n));
}

function matchesEvidence(raw: string, numbers: number[], citedRows: number): boolean {
  const { value, decimals, percent } = parse(raw);
  if (!Number.isFinite(value)) return true;
  const round = (n: number, d: number) => Number(n.toFixed(d));
  if (numbers.some((e) => e === value || round(e, decimals) === value)) return true;
  if (percent && numbers.some((e) => round(e * 100, decimals) === value)) return true; // 0.05 stored, "5%" said
  // a small count of the rows the answer itself cites ("3 matching rows") is the answer's own bookkeeping
  return Number.isInteger(value) && value > 0 && value <= citedRows;
}

const evidenceText = (chunks: EvidenceChunk[]) => chunks.map((c) => `${c.citation.label} ${c.text}`).join('\n');

/** Figures and code-like tokens of `text` that neither `evidence` nor `allowed` contains. */
function check(text: string, evidence: string, citedRows: number, allowed: string): string[] {
  const numbers = [...numbersIn(evidence), ...numbersIn(allowed)];
  const lower = `${evidence}\n${allowed}`.toLowerCase();
  const clean = stripNoise(text);
  const bad = new Set<string>();
  for (const raw of clean.match(NUMBER) ?? []) {
    if (!matchesEvidence(raw, numbers, citedRows)) bad.add(raw);
  }
  for (const token of clean.match(CODE) ?? []) {
    const hasDigit = /\d/.test(token);
    const hasLetter = /[A-Za-z]/.test(token);
    const codeLike = hasDigit && (hasLetter || (token.includes('-') && token.length >= 7));
    if (codeLike && !lower.includes(token.toLowerCase())) bad.add(token);
  }
  return [...bad];
}

const distinctMarkers = (text: string) => new Set(text.match(MARKER) ?? []).size;

/** Figures and part-number-like tokens in the answer that the evidence does not contain. Empty = verified. */
export function unverifiedFigures(answer: string, chunks: EvidenceChunk[], allowed = ''): string[] {
  return check(answer, evidenceText(chunks), distinctMarkers(answer), allowed);
}

/** Same check, line by line: a line that cites rows is held to those rows. */
export function unverifiedByLine(answer: string, chunks: EvidenceChunk[], allowed = ''): string[] {
  const cited = distinctMarkers(answer);
  const bad = new Set<string>();
  for (const line of answer.split('\n')) {
    const rows = [...line.matchAll(MARKER)].map((m) => chunks[Number(m[1]) - 1]).filter((c): c is EvidenceChunk => !!c);
    for (const t of check(line, evidenceText(rows.length ? rows : chunks), cited, allowed)) bad.add(t);
  }
  return [...bad];
}

/** Replaces [n] markers with the cell they point at, and says which chunks were cited (0-based). */
export function resolveCitations(answer: string, chunks: EvidenceChunk[]): { text: string; cited: number[] } {
  const cited = new Set<number>();
  const text = answer.replace(MARKER, (_whole, n: string) => {
    const i = Number(n) - 1;
    if (i < 0 || i >= chunks.length) return ''; // a marker that points at nothing is dropped, never trusted
    cited.add(i);
    return ` (${chunks[i].citation.label})`;
  });
  return { text: text.replace(/ {2,}/g, ' ').trim(), cited: [...cited].sort((a, b) => a - b) };
}

/** What the results contain, verbatim, when a verified summary could not be produced. */
export function evidenceOnlyAnswer(chunks: EvidenceChunk[], preface: string, limit = 8): string {
  const shown = chunks.slice(0, limit).map((c) => `- **${c.citation.label}**: ${c.text.replace(/^[^:]*: /, '').slice(0, 360)}`);
  return `${preface}\n\n${shown.join('\n')}`;
}
