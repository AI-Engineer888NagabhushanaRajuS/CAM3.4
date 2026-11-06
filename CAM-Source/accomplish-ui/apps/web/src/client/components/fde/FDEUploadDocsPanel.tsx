import { useEffect, useMemo, useState } from 'react';
import Uppy from '@uppy/core';
import XHRUpload from '@uppy/xhr-upload';
import { Dashboard } from '@uppy/react';
import '@uppy/core/dist/style.min.css';
import '@uppy/dashboard/dist/style.min.css';
import { FileText } from '@phosphor-icons/react';
import { FDE_UPLOAD_URL } from '@/config/endpoints';
import { getProjectToken } from '@/lib/apiAuth';
import { listFdeProjectFiles, type FdeProjectFile } from '@/lib/fdeApi';
import { FDEProjectPicker } from './FDEProjectPicker';

interface FDEUploadDocsPanelProps {
  selectedProjectId: string | null;
  onSelectProject: (projectId: string) => void;
  onOpenSettings: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FDEUploadDocsPanel({ selectedProjectId, onSelectProject, onOpenSettings }: FDEUploadDocsPanelProps) {
  const [files, setFiles] = useState<FdeProjectFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);

  const refreshFiles = (projectId: string) => {
    setFilesLoading(true);
    setFilesError(null);
    listFdeProjectFiles(projectId)
      .then(setFiles)
      .catch((err: unknown) => setFilesError(err instanceof Error ? err.message : 'Failed to load files'))
      .finally(() => setFilesLoading(false));
  };

  useEffect(() => {
    if (selectedProjectId) {
      refreshFiles(selectedProjectId);
    } else {
      setFiles([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId]);

  // Recreated whenever the project changes -- the upload endpoint and every
  // fresh per-file token are both project-scoped, so a stale Uppy instance
  // from a previously-selected project must never be reused.
  const uppy = useMemo(() => {
    if (!selectedProjectId) return null;
    const instance = new Uppy({
      restrictions: { allowedFileTypes: null }, // "any file type" per spec -- no fixed schema
      autoProceed: false,
    });
    instance.use(XHRUpload, {
      endpoint: `${FDE_UPLOAD_URL}/api/fde/projects/${encodeURIComponent(selectedProjectId)}/upload`,
      fieldName: 'file',
      bundle: false,
      // A fresh project-scoped JWT (60s TTL) fetched right before EACH
      // individual request fires -- not a single token captured once for
      // the whole Dashboard session, since a multi-file batch could easily
      // outlive 60s for later files otherwise. onBeforeRequest (unlike the
      // synchronous `headers` option) supports an async callback.
      onBeforeRequest: async (xhr) => {
        const token = await getProjectToken(selectedProjectId);
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      },
    });
    instance.on('complete', () => {
      refreshFiles(selectedProjectId);
    });
    return instance;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId]);

  useEffect(() => {
    return () => {
      uppy?.destroy();
    };
  }, [uppy]);

  if (!selectedProjectId || !uppy) {
    return <FDEProjectPicker onSelectProject={onSelectProject} onOpenSettings={onOpenSettings} />;
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-6">
      <div>
        <h2 className="text-sm font-bold text-foreground">Upload Docs</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Project <span className="font-mono text-foreground">{selectedProjectId}</span> — any file type,
          zip archives are auto-extracted.
        </p>
      </div>

      <Dashboard uppy={uppy} height={320} width="100%" proudlyDisplayPoweredByUppy={false} />

      <div className="rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-2.5">
          <p className="text-xs font-semibold text-foreground">Already uploaded</p>
        </div>
        <div className="max-h-64 overflow-y-auto">
          {filesLoading && <p className="px-4 py-3 text-xs text-muted-foreground">Loading…</p>}
          {filesError && (
            <p className="px-4 py-3 text-xs text-destructive">{filesError}</p>
          )}
          {!filesLoading && !filesError && files.length === 0 && (
            <p className="px-4 py-3 text-xs text-muted-foreground">No files uploaded yet.</p>
          )}
          {files.map((f) => (
            <div
              key={f.file_id}
              className="flex items-center gap-2.5 border-b border-border/60 px-4 py-2 last:border-0"
            >
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-xs text-foreground">{f.original_filename}</span>
              {f.extracted_from_file_id !== null && (
                <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  from zip
                </span>
              )}
              <span className="shrink-0 text-[10px] text-muted-foreground">{formatBytes(f.file_size_bytes)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
