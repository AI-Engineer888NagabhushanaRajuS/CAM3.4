import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

const editorSpies = vi.hoisted(() => ({ jumpTo: vi.fn(), format: vi.fn() }));

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}`, PYTHON_BRIDGE_URL: 'http://bridge' }));
vi.mock('@/components/ui/ThemeToggle', () => ({ ThemeToggle: () => null }));
vi.mock('@/components/manifests/ManifestEditor', async () => {
  const React = await import('react');
  type P = { value: string; readOnly: boolean; language?: string; onChange: (t: string) => void };
  return {
    ManifestEditor: React.forwardRef<unknown, P>(function Fake(p, ref) {
      React.useImperativeHandle(ref, () => editorSpies);
      return <textarea aria-label={p.language === 'python' ? 'generated editor' : 'editor'} value={p.value} readOnly={p.readOnly} onChange={(e) => p.onChange(e.target.value)} />;
    }),
  };
});

import { ManifestsPage } from '@/pages/Manifests';

const SKILL = '{\n  "a": 1,\n  "skills": [\n    { "id": "x" }\n  ]\n}';
const TREE = {
  agent: {
    path: 'agent/agent_manifest.json', id: 'agent', name: 'CAM Agent', version: '1.5.0', status: 'draft', hash: 'sha256:aaaa', skills: [
      { path: 'skills/skill_01.json', id: 's1', name: 'Input Standardization', sequence: 1, version: '1.0.0', status: 'draft', hash: 'sha256:b1', subSkills: [
        { id: 'u1', name: 'Parse BOM', type: 'tool', stepCount: 3 }, { id: 'u2', name: 'Normalise', type: 'tool', stepCount: 2 },
      ] },
    ],
  },
  reporting: null, approved: [], runtime: [],
};
const FILE = {
  path: 'skills/skill_01.json', kind: 'skill', text: SKILL, hash: 'sha256:b1b1b1b1b1b1', version: '1.0.0', status: 'draft', readOnly: false,
  validation: { ok: true, errors: [] },
};
const CODE = {
  ok: true, files: { 'tools/parse_bom.py': 'def run():\n    return 1\n' }, bundle_sha256: 'abcdef0123456789abcdef', findings: [],
  repairs: ['renamed step "a b" to a_b'], ast: { ok: true, errors: [] },
};

let codegen: () => { status: number; body: unknown };
let lint: () => { status: number; body: unknown };
let fetchMock: ReturnType<typeof vi.fn>;
const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
const bridgeCalls = (path: string) => fetchMock.mock.calls.filter(([u]) => String(u) === `http://bridge${path}`);

