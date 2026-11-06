/**
 * The edit_value action (SPEC-020): "set the MOQ of PN-100 to 500 in RFQ-00007" from the chat. planEditValue reads the row
 * from the bridge and decides whether a confirmation card may be issued (refusals are plain messages and write nothing);
 * runEditValue is what Confirm runs: the bridge's one endpoint that applies the edit, regenerates the reports and compares
 * the new workbook with the old (nothing half-applied). Token, session binding, param hash and audit lines are shared
 * with create_rfq (rfq-chat-actions.ts).
 */
import type { ActionConfirmResponse } from './rfq-chat-contract.js';
import { UnknownOutcomeError, type ActionDeps, type BomRow, type EditValueParams } from './rfq-chat-actions-types.js';
import { coerceValue, editableList, resolveField } from './rfq-chat-edit-fields.js';

type Step = ActionConfirmResponse['steps'][number];

const shown = (v: string | number | null): string => (v === null || v === '' ? 'empty' : String(v));
const rowName = (r: BomRow): string => r.cpn || r.mpn || r.description || r.bomItemId;

export async function planEditValue(
  deps: ActionDeps,
  p: { rfqId: string; target: string; fieldText: string; value: string; volume?: number },
): Promise<{ message: string; params?: EditValueParams; summary?: string }> {
  const field = resolveField(p.fieldText);
  if (!field) {
    return { message: `I can't change "${p.fieldText}": it is not an editable value. I can change these: ${editableList()}. Nothing was changed.` };
  }
  if (!p.target) {
    return { message: `Which part? Give the part number or the bom item id, for example "set the ${field.label} of PN-100 to ... in ${p.rfqId}". Nothing was changed.` };
  }
  const coerced = coerceValue(field, p.value);
  if ('error' in coerced) {
    return { message: `${coerced.error} Nothing was changed.` };
  }
  const rows = await deps.findBomRows(p.rfqId, p.target);
  if (rows.length === 0) {
    return { message: `I can't find "${p.target}" (part number or bom item id) in the costed BOM of ${p.rfqId}, so I can't change it. Nothing was changed.` };
  }
  // One bom item id can have a row per volume: that is ONE target. Different ids are the ambiguous case.
  const ids = [...new Set(rows.map((r) => r.bomItemId))];
  const pick = ids.includes(p.target) ? [p.target] : ids;
  if (pick.length > 1) {
    const list = pick.slice(0, 5).map((id) => {
      const r = rows.find((x) => x.bomItemId === id)!;
      return `${id} (${rowName(r)}${r.fg ? `, FG ${r.fg}` : ''}${r.description ? `, ${r.description}` : ''})`;
    }).join('; ');
    return { message: `"${p.target}" matches ${pick.length} different bom items in ${p.rfqId}: ${list}${pick.length > 5 ? '; ...' : ''}. Tell me the bom item id of the one you mean. Nothing was changed.` };
  }
  const all = rows.filter((r) => r.bomItemId === pick[0]);
  const hit = p.volume === undefined ? all : all.filter((r) => r.volumeNo === p.volume);
  if (hit.length === 0) {
    const have = all.map((r) => r.volumeNo).filter((v) => v !== null).join(', ');
    return { message: `${rowName(all[0])} has no volume ${p.volume} in ${p.rfqId}${have ? ` (its volumes: ${have})` : ''}. Nothing was changed.` };
  }
  const volumes = hit.map((r) => ({ volumeNo: r.volumeNo, before: r.values[field.name] ?? null }));
  if (volumes.every((v) => v.before === coerced.value)) {
    return { message: `${field.label} of ${rowName(hit[0])} in ${p.rfqId} is already ${shown(coerced.value)}${hit.length > 1 ? ' in every volume' : ''}, so there is nothing to change.` };
  }
  const same = volumes.every((v) => v.before === volumes[0].before);
  const before = same ? volumes[0].before : volumes.map((v) => `Volume ${v.volumeNo ?? '?'}: ${shown(v.before)}`).join('; ');
  const row = hit[0];
  const params: EditValueParams = { rfqId: p.rfqId, bomItemId: row.bomItemId, label: rowName(row), field: field.name, fieldLabel: field.label, before, after: coerced.value, volumeNo: p.volume ?? null, volumes };
  const scope = p.volume !== undefined ? ` (volume ${p.volume} only)` : hit.length > 1 ? `, in all ${hit.length} volume rows` : '';
  return {
    message: `${field.label} of ${params.label} in ${p.rfqId} is ${shown(before)}${hit.length > 1 && p.volume === undefined ? '; the change applies to every volume row of this item (say "volume 2" to change one volume only)' : ''}. Check the change and press Confirm to apply it and regenerate the reports; nothing happens until you do.`,
    params,
    summary: `Change ${field.label} of ${params.label} (bom item ${params.bomItemId}${scope}) in ${p.rfqId} from ${shown(before)} to ${shown(params.after)}, then regenerate the reports as a new version.`,
  };
}

