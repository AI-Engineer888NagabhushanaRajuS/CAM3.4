import { useRef } from 'react';
import { ArrowCounterClockwise, BracketsCurly, FloppyDisk, LockSimple, WarningCircle } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import { shortHash, type SubSkill } from '@/lib/manifestsApi';
import { ManifestEditor, type EditorHandle } from './ManifestEditor';
import { PreviewTabs } from './PreviewTabs';
import { StatusBadge } from './StatusBadge';
import { ValidationList } from './ValidationList';
import { offsetForPath, positionAt } from './jsonPath';
import type { useManifestFile } from './useManifestFile';

type State = ReturnType<typeof useManifestFile>;

/** Right-hand pane: toolbar, status line, banners, Monaco editor, validation list. */
export function ManifestPane({ m, path, subSkills = [] }: { m: State; path: string | null; subSkills?: SubSkill[] }) {
  const editor = useRef<EditorHandle>(null);
  const { file } = m;

  if (!path) return <Empty>Select a manifest on the left to view or edit it.</Empty>;
  if (m.loading && !file) return <Empty>Loading {path}...</Empty>;
  if (m.loadError) {
    return (
      <Empty>
        <WarningCircle className="mx-auto mb-2 h-6 w-6 text-destructive" aria-hidden="true" />
        <p role="alert">{m.loadError}</p>
        <Button className="mt-3" size="sm" variant="outline" onClick={m.reload}>Try again</Button>
      </Empty>
    );
  }
  if (!file) return null;

  const jump = (errPath: string) => {
    const { line, column } = positionAt(m.text, offsetForPath(m.text, errPath));
    editor.current?.jumpTo(line, column);
  };

  const json = (
    <>
      <div className="min-h-[240px] flex-1">
        <ManifestEditor
          ref={editor}
          path={file.path}
          kind={file.kind}
          schema={m.schema}
          value={m.text}
          readOnly={file.readOnly}
          onChange={m.setText}
          onSave={() => void m.save()}
        />
      </div>
      <div className="border-t border-border">
        <ValidationList validation={m.validation} onJump={jump} />
      </div>
    </>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <h2 className="min-w-0 flex-1 truncate font-mono text-xs font-semibold" title={file.path}>{file.path}</h2>
        <Button size="sm" onClick={() => void m.save()} disabled={!m.dirty || file.readOnly || m.saving} title="Save (Ctrl+S)">
          <FloppyDisk aria-hidden="true" />{m.saving ? 'Saving...' : 'Save'}
        </Button>
        <Button size="sm" variant="outline" onClick={m.revert} disabled={!m.dirty || m.saving}>
          <ArrowCounterClockwise aria-hidden="true" />Revert
        </Button>
        <Button size="sm" variant="outline" onClick={() => editor.current?.format()} disabled={file.readOnly}>
          <BracketsCurly aria-hidden="true" />Format
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground" aria-label="File status">
        <span>Version <b className="font-mono text-foreground">{file.version || 'n/a'}</b></span>
        <StatusBadge status={file.status} />
        <span>Hash <code className="font-mono text-foreground" title={file.hash}>{shortHash(file.hash)}</code></span>
        <span className={m.dirty ? 'font-semibold text-amber-700 dark:text-amber-400' : ''} role="status">
          {m.dirty ? '● Unsaved changes' : 'No unsaved changes'}
        </span>
      </div>

      {file.readOnly && (
        <p className="flex items-center gap-2 border-b border-border bg-muted/60 px-3 py-2 text-xs" role="note">
          <LockSimple className="h-4 w-4 shrink-0" aria-hidden="true" />
          Read-only: this is a live routing manifest. Change it with scripts/import_manifest.py.
        </p>
      )}
      {m.conflict && (
        <div className="flex flex-wrap items-center gap-2 border-b border-destructive/40 bg-destructive/10 px-3 py-2 text-xs" role="alert">
          <span className="min-w-0 flex-1">This file changed on disk since you opened it. Reload discards your edits; Keep mine lets your next save replace the disk version.</span>
          <Button size="sm" variant="outline" onClick={m.reload}>Reload</Button>
          <Button size="sm" variant="outline" onClick={m.keepMine}>Keep mine</Button>
        </div>
      )}
      {m.notice && (
        <p
          className={m.notice.tone === 'ok' ? 'border-b border-border bg-emerald-500/10 px-3 py-2 text-xs' : 'border-b border-destructive/40 bg-destructive/10 px-3 py-2 text-xs'}
          role={m.notice.tone === 'ok' ? 'status' : 'alert'}
        >
          {m.notice.message}
        </p>
      )}

      {file.kind === 'agent' ? json : (
        <PreviewTabs key={file.path} kind={file.kind} text={m.text} subSkills={subSkills} json={json} onJump={jump} />
      )}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="flex h-full min-h-[240px] items-center justify-center p-6 text-center text-sm text-muted-foreground"><div>{children}</div></div>;
}
