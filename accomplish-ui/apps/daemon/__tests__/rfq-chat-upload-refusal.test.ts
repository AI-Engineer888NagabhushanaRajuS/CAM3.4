import { afterEach, describe, expect, it, vi } from 'vitest';
import { realActionDeps } from '../src/rfq-chat/rfq-chat-actions-deps.js';

/** SPEC-023: the upload service refuses an invalid BOM with a 422 whose detail is an object; the user must read why, not "HTTP 422". */
describe('upload refusal reaches the user in words', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('reads detail.message and the first cells from the 422', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (String(url).includes('/auth/token')
      ? new Response(JSON.stringify({ token: 't' }), { status: 200 })
      : new Response(JSON.stringify({ detail: { code: 'input_invalid', message: 'The BOM was not accepted: 2 problems would give NaN or errors in the output.', issues: [{ sheet: 'SCRUB BOM', col: 'I', row: 5, message: 'Quantity "ten" is not a number.' }] } }), { status: 422 }))));
    const bytes = new Uint8Array([1]);
    await expect(realActionDeps().upload('RFQ-000099', { name: 'b.xlsx', bytes }, { name: 'v.xlsx', bytes })).rejects.toThrow(
      /HTTP 422: The BOM was not accepted: 2 problems.* First: SCRUB BOM I5: Quantity "ten" is not a number\./,
    );
  });

  it('a plain string detail still reads as before', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (String(url).includes('/auth/token')
      ? new Response(JSON.stringify({ token: 't' }), { status: 200 })
      : new Response(JSON.stringify({ detail: 'Unsupported file type' }), { status: 415 }))));
    const bytes = new Uint8Array([1]);
    await expect(realActionDeps().upload('RFQ-000099', { name: 'b.xlsx', bytes }, { name: 'v.xlsx', bytes })).rejects.toThrow('HTTP 415: Unsupported file type');
  });
});
