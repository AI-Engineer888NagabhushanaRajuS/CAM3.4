import { useState } from 'react';
import { Check, Copy } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { shortHash, type SubSkill } from '@/lib/manifestsApi';
import { describeRepair } from '@/lib/manifestsCodegen';
import { ManifestEditor } from './ManifestEditor';
import type { Preview } from './usePreview';

interface Props { preview: Preview; subSkills: SubSkill[]; subSkillId: string | undefined; onSubSkill: (id: string) => void }

const SELECT = 'h-7 rounded-md border border-input bg-background px-1';

/** Read-only Python preview of the generated tool, with the bundle hash, AST gate and self-heal repairs. */
export function GeneratedView({ preview, subSkills, subSkillId, onSubSkill }: Props) {
  const [copied, setCopied] = useState(false);
  const [pick, setPick] = useState('');
  const { code } = preview;
  const names = code ? Object.keys(code.files) : [];
  const file = names.includes(pick) ? pick : names[0];

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code?.bundle_sha256 ?? '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked: the full hash is in the tooltip
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <p className="border-b border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">Preview only: nothing is executed or deployed (SPEC-020).</p>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-1.5 text-xs">
        {subSkills.length > 1 && (
          <label className="flex items-center gap-1.5">Sub-skill
            <select className={SELECT} value={subSkillId ?? ''} onChange={(e) => onSubSkill(e.target.value)}>
              <option value="">Default</option>
              {subSkills.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
        )}
        {names.length > 1 && (
          <label className="flex items-center gap-1.5">File
            <select className={SELECT} value={file} onChange={(e) => setPick(e.target.value)}>
              {names.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        )}
        {names.length === 1 && <code className="font-mono">{file}</code>}
        {code && (
          <span className="ml-auto flex items-center gap-1">
            Bundle <code className="font-mono" title={code.bundle_sha256}>{shortHash(code.bundle_sha256)}</code>
            <Button size="icon-sm" variant="ghost" onClick={() => void copy()} aria-label="Copy bundle sha256" title="Copy bundle sha256">
              {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            </Button>
          </span>
        )}
      </div>
      {preview.state === 'invalid' && <p className="px-3 py-2 text-xs text-muted-foreground" role="status">Invalid JSON: fix the syntax and the preview refreshes. ({preview.message})</p>}
      {preview.state === 'error' && <p className="px-3 py-2 text-xs text-destructive" role="alert">Preview unavailable. {preview.message}</p>}
      {preview.state === 'loading' && <p className="px-3 py-1 text-xs text-muted-foreground" role="status">Refreshing preview...</p>}
      {code && (
        <>
          <p className="px-3 py-1.5 text-xs" role="status">
            AST gate: {code.ast.ok ? 'passed, the generated code parses.' : `failed on ${code.ast.errors.length} line(s).`}
          </p>
          {!code.ast.ok && (
            <ul className="px-3 pb-1.5 text-xs text-destructive" aria-label="AST errors">
              {code.ast.errors.map((e, i) => <li key={i}>line {e.line}: {e.message}</li>)}
            </ul>
          )}
          {code.repairs.length > 0 && (
            <div className="px-3 pb-1.5 text-xs">
              <p className="font-semibold">Self-heal repairs ({code.repairs.length})</p>
              <ul className="list-disc pl-5">{code.repairs.map((r, i) => <li key={i}>{describeRepair(r)}</li>)}</ul>
            </div>
          )}
          <div className="min-h-[160px] flex-1">
            {file && <ManifestEditor path={`generated/${file}`} kind="generated" language="python" schema={null} value={code.files[file]} readOnly onChange={() => {}} onSave={() => {}} />}
          </div>
        </>
      )}
    </div>
  );
}
