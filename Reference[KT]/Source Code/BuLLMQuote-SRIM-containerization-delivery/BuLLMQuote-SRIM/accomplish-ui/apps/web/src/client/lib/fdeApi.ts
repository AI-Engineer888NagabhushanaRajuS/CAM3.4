/**
 * Typed wrappers over the FDE Staging Pipeline's backend endpoints
 * (fastmcp-router/upload_server.py, ENABLE_FDE_ROUTES-gated). Direct HTTP
 * calls via authFetchFde -- NOT the window.accomplish.* Electron/daemon IPC
 * pattern ProjectTrackingPanel.tsx uses, since this backend lives in the
 * same fastmcp-router HTTP process space as production's own upload
 * endpoints (see RfqIntakeUploadModal.tsx/RfqCreateForm.tsx for the
 * equivalent RFQ-side pattern this mirrors).
 */

import { FDE_UPLOAD_URL } from '../config/endpoints';
import { authFetchFde } from './apiAuth';

export interface FdeProject {
  project_id: string;
  project_name: string;
  description: string | null;
  created_at: string;
}

export interface FdeProjectFile {
  file_id: number;
  original_filename: string;
  file_extension: string;
  file_size_bytes: number;
  uploaded_at: string;
  extracted_from_file_id: number | null;
  scan_status: string;
}

// No real project_id exists yet for create/list -- the server-side
// verify_token_any_project dependency never checks this value against
// anything, it just needs a validly-signed token minted somehow.
const NO_PROJECT_PLACEHOLDER = 'new';

export async function listFdeProjects(): Promise<FdeProject[]> {
  const res = await authFetchFde(`${FDE_UPLOAD_URL}/api/fde/projects`, NO_PROJECT_PLACEHOLDER);
  if (!res.ok) {
    throw new Error(`Failed to list FDE projects: HTTP ${res.status}`);
  }
  return (await res.json()) as FdeProject[];
}

export async function createFdeProject(projectName: string, description?: string): Promise<FdeProject> {
  const res = await authFetchFde(`${FDE_UPLOAD_URL}/api/fde/projects`, NO_PROJECT_PLACEHOLDER, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_name: projectName, description: description ?? null }),
  });
  if (!res.ok) {
    throw new Error(`Failed to create FDE project: HTTP ${res.status}`);
  }
  return (await res.json()) as FdeProject;
}

export async function listFdeProjectFiles(projectId: string): Promise<FdeProjectFile[]> {
  const res = await authFetchFde(`${FDE_UPLOAD_URL}/api/fde/projects/${encodeURIComponent(projectId)}/files`, projectId);
  if (!res.ok) {
    throw new Error(`Failed to list files for FDE project ${projectId}: HTTP ${res.status}`);
  }
  return (await res.json()) as FdeProjectFile[];
}

// Uppy's XHRUpload plugin handles the actual upload POST directly (endpoint
// + a fresh per-file Authorization header configured on the Uppy instance
// itself, see FDEUploadDocsPanel.tsx) -- no wrapper needed here for that
// specific call.
