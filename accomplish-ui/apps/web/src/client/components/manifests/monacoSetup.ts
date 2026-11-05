/**
 * Monaco bundled locally by Vite: no CDN, no network. Importing this module once wires the loader and the two
 * workers (editor core + JSON language service). Kept apart so unit tests can mock it.
 */
import * as monaco from 'monaco-editor';
import { loader } from '@monaco-editor/react';
import EditorWorker from 'monaco-editor/editor/editor.worker?worker';
import JsonWorker from 'monaco-editor/language/json/json.worker?worker';

(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorker: (_id: string, label: string) => (label === 'json' ? new JsonWorker() : new EditorWorker()),
};
loader.config({ monaco });

export { monaco };

const schemas = new Map<string, { uri: string; fileMatch: string[]; schema: object }>();

/** Model path for a manifest file; the JSON schema is matched to it by URI. */
export const modelPath = (path: string) => `inmemory://cam-manifests/${path}`;

/** Validation + completion for one file's model (monaco 0.57 exposes the JSON defaults as `monaco.json`). */
export function registerSchema(path: string, kind: string, schema: object): void {
  schemas.set(path, { uri: `cam-schema://${kind}/${path}`, fileMatch: [monaco.Uri.parse(modelPath(path)).toString()], schema });
  monaco.json.jsonDefaults.setDiagnosticsOptions({
    validate: true, allowComments: false, enableSchemaRequest: false, schemaValidation: 'error', schemas: [...schemas.values()],
  });
}
