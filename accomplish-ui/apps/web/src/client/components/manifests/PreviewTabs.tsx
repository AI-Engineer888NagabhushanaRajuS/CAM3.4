import { useEffect, useState, type ReactNode } from 'react';
import type { ManifestKind, SubSkill } from '@/lib/manifestsApi';
import { GeneratedView } from './GeneratedView';
import { LintList } from './LintList';
import { usePreview } from './usePreview';

type Tab = 'json' | 'generated' | 'lint';
interface Props {
  kind: ManifestKind;
  text: string;
  subSkills: SubSkill[];
  /** The JSON editor + validation list; stays mounted while another tab is shown. */
  json: ReactNode;
  onJump: (path: string) => void;
}

/** JSON | Generated tool | Lint, all driven by the live editor text (bridge preview, SPEC-020). */
export function PreviewTabs({ kind, text, subSkills, json, onJump }: Props) {
  const [tab, setTab] = useState<Tab>('json');
  const [subSkillId, setSubSkillId] = useState<string | undefined>();
  const [pending, setPending] = useState<string | null>(null);
  const preview = usePreview(text, kind, subSkillId);
  const findings = preview.lint?.findings ?? [];
  const errors = findings.filter((f) => f.level === 'error').length;

  // A lint click first reveals the JSON tab, then jumps (the editor can only reveal a line while visible).
  useEffect(() => {
    if (tab === 'json' && pending !== null) { onJump(pending); setPending(null); }
  }, [tab, pending, onJump]);

  const tabs: [Tab, string][] = [['json', 'JSON'], ['generated', 'Generated tool'], ['lint', `Lint (${preview.lint ? findings.length : '...'})`]];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div role="tablist" aria-label="Editor views" className="flex gap-1 border-b border-border px-2 pt-1">
        {tabs.map(([id, label]) => (
          <button
            key={id} type="button" role="tab" id={`tab-${id}`} aria-selected={tab === id} aria-controls={`panel-${id}`}
            onClick={() => setTab(id)}
            className={`min-h-7 rounded-t-md px-3 py-1 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${tab === id ? 'border-b-2 border-primary text-foreground' : 'text-muted-foreground hover:bg-accent'}`}
          >
            {label}{id === 'lint' && errors > 0 && <span className="ml-1 text-destructive">{errors} error{errors === 1 ? '' : 's'}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="panel-json" aria-labelledby="tab-json" hidden={tab !== 'json'} className="flex min-h-0 flex-1 flex-col">{json}</div>
      {tab === 'generated' && (
        <div role="tabpanel" id="panel-generated" aria-labelledby="tab-generated" className="min-h-0 flex-1">
          <GeneratedView preview={preview} subSkills={subSkills} subSkillId={subSkillId} onSubSkill={setSubSkillId} />
        </div>
      )}
      {tab === 'lint' && (
        <div role="tabpanel" id="panel-lint" aria-labelledby="tab-lint" className="min-h-0 flex-1 overflow-y-auto">
          <p className="border-b border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">Preview only: nothing is executed or deployed (SPEC-020).</p>
          {preview.state === 'invalid' && <p className="px-3 py-2 text-xs text-muted-foreground" role="status">Invalid JSON: lint resumes when the syntax is fixed.</p>}
          {preview.state === 'error' && <p className="px-3 py-2 text-xs text-destructive" role="alert">Lint unavailable. {preview.message}</p>}
          {preview.lint && <LintList findings={findings} onJump={(p) => { setPending(p); setTab('json'); }} />}
        </div>
      )}
    </div>
  );
}
