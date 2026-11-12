import { describe, it, expect } from 'vitest';
import { refusalMessage } from '@/lib/uploadRefusal';

const res = (status: number, body: unknown) => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });

describe('upload refusal message (SPEC-023)', () => {
  it('a pre-flight refusal names the cells and where to fix them, not just the status', async () => {
    const m = await refusalMessage(res(422, { detail: { code: 'input_invalid', message: 'The BOM was not accepted: 1 problem would give NaN.', issues: [{ sheet: 'SCRUB BOM', col: 'F', row: 7, message: 'text in a quantity' }] } }));
    expect(m).toContain('1 problem would give NaN');
    expect(m).toContain('SCRUB BOM F7: text in a quantity');
    expect(m).toContain('paperclip');
  });

  it('anything else (other status, string detail, not JSON) falls back to the status', async () => {
    expect(await refusalMessage(res(500, { detail: 'boom' }))).toBe('Server rejected the BOM upload (status 500).');
    expect(await refusalMessage(res(422, 'not json'))).toBe('Server rejected the BOM upload (status 422).');
  });
});
