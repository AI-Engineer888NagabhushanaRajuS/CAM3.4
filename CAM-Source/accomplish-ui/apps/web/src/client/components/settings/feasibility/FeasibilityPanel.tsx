import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { getAccomplish, type FeasibilityMachineRule, type FeasibilitySettingsInput } from '@/lib/accomplish';

// Mirrors daemon/src/feasibility-settings.ts: the same columns, operators and effects the server accepts.
const COLUMNS = [
  'fg', 'assembly', 'cpn', 'description', 'manufacturer', 'mpn', 'commodity', 'quantity', 'unit_of_measure', 'part_status',
  'ce_remarks', 'drawing_reference', 'designators', 'part_type', 'ltb_date', 'inventory_stock',
];
const OPERATORS: Array<[string, string]> = [
  ['contains', 'contains'], ['not_contains', 'does not contain'], ['equals', 'equals'], ['not_equals', 'does not equal'],
  ['gt', 'greater than'], ['gte', 'at least'], ['lt', 'less than'], ['lte', 'at most'], ['empty', 'is empty'], ['not_empty', 'is not empty'],
];
const EFFECTS: Array<[string, string]> = [['cannot_build', 'Cannot build'], ['high', 'Risk: High'], ['medium', 'Risk: Medium']];
const NO_VALUE = new Set(['empty', 'not_empty']);

const list = (s: string): string[] => s.split(',').map((x) => x.trim()).filter(Boolean);

// The panel edits the list as text ("EOL, DISCONTINUED"); the server gets arrays.
interface Draft extends Omit<FeasibilitySettingsInput, 'cannot_build_statuses' | 'medium_statuses'> {
  cannot_build_statuses: string;
  medium_statuses: string;
}
const toDraft = (s: FeasibilitySettingsInput): Draft => ({ ...s, cannot_build_statuses: s.cannot_build_statuses.join(', '), medium_statuses: s.medium_statuses.join(', ') });
const fromDraft = (d: Draft): FeasibilitySettingsInput => ({ ...d, cannot_build_statuses: list(d.cannot_build_statuses), medium_statuses: list(d.medium_statuses) });

