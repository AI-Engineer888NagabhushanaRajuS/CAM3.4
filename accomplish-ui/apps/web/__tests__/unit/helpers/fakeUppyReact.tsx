import { useEffect, useReducer } from 'react';
import type Uppy from '@uppy/core';

/** Uppy's Dashboard needs a real layout engine; in jsdom this stands in for it: one tile per file with a remove button, driven by the real Uppy instance. */
export function Dashboard({ uppy }: { uppy: Uppy }) {
  const [, redraw] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    uppy.on('file-added', redraw);
    uppy.on('file-removed', redraw);
    return () => { uppy.off('file-added', redraw); uppy.off('file-removed', redraw); };
  }, [uppy]);
  return (
    <ul aria-label="Files">
      {uppy.getFiles().map((f) => (
        <li key={f.id}>
          <span>{f.name}</span>
          <button type="button" aria-label={`Remove ${f.name}`} onClick={() => uppy.removeFile(f.id)} />
        </li>
      ))}
    </ul>
  );
}