export async function runEditValue(
  deps: ActionDeps,
  p: EditValueParams,
  audit: (action: string, result: string) => Promise<void>,
): Promise<ActionConfirmResponse> {
  const steps: Step[] = [];
  const stop = async (name: string, why: string, message: string): Promise<ActionConfirmResponse> => {
    steps.push({ step: name, status: 'failed', detail: why });
    await audit(`edit_value.${name}`, `failed: ${why}`);
    return { ok: false, rfqId: p.rfqId, message, steps };
  };

  // The card may be minutes old: the row must still hold the value the user saw.
  try {
    const rows = (await deps.findBomRows(p.rfqId, p.bomItemId)).filter((r) => r.bomItemId === p.bomItemId);
    for (const v of p.volumes) {
      const row = rows.find((r) => r.volumeNo === v.volumeNo);
      const vol = v.volumeNo === null ? '' : ` (volume ${v.volumeNo})`;
      if (!row) {
        return stop('check_row', `the row${vol} no longer exists`, `Stopped: the row ${p.bomItemId}${vol} is no longer in ${p.rfqId}. Nothing was changed.`);
      }
      const now = row.values[p.field] ?? null;
      if (now !== v.before) {
        return stop('check_row', `the value${vol} is now ${shown(now)}`, `Stopped: ${p.fieldLabel}${vol} is now ${shown(now)}, not ${shown(v.before)} as on the card, so it changed since. Ask me again. Nothing was changed.`);
      }
    }
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err);
    return stop('check_row', why, `Stopped at check_row: ${why}. Nothing was changed.`);
  }
  steps.push({ step: 'check_row', status: 'done', detail: `${p.fieldLabel} still ${shown(p.before)} in ${p.volumes.length} row${p.volumes.length === 1 ? '' : 's'}` });
  await audit('edit_value.check_row', 'done');

  try {
    const r = await deps.editAndRegenerate(p.rfqId, { bomItemId: p.bomItemId, field: p.field, value: p.after, ...(p.volumeNo !== null ? { volumeNo: p.volumeNo } : {}) }, `assistant: ${p.fieldLabel} ${shown(p.before)} -> ${shown(p.after)}`);
    if (r.applied < 1) {
      return stop('edit_and_regenerate', 'the service applied no row', `The service applied no row, so nothing was changed and no new version exists.`);
    }
    const cells = r.diff
      ? `${r.diff.total_changed_cells} changed cell${r.diff.total_changed_cells === 1 ? '' : 's'} across ${r.diff.sheets.filter((s) => s.changed > 0).length} sheet${r.diff.sheets.filter((s) => s.changed > 0).length === 1 ? '' : 's'}`
      : 'no cell comparison (there was no earlier version to compare with)';
    const detail = `new version ${r.after.filename}; ${cells}`;
    steps.push({ step: 'edit_and_regenerate', status: 'done', detail });
    await audit('edit_value.edit_and_regenerate', `done: ${detail}`);
    return {
      ok: true,
      rfqId: p.rfqId,
      message: `Changed ${p.fieldLabel} of ${p.label} in ${p.rfqId} from ${shown(p.before)} to ${shown(p.after)} and regenerated the reports. New version: ${r.after.filename}${r.before ? ` (the previous one, ${r.before.filename}, stays downloadable)` : ''}. ${cells[0].toUpperCase()}${cells.slice(1)}. The new version is downloadable with the button below and in the Versions list of the right pane.`,
      steps,
      ui: { type: 'open_export', rfqId: p.rfqId },
    };
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err);
    if (err instanceof UnknownOutcomeError) {
      return stop('edit_and_regenerate', why, `Stopped at edit_and_regenerate: ${why}. The edit may have been applied: check the costed BOM and the Versions list before asking again.`);
    }
    return stop('edit_and_regenerate', why, `Stopped at edit_and_regenerate: ${why}. The service keeps nothing half-applied: the edit is not kept when the regeneration fails.`);
  }
}
