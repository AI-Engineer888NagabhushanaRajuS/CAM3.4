import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchManifestFile, fetchManifestSchema, saveManifestFile, shortHash,
  type ManifestFile, type ManifestKind, type Validation,
} from '@/lib/manifestsApi';

export interface Notice { tone: 'ok' | 'error'; message: string }
const messageOf = (e: unknown) => (e instanceof Error ? e.message : 'Unknown error');

/** Loads one manifest (and its kind's schema), tracks edits and runs the save/conflict protocol. */
export function useManifestFile(path: string | null, onSaved: () => void) {
  const [file, setFile] = useState<ManifestFile | null>(null);
  const [text, setText] = useState('');
  const [baseHash, setBaseHash] = useState('');
  const [schema, setSchema] = useState<object | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [conflict, setConflict] = useState<{ currentHash: string } | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const schemas = useRef(new Map<ManifestKind, object>());
  const latest = useRef(0);

  const load = useCallback(async (p: string) => {
    const mine = ++latest.current;
    setLoading(true); setLoadError(null); setNotice(null); setConflict(null);
    try {
      const f = await fetchManifestFile(p);
      let s = schemas.current.get(f.kind);
      if (!s) { s = await fetchManifestSchema(f.kind).catch(() => undefined); if (s) schemas.current.set(f.kind, s); }
      if (mine !== latest.current) return;
      setFile(f); setText(f.text); setBaseHash(f.hash); setValidation(f.validation); setSchema(s ?? null);
    } catch (e) {
      if (mine !== latest.current) return;
      setFile(null); setLoadError(messageOf(e));
    } finally {
      if (mine === latest.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (path) void load(path);
    else { latest.current++; setFile(null); setLoadError(null); setLoading(false); }
  }, [path, load]);

  const save = useCallback(async () => {
    if (!file || file.readOnly || saving || text === file.text) return;
    setSaving(true); setNotice(null);
    try {
      const r = await saveManifestFile({ path: file.path, text, baseHash });
      if (r.type === 'ok') {
        setNotice({ tone: 'ok', message: `Saved: version ${file.version} -> ${r.file.version}, hash ${shortHash(r.file.hash)}` });
        setFile({ ...file, ...r.file }); setText(r.file.text); setBaseHash(r.file.hash); setValidation(r.file.validation); setConflict(null);
        onSaved();
      } else if (r.type === 'invalid') {
        setValidation(r.validation);
        setNotice({ tone: 'error', message: `Not saved: ${r.validation.errors.length} problem(s) to fix. Your text is kept.` });
      } else if (r.type === 'conflict') {
        setConflict({ currentHash: r.currentHash });
      } else {
        setNotice({ tone: 'error', message: `Not saved. ${r.message}` });
      }
    } catch (e) {
      setNotice({ tone: 'error', message: `Not saved. ${messageOf(e)}` });
    } finally {
      setSaving(false);
    }
  }, [file, text, baseHash, saving, onSaved]);

  return {
    file, text, setText, schema, loading, loadError, saving, notice, conflict, validation,
    dirty: !!file && text !== file.text,
    save,
    revert: () => { if (file) { setText(file.text); setNotice(null); } },
    reload: () => { if (path) void load(path); },
    /** Keep my text and overwrite what changed on disk with the next save. */
    keepMine: () => {
      if (!conflict) return;
      setBaseHash(conflict.currentHash); setConflict(null);
      setNotice({ tone: 'ok', message: 'Kept your text. The next save replaces the version now on disk.' });
    },
  };
}
