import { useCallback, useEffect, useState } from 'react';
import { useBlocker, useNavigate, useSearchParams } from 'react-router';
import { ArrowLeft, Info } from '@phosphor-icons/react';
import { BrandMark } from '@/components/BrandMark';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { Button } from '@/components/ui/button';
import { ManifestPane } from '@/components/manifests/ManifestPane';
import { ManifestTree } from '@/components/manifests/ManifestTree';
import { useManifestFile } from '@/components/manifests/useManifestFile';
import { fetchManifestTree, type ManifestTree as Tree } from '@/lib/manifestsApi';

const LEAVE = 'You have unsaved manifest edits. Leave and discard them?';

/** #/manifests?path=skills/skill_01_input_standardization.json : agent > skill > sub-skill tree + Monaco JSON editor (SPEC-020). */
export function ManifestsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const path = params.get('path');
  const [tree, setTree] = useState<Tree | null>(null);
  const [treeError, setTreeError] = useState<string | null>(null);

  const loadTree = useCallback(() => {
    fetchManifestTree().then((t) => { setTree(t); setTreeError(null); })
      .catch((e: unknown) => setTreeError(e instanceof Error ? e.message : 'Could not load the manifest list.'));
  }, []);
  useEffect(loadTree, [loadTree]);

  const m = useManifestFile(path, loadTree);

  const blocker = useBlocker(m.dirty);
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    if (window.confirm(LEAVE)) blocker.proceed(); else blocker.reset();
  }, [blocker]);
  useEffect(() => {
    if (!m.dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [m.dirty]);

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-4">
        <Button variant="ghost" size="icon-sm" onClick={() => navigate('/')} aria-label="Back to workspace" title="Back to workspace">
          <ArrowLeft aria-hidden="true" />
        </Button>
        <BrandMark className="text-base" />
        <h1 className="text-sm font-semibold text-muted-foreground">Manifests</h1>
        <div className="ml-auto"><ThemeToggle /></div>
      </header>

      <p className="flex shrink-0 items-start gap-2 border-b border-border bg-amber-500/10 px-4 py-2 text-xs" role="note">
        <Info className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
        Saving versions the file. A skill's enabled flag switches its pipeline steps on or off; sequence and ui_actions shape the left pane; everything else is design input (SPEC-025).
      </p>

      <main className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,40%)_minmax(0,1fr)] min-[900px]:grid-cols-[minmax(280px,380px)_minmax(0,1fr)] min-[900px]:grid-rows-1">
        <nav aria-label="Manifest list" className="min-h-0 overflow-y-auto border-b border-border bg-card px-2 py-2 min-[900px]:border-b-0 min-[900px]:border-r">
          {tree ? (
            <ManifestTree tree={tree} selectedPath={path} onSelect={(p) => setParams({ path: p })} />
          ) : treeError ? (
            <div className="p-3 text-sm" role="alert">
              <p>{treeError}</p>
              <Button className="mt-2" size="sm" variant="outline" onClick={loadTree}>Try again</Button>
            </div>
          ) : <p className="p-3 text-sm text-muted-foreground">Loading manifests...</p>}
        </nav>
        <section aria-label="Manifest editor" className="min-h-0 min-w-0">
          <ManifestPane m={m} path={path} subSkills={tree?.agent?.skills.find((k) => k.path === path)?.subSkills} />
        </section>
      </main>
    </div>
  );
}

export const Component = ManifestsPage;