beforeEach(() => {
  editorSpies.jumpTo.mockReset();
  codegen = () => ({ status: 200, body: CODE });
  lint = () => ({ status: 200, body: { ok: true, findings: [] } });
  fetchMock = vi.fn(async (url: string) => {
    const u = String(url);
    if (u === 'http://bridge/auth/token') return reply(200, { token: 'bridge-tok' });
    if (u === 'http://bridge/api/manifests/codegen') { const r = codegen(); return reply(r.status, r.body); }
    if (u === 'http://bridge/api/manifests/lint') { const r = lint(); return reply(r.status, r.body); }
    const p = new URL(u).pathname;
    if (p === '/api/manifests') return reply(200, { tree: TREE });
    if (p.startsWith('/api/manifests/schema/')) return reply(200, {});
    if (p === '/api/manifests/file') return reply(200, FILE);
    return reply(404, {});
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function open() {
  const router = createMemoryRouter([{ path: '/manifests', element: <ManifestsPage /> }], { initialEntries: ['/manifests?path=skills/skill_01.json'] });
  render(<RouterProvider router={router} />);
  await waitFor(() => expect((screen.getByLabelText('editor') as HTMLTextAreaElement).value).toBe(SKILL));
}
const tab = (name: RegExp) => fireEvent.click(screen.getByRole('tab', { name }));
const jsonBox = () => screen.getByLabelText('editor') as HTMLTextAreaElement;

describe('Manifests preview: generated tool', () => {
  it('shows the generated file, short bundle hash, AST gate result, repairs in words and the honest label', async () => {
    await open();
    tab(/Generated tool/);
    const code = await screen.findByLabelText('generated editor');
    await waitFor(() => expect((code as HTMLTextAreaElement).value).toBe(CODE.files['tools/parse_bom.py']));
    expect(screen.getByText('tools/parse_bom.py')).toBeTruthy();
    expect(screen.getByText('abcdef01...')).toBeTruthy();
    expect(screen.getByText(/AST gate: passed/)).toBeTruthy();
    expect(screen.getByText('renamed step "a b" to a_b')).toBeTruthy();
    expect(screen.getByText('Preview only: nothing is executed or deployed (SPEC-020).')).toBeTruthy();
    expect((code as HTMLTextAreaElement).readOnly).toBe(true);
    // the bridge is called with the fixed MANIFESTS scope token and the editor text
    const tokenCall = bridgeCalls('/auth/token')[0][1] as RequestInit;
    expect(JSON.parse(String(tokenCall.body))).toEqual({ rfq_id: 'MANIFESTS' });
    const call = bridgeCalls('/api/manifests/codegen')[0][1] as RequestInit;
    expect((call.headers as Record<string, string>).Authorization).toBe('Bearer bridge-tok');
    expect(JSON.parse(String(call.body))).toEqual({ text: SKILL });
  });

  it('sends the chosen sub-skill id', async () => {
    await open();
    tab(/Generated tool/);
    fireEvent.change(await screen.findByLabelText('Sub-skill'), { target: { value: 'u2' } });
    await waitFor(() => expect(bridgeCalls('/api/manifests/codegen').some(([, i]) => JSON.parse(String((i as RequestInit).body)).sub_skill_id === 'u2')).toBe(true));
  });

  it('debounces: rapid edits trigger one refresh with the last text', async () => {
    await open();
    await waitFor(() => expect(bridgeCalls('/api/manifests/codegen')).toHaveLength(1));
    for (const v of ['{"a":1}', '{"a":12}', '{"a":123}']) fireEvent.change(jsonBox(), { target: { value: v } });
    await new Promise((r) => setTimeout(r, 300));
    expect(bridgeCalls('/api/manifests/codegen')).toHaveLength(1); // still waiting
    await waitFor(() => expect(bridgeCalls('/api/manifests/codegen')).toHaveLength(2), { timeout: 2000 });
    expect(JSON.parse(String((bridgeCalls('/api/manifests/codegen')[1][1] as RequestInit).body)).text).toBe('{"a":123}');
    expect(bridgeCalls('/api/manifests/lint')).toHaveLength(2);
  });

  it('invalid JSON is shown calmly with no request and no alert', async () => {
    await open();
    await waitFor(() => expect(bridgeCalls('/api/manifests/codegen')).toHaveLength(1));
    tab(/Generated tool/);
    fireEvent.change(jsonBox(), { target: { value: '{ "a": ' } });
    expect((await screen.findByText(/Invalid JSON: fix the syntax/)).getAttribute('role')).toBe('status');
    await new Promise((r) => setTimeout(r, 800));
    expect(bridgeCalls('/api/manifests/codegen')).toHaveLength(1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('a 400 from the bridge is also shown as invalid JSON, not as an error', async () => {
    codegen = () => ({ status: 400, body: { detail: 'Expecting value: line 1' } });
    await open();
    tab(/Generated tool/);
    expect((await screen.findByText(/Invalid JSON: fix the syntax/)).textContent).toContain('Expecting value: line 1');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows the AST error lines when the generated code does not parse', async () => {
    codegen = () => ({ status: 200, body: { ...CODE, ast: { ok: false, errors: [{ line: 7, message: 'invalid syntax' }] } } });
    await open();
    tab(/Generated tool/);
    expect(await screen.findByText(/AST gate: failed on 1 line/)).toBeTruthy();
    expect(screen.getByText('line 7: invalid syntax')).toBeTruthy();
  });
});

describe('Manifests preview: lint', () => {
  it('lists errors before warnings and a click jumps to the JSON line', async () => {
    lint = () => ({ status: 200, body: { ok: false, findings: [
      { level: 'warning', path: '/a', message: 'prefer a longer name' },
      { level: 'error', path: '/skills/0/id', message: 'id is reserved' },
    ] } });
    await open();
    await waitFor(() => expect(screen.getByRole('tab', { name: /Lint \(2\)/ })).toBeTruthy());
    tab(/Lint/);
    const items = await screen.findAllByRole('button', { name: /at \// });
    expect(items[0].getAttribute('aria-label')).toBe('error at /skills/0/id: id is reserved');
    expect(items[1].getAttribute('aria-label')).toContain('warning');
    fireEvent.click(items[0]);
    await waitFor(() => expect(editorSpies.jumpTo).toHaveBeenCalledWith(4, expect.any(Number)));
    expect(screen.getByRole('tab', { name: /JSON/ }).getAttribute('aria-selected')).toBe('true');
  });
});
