/** Read-only security telemetry from the Python bridge. Not RFQ-bound, so the token uses the fixed scope id 'SECURITY'. */
import { PYTHON_BRIDGE_URL } from '../config/endpoints';
import { authFetch } from './apiAuth';

export const SECURITY_SCOPE = 'SECURITY';

export interface TelemetryEngine { id: 'clamav' | 'repel'; label: string; status: 'ok' | 'unavailable'; detail: string; signatures: number | null }
export interface Decision { time: string; scope: string; name: string; decision: 'released' | 'quarantined' | 'error'; reason: string; clamav: string | null; repel: string | null }
export interface Telemetry {
  engines: TelemetryEngine[];
  counts: { released: number; quarantined: number; held: number; error: number };
  recent: Decision[];
  policy: { failClosed: boolean; maxFiles: number; maxFileBytes: number; maxTotalBytes: number };
}
export type MemoryStatus =
  | { available: true; writesEnabled: boolean; provider: 'ollama' | 'openrouter'; maxConcurrent: number; running: number; queued: number }
  | { available: false; reason: string };

async function get<T>(path: string): Promise<T> {
  const res = await authFetch(`${PYTHON_BRIDGE_URL}${path}`, SECURITY_SCOPE);
  if (!res.ok) throw new Error(`The security service answered HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const getTelemetry = () => get<Telemetry>('/api/security/telemetry');
export const getMemoryStatus = () => get<MemoryStatus>('/api/memory/status');