export function FeasibilityPanel() {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [defaults, setDefaults] = useState<FeasibilitySettingsInput | null>(null);
  const [saved, setSaved] = useState(false);
  const [updated, setUpdated] = useState<{ at: string | null; by: string | null }>({ at: null, by: null });
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getAccomplish().feasibilityGetSettings()
      .then((r) => {
        if (!alive) { return; }
        setDraft(toDraft(r.settings));
        setDefaults(r.defaults);
        setSaved(r.saved);
        setUpdated({ at: r.updatedAt, by: r.updatedBy });
      })
      .catch((err: unknown) => setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not load the Feasibility rules' }));
    return () => { alive = false; };
  }, []);

  if (!draft || !defaults) {
    return <div className="flex h-[360px] items-center justify-center text-sm text-muted-foreground">Loading Feasibility rules...</div>;
  }

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft({ ...draft, [key]: value });
  const setRule = (i: number, patch: Partial<FeasibilityMachineRule>) =>
    set('constraints', draft.constraints.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addRule = () =>
    set('constraints', [...draft.constraints, { name: '', column: 'description', operator: 'contains', value: '', effect: 'cannot_build' }]);
  const removeRule = (i: number) => set('constraints', draft.constraints.filter((_, idx) => idx !== i));

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const r = await getAccomplish().feasibilitySaveSettings({ settings: fromDraft(draft) });
      setSaved(r.saved);
      setUpdated({ at: new Date().toISOString(), by: updated.by });
      setMessage({ kind: 'ok', text: 'Saved. Every RFQ that runs the Feasibility & Risk step from now on uses these rules.' });
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not save the rules' });
    } finally {
      setBusy(false);
    }
  };

  const resetToDefaults = () => {
    setDraft(toDraft(defaults));
    setMessage({ kind: 'ok', text: 'Defaults filled in. Press Save to apply them.' });
  };

  const field = 'mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm';
  const check = 'h-4 w-4 accent-primary';

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
        {saved
          ? `Rules saved${updated.at ? ` ${new Date(updated.at).toLocaleString()}` : ''}${updated.by ? ` by ${updated.by}` : ''}.`
          : 'Nothing saved yet: the documented defaults below apply to every RFQ. Press Save to make these the rules the pipeline uses.'}
        {' '}Each RFQ records the rules it used, and its Feasibility &amp; Risk tab shows them.
      </div>

      <label className="block text-sm">
        <span className="font-medium">Lead-time limit (weeks)</span>
        <span className="block text-xs text-muted-foreground">A best lead time above this is Risk: Medium.</span>
        <input type="number" min={1} max={520} className={field} value={draft.lead_time_limit_weeks}
          onChange={(e) => set('lead_time_limit_weeks', Number(e.target.value))} />
      </label>

      <label className="block text-sm">
        <span className="font-medium">Cannot-build statuses</span>
        <span className="block text-xs text-muted-foreground">Part Status values that make a line Cannot build, separated by commas.</span>
        <input className={field} value={draft.cannot_build_statuses} onChange={(e) => set('cannot_build_statuses', e.target.value)} />
      </label>

      <label className="block text-sm">
        <span className="font-medium">Medium-risk statuses</span>
        <span className="block text-xs text-muted-foreground">Part Status values that make a line Risk: Medium, separated by commas.</span>
        <input className={field} value={draft.medium_statuses} onChange={(e) => set('medium_statuses', e.target.value)} />
      </label>

      <fieldset className="flex flex-col gap-2 text-sm">
        <legend className="font-medium">Other rules</legend>
        <label className="flex items-center gap-2"><input type="checkbox" className={check} checked={draft.no_price_cannot_build} onChange={(e) => set('no_price_cannot_build', e.target.checked)} />A line with no quote with a price is Cannot build</label>
        <label className="flex items-center gap-2"><input type="checkbox" className={check} checked={draft.no_lead_time_high} onChange={(e) => set('no_lead_time_high', e.target.checked)} />A priced line with no lead time is Risk: High</label>
        <label className="flex items-center gap-2"><input type="checkbox" className={check} checked={draft.ltb_high} onChange={(e) => set('ltb_high', e.target.checked)} />A last-time-buy date is Risk: High</label>
        <label className="flex items-center gap-2"><input type="checkbox" className={check} checked={draft.ncnr_medium} onChange={(e) => set('ncnr_medium', e.target.checked)} />NCNR is Risk: Medium</label>
        <label className="flex items-center gap-2"><input type="checkbox" className={check} checked={draft.expired_validity_medium} onChange={(e) => set('expired_validity_medium', e.target.checked)} />Every quote's price validity has passed is Risk: Medium</label>
      </fieldset>

      <div className="flex flex-col gap-2">
        <div>
          <p className="text-sm font-medium">Machine rules</p>
          <p className="text-xs text-muted-foreground">
            The BOM does not carry machine data, so a rule can only test what the BOM says: for example, a description that contains "0201" is Cannot build on your placement line.
            No EMS template is used.
          </p>
        </div>
        {draft.constraints.length === 0 && <p className="text-xs text-muted-foreground">No machine rules yet.</p>}
        {draft.constraints.map((rule, i) => {
          const noValue = NO_VALUE.has(rule.operator);
          return (
            <div key={i} className="grid grid-cols-1 gap-2 rounded-md border border-border p-3 md:grid-cols-[1.2fr_1fr_1fr_1.2fr_1fr_auto]">
              <input aria-label="Rule name" placeholder="Rule name" className={field} value={rule.name} onChange={(e) => setRule(i, { name: e.target.value })} />
              <select aria-label="BOM column" className={field} value={rule.column} onChange={(e) => setRule(i, { column: e.target.value })}>
                {COLUMNS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select aria-label="Operator" className={field} value={rule.operator} onChange={(e) => setRule(i, { operator: e.target.value })}>
                {OPERATORS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
              <input aria-label="Value" placeholder={noValue ? '(no value needed)' : 'Value'} disabled={noValue} className={field} value={rule.value} onChange={(e) => setRule(i, { value: e.target.value })} />
              <select aria-label="Effect" className={field} value={rule.effect} onChange={(e) => setRule(i, { effect: e.target.value })}>
                {EFFECTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
              <Button variant="ghost" size="sm" onClick={() => removeRule(i)} aria-label="Remove rule">Remove</Button>
            </div>
          );
        })}
        <div><Button variant="outline" size="sm" onClick={addRule}>+ Add machine rule</Button></div>
      </div>

      {message && (
        <p className={`text-xs ${message.kind === 'ok' ? 'text-muted-foreground' : 'text-destructive'}`} role="status">{message.text}</p>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => void save()} disabled={busy}>{busy ? 'Saving...' : 'Save'}</Button>
        <Button variant="outline" size="sm" onClick={resetToDefaults} disabled={busy}>Reset to defaults</Button>
      </div>
    </div>
  );
}
