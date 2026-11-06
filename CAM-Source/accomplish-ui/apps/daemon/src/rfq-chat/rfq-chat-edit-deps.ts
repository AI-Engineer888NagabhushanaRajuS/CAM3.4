/**
 * The two bridge calls behind the edit_value action (SPEC-020): read costed-BOM rows (the preview endpoint the app's
 * BOM grid uses) and POST /api/rfq/{id}/edit-and-regenerate. Same token minting as the other actions (passed in, so this file
 * does not import rfq-chat-actions-deps.ts).
 */
import { UnknownOutcomeError, type ActionDeps, type BomRow } from './rfq-chat-actions-types.js';
import { EDIT_FIELDS } from './rfq-chat-edit-fields.js';

interface Bridge {
  bridge: () => string;
  authHeader: (rfqId: string) => Promise<Record<string, string>>;
  failure: (res: Response, what: string) => Promise<Error>;
}

const PAGE = 1000; // the preview endpoint's maximum
const MAX_PAGES = 30; // ponytail: 30,000 rows per RFQ is far above any costed BOM; a bridge lookup by part number would replace the scan
const MAX_VOLUMES = 10; // ponytail: an RFQ with more volumes than this needs a bridge-side lookup by part number
const REGENERATION_MS = 330_000; // the bridge's own limit is 300 s

const text = (v: unknown): string => (v === null || v === undefined ? '' : String(v));
const scalar = (v: unknown): string | number | null => (typeof v === 'number' || typeof v === 'string' ? v : null);

export function toBomRow(r: Record<string, unknown>, volumeNo: number | null = null): BomRow {
  return {
    bomItemId: text(r.bom_item_id),
    volumeNo: typeof r.volume_no === 'number' ? r.volume_no : volumeNo,
    cpn: text(r.cpn),
    mpn: text(r.mfg_part_number),
    fg: text(r.fg),
    description: text(r.description),
    values: Object.fromEntries(EDIT_FIELDS.map((f) => [f.name, scalar(r[f.name])])),
  };
}

export function realEditDeps({ bridge, authHeader, failure }: Bridge): Pick<ActionDeps, 'findBomRows' | 'editAndRegenerate'> {
  return {
    async findBomRows(rfqId, target) {
      const want = target.trim().toLowerCase();
      const found: BomRow[] = [];
      // One volume per call: the first call (no volume_no) answers with the lowest volume, then the next volumes until one is empty.
      let volume: number | null = null;
      for (let v = 0; v < MAX_VOLUMES; v += 1) {
        let cursor = '';
        let seen = 0;
        for (let page = 0; ; page += 1) {
          if (page >= MAX_PAGES) {
            throw new Error(`the costed BOM of ${rfqId} has more than ${PAGE * MAX_PAGES} rows in one volume`);
          }
          const vol = volume === null ? '' : `&volume_no=${volume}`;
          const res = await fetch(`${bridge()}/api/bom/preview/${encodeURIComponent(rfqId)}?limit=${PAGE}${vol}${cursor}`, { headers: await authHeader(rfqId), signal: AbortSignal.timeout(60000) });
          if (!res.ok) {
            throw await failure(res, 'the costed BOM');
          }
          const body = (await res.json()) as { volume_no?: number; data?: Array<Record<string, unknown>>; next_cursor?: { cursor_fg: string; cursor_cpn: string; cursor_id: string } | null };
          volume = typeof body.volume_no === 'number' ? body.volume_no : (volume ?? 1);
          for (const r of body.data ?? []) {
            const row = toBomRow(r, volume);
            seen += 1;
            if ([row.bomItemId, row.cpn, row.mpn].some((x) => x.toLowerCase() === want)) {
              found.push(row);
            }
          }
          const next = body.next_cursor;
          if (!next) {
            break;
          }
          cursor = `&cursor_fg=${encodeURIComponent(next.cursor_fg)}&cursor_cpn=${encodeURIComponent(next.cursor_cpn)}&cursor_id=${encodeURIComponent(next.cursor_id)}`;
        }
        if (seen === 0) {
          break;
        }
        volume = (volume ?? 1) + 1;
      }
      return found;
    },
    async editAndRegenerate(rfqId, edit, note) {
      const headers = { 'Content-Type': 'application/json', ...(await authHeader(rfqId)) }; // a failed mint means nothing was sent
      let res: Response;
      try {
        res = await fetch(`${bridge()}/api/rfq/${encodeURIComponent(rfqId)}/edit-and-regenerate`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ edits: [{ bom_item_id: edit.bomItemId, ...(edit.volumeNo !== undefined ? { volume_no: edit.volumeNo } : {}), set: { [edit.field]: edit.value } }], note }),
          signal: AbortSignal.timeout(REGENERATION_MS),
        });
      } catch (err) {
        // The bridge may have applied and regenerated before the connection dropped.
        throw new UnknownOutcomeError(`the reporting service did not answer (${err instanceof Error ? err.message : String(err)})`);
      }
      if (!res.ok) {
        throw await failure(res, 'the reporting service');
      }
      const out = (await res.json()) as { applied?: number; before?: { filename: string } | null; after?: { filename: string; generated_at?: string }; diff?: EditDiff | null };
      if (!out.after?.filename) {
        throw new Error('the reporting service answered without a new filename');
      }
      return { applied: out.applied ?? 0, before: out.before ?? null, after: out.after, diff: out.diff ? { total_changed_cells: out.diff.total_changed_cells, sheets: out.diff.sheets ?? [] } : null };
    },
  };
}

interface EditDiff {
  total_changed_cells: number;
  sheets?: Array<{ sheet: string; changed: number }>;
}
