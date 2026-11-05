import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

const editorSpies = vi.hoisted(() => ({ jumpTo: vi.fn(), format: vi.fn() }));

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}`, PYTHON_BRIDGE_URL: 'http://bridge' }));
vi.mock('@/components/ui/ThemeToggle', () => ({ ThemeToggle: () => null }));
// Monaco does not run in jsdom: a textarea with the same props and handle stands in for it.
vi.mock('@/components/manifests/ManifestEditor', async () => {
  const React = await import('react');
  type P = { value: string; readOnly: boolean; onChange: (t: string) => void };
  return {
    ManifestEditor: React.forwardRef<unknown, P>(function Fake(p, ref) {
      React.useImperativeHandle(ref, () => editorSpies);
      return <textarea aria-label="editor" value={p.value} readOnly={p.readOnly} onChange={(e) => p.onChange(e.target.value)} />;
    }),
  };
});

import { ManifestsPage } from '@/pages/Manifests';

const SKILL = '{\n  "a": 1,\n  "skills": [\n    { "id": "x" }\n  ]\n}';
const TREE = {
  agent: {
    path: 'agent/agent_manifest.json', id: 'agent', name: 'CAM Agent', version: '1.5.0', status: 'draft', hash: 'sha256:aaaa', skills: [
      { path: 'skills/skill_02.json', id: 's2', name: 'Feature Extraction', sequence: 2, version: '1.0.0', status: 'approved', hash: 'sha256:b2', subSkills: [] },
      { path: 'skills/skill_01.json', id: 's1', name: 'Input Standardization', sequence: 1, version: '1.0.0', status: 'draft', hash: 'sha256:b1', subSkills: [
        { id: 'u1', name: 'Parse BOM', type: 'tool', stepCount: 3 },
      ] },
    ],
  },
  reporting: { path: 'reporting/centum.json', id: 'r', name: 'Centum Reporting', version: '2.0.0', status: 'draft', hash: 'sha256:r', reportCount: 16 },
  approved: [{ path: 'repo-approved/a1.json', id: 'a1', name: 'As-built One', version: '1.4.0', active: true }],
  runtime: [{ path: 'centum_intake.json', id: 'ci', name: 'Centum Intake', version: '1', port: 8101, readOnly: true }],
};
const file = (over: Record<string, unknown> = {}) => ({
  path: 'skills/skill_01.json', kind: 'skill', text: SKILL, hash: 'sha256:b1b1b1b1b1b1', version: '1.0.0', status: 'draft', readOnly: false,
  validation: { ok: true, errors: [] }, ...over,
});

let files: Record<string, unknown>;
let put: (body: { path: string; text: string; baseHash: string }) => { status: number; body: unknown };
let fetchMock: ReturnType<typeof vi.fn>;
const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;

beforeEach(() => {
  editorSpies.jumpTo.mockReset();
  files = {
    'skills/skill_01.json': file(),
    'centum_intake.json': file({ path: 'centum_intake.json', kind: 'approved', readOnly: true, status: 'approved' }),
  };
  put = () => ({ status: 500, body: {} });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url);
    if (init?.method === 'PUT') { const r = put(JSON.parse(String(init.body))); return reply(r.status, r.body); }
    if (u.pathname === '/api/manifests') return reply(200, { tree: TREE });
    if (u.pathname.startsWith('/api/manifests/schema/')) return reply(200, { type: 'object' });
    if (u.pathname === '/api/manifests/file') {
      const f = files[u.searchParams.get('path') ?? ''];
      return f ? reply(200, f) : reply(404, { error: 'not found' });
    }
    return reply(404, {});
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function renderAt(url = '/manifests') {
  const router = createMemoryRouter([{ path: '/manifests', element: <ManifestsPage /> }, { path: '*', element: <p>elsewhere</p> }], { initialEntries: [url] });
  render(<RouterProvider router={router} />);
  return router;
}
const editor = () => screen.getByLabelText('editor') as HTMLTextAreaElement;
const putCalls = () => fetchMock.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === 'PUT');
const saveButton = () => screen.getByRole('button', { name: /Save/ }) as HTMLButtonElement;

describe('Manifests page: tree', () => {
  it('renders agent > skills in sequence order with status badges and read-only sub-skills, then the other sections', async () => {
    renderAt();
    const tree = await screen.findByRole('tree');
    const items = within(tree).getAllByRole('treeitem');
    expect(items.map((i) => i.textContent)).toEqual([
      expect.stringContaining('CAM Agent'),
      expect.stringContaining('1. Input Standardization'),
      expect.stringContaining('2. Feature Extraction'),
      expect.stringContaining('Centum Reporting'),
      expect.stringContaining('As-built (approved)'),
      expect.stringContaining('Live routing manifests (read-only)'),
    ]);
    expect(items[1].textContent).toContain('DRAFT');
    expect(items[2].textContent).toContain('APPROVED');
    expect(items[1].textContent).toContain('v1.0.0');
    expect(screen.getByText(/Design input: saving versions the file; it does not yet change how a tool runs \(SPEC-020\)\./)).toBeTruthy();
    // sub-skills appear when the skill is expanded and cannot be selected
    fireEvent.keyDown(items[1], { key: 'ArrowRight' });
    const sub = screen.getByRole('treeitem', { name: /Parse BOM/ });
    expect(sub.getAttribute('aria-level')).toBe('3');
    expect(sub.getAttribute('aria-selected')).toBeNull();
    fireEvent.click(sub);
    expect(screen.getByText('Select a manifest on the left to view or edit it.')).toBeTruthy();
    // groups expand to list their files
    fireEvent.click(screen.getByRole('treeitem', { name: /As-built/ }));
    expect(screen.getByRole('treeitem', { name: /As-built One/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('treeitem', { name: /Live routing/ }));
    expect(screen.getByRole('treeitem', { name: /Centum Intake/ })).toBeTruthy();
  });

  it('is keyboard navigable: roving focus, arrows, Enter selects', async () => {
    renderAt();
    const tree = await screen.findByRole('tree');
    const first = within(tree).getAllByRole('treeitem')[0];
    expect(first.getAttribute('tabindex')).toBe('0');
    first.focus();
    fireEvent.keyDown(first, { key: 'ArrowDown' });
    const second = within(tree).getAllByRole('treeitem')[1];
    expect(document.activeElement).toBe(second);
    expect(second.getAttribute('tabindex')).toBe('0');
    expect(first.getAttribute('tabindex')).toBe('-1');
    fireEvent.keyDown(second, { key: 'ArrowRight' }); // expand the skill
    expect(second.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(second, { key: 'Enter' });
    await waitFor(() => expect(editor().value).toBe(SKILL));
  });

  it('says why the tree is empty when the daemon is unreachable', async () => {
    fetchMock.mockRejectedValue(new Error('down'));
    renderAt();
    expect((await screen.findAllByRole('alert'))[0].textContent).toContain('Could not reach the CAM daemon');
  });
});

describe('Manifests page: selecting and editing', () => {
  it('loads the selected file with the session token and shows version, status, short hash', async () => {
    renderAt();
    fireEvent.click(await screen.findByRole('treeitem', { name: /Input Standardization/ }));
    await waitFor(() => expect(editor().value).toBe(SKILL));
    const call = fetchMock.mock.calls.find(([u]) => String(u).includes('/api/manifests/file'))!;
    expect(String(call[0])).toContain('path=skills%2Fskill_01.json');
    expect(((call[1] as RequestInit).headers as Record<string, string>).Authorization).toBe('Bearer tok');
    const status = screen.getByLabelText('File status');
    expect(status.textContent).toContain('1.0.0');
    expect(status.textContent).toContain('b1b1b1b1...');
    expect(status.textContent).toContain('No unsaved changes');
  });

  it('tracks dirty state: Save and Revert enable on edit, Revert restores the text', async () => {
    renderAt('/manifests?path=skills/skill_01.json');
    await waitFor(() => expect(editor().value).toBe(SKILL));
    const revert = screen.getByRole('button', { name: /Revert/ }) as HTMLButtonElement;
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(editor(), { target: { value: SKILL + ' ' } });
    expect(screen.getByLabelText('File status').textContent).toContain('Unsaved changes');
    expect(saveButton().disabled).toBe(false);
    fireEvent.click(revert);
    expect(editor().value).toBe(SKILL);
    expect(screen.getByLabelText('File status').textContent).toContain('No unsaved changes');
  });

  it('asks before leaving a dirty file and stays when the user declines', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const router = renderAt('/manifests?path=skills/skill_01.json');
    await waitFor(() => expect(editor().value).toBe(SKILL));
    fireEvent.change(editor(), { target: { value: 'changed' } });
    fireEvent.click(screen.getByRole('treeitem', { name: /Centum Reporting/ }));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(router.state.location.search).toBe('?path=skills/skill_01.json');
    expect(editor().value).toBe('changed');
  });
});

describe('Manifests page: save', () => {
  it('200: sends baseHash, replaces the text with the server copy and says what changed', async () => {
    renderAt('/manifests?path=skills/skill_01.json');
    await waitFor(() => expect(editor().value).toBe(SKILL));
    put = (b) => ({ status: 200, body: { path: b.path, text: '{"saved":true}', hash: 'sha256:cdcdcdcdcdcd9999', version: '1.0.1', status: 'draft', validation: { ok: true, errors: [] } } });
    fireEvent.change(editor(), { target: { value: '{"x":1}' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(editor().value).toBe('{"saved":true}'));
    expect(screen.getByText('Saved: version 1.0.0 -> 1.0.1, hash cdcdcdcd...')).toBeTruthy();
    expect(JSON.parse(String((putCalls()[0][1] as RequestInit).body))).toEqual({ path: 'skills/skill_01.json', text: '{"x":1}', baseHash: 'sha256:b1b1b1b1b1b1' });
    expect(screen.getByLabelText('File status').textContent).toContain('1.0.1');
    // the tree is refreshed so the versions on the left follow
    const treeLoads = fetchMock.mock.calls.filter(([u, i]) => new URL(String(u)).pathname === '/api/manifests' && !(i as RequestInit | undefined)?.method);
    expect(treeLoads).toHaveLength(2);
  });

  it('400: shows the server errors, keeps the text, and clicking an error jumps to its line', async () => {
    renderAt('/manifests?path=skills/skill_01.json');
    await waitFor(() => expect(editor().value).toBe(SKILL));
    put = () => ({ status: 400, body: { validation: { ok: false, errors: [{ path: '/skills/0/id', message: 'must be a number' }] } } });
    fireEvent.change(editor(), { target: { value: SKILL + '\n' } });
    fireEvent.click(saveButton());
    const err = await screen.findByRole('button', { name: /must be a number/ });
    expect(screen.getByText(/Not saved: 1 problem/)).toBeTruthy();
    expect(editor().value).toBe(SKILL + '\n');
    fireEvent.click(err);
    expect(editorSpies.jumpTo).toHaveBeenCalledWith(4, expect.any(Number));
  });

  it('409: offers Reload / Keep mine; Keep mine saves against the new hash, Reload refetches', async () => {
    renderAt('/manifests?path=skills/skill_01.json');
    await waitFor(() => expect(editor().value).toBe(SKILL));
    put = () => ({ status: 409, body: { currentHash: 'sha256:newhash' } });
    fireEvent.change(editor(), { target: { value: 'mine' } });
    fireEvent.click(saveButton());
    expect((await screen.findByRole('alert')).textContent).toContain('changed on disk since you opened it');
    expect(editor().value).toBe('mine');

    fireEvent.click(screen.getByRole('button', { name: 'Keep mine' }));
    put = (b) => ({ status: 200, body: { path: b.path, text: b.text, hash: 'sha256:final0000000', version: '1.0.2', status: 'draft', validation: { ok: true, errors: [] } } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(putCalls()).toHaveLength(2));
    expect(JSON.parse(String((putCalls()[1][1] as RequestInit).body)).baseHash).toBe('sha256:newhash');

    put = () => ({ status: 409, body: { currentHash: 'sha256:again' } });
    fireEvent.change(editor(), { target: { value: 'mine again' } });
    fireEvent.click(saveButton());
    await screen.findByRole('button', { name: 'Reload' });
    files['skills/skill_01.json'] = file({ text: 'from disk', hash: 'sha256:again', version: '1.0.9' });
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await waitFor(() => expect(editor().value).toBe('from disk'));
  });

  it('403: explains the refusal and keeps the text', async () => {
    renderAt('/manifests?path=skills/skill_01.json');
    await waitFor(() => expect(editor().value).toBe(SKILL));
    put = () => ({ status: 403, body: {} });
    fireEvent.change(editor(), { target: { value: 'x' } });
    fireEvent.click(saveButton());
    expect((await screen.findByRole('alert')).textContent).toContain('needs an admin account');
    expect(editor().value).toBe('x');
  });
});

describe('Manifests page: read-only and deep link', () => {
  it('a live routing manifest is read-only with the plain explanation and no way to save', async () => {
    renderAt('/manifests?path=centum_intake.json');
    await waitFor(() => expect(editor().readOnly).toBe(true));
    expect(screen.getByText(/live routing manifest\. Change it with scripts\/import_manifest\.py/)).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
    expect((screen.getByRole('button', { name: /Format/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('#/manifests?path=... preselects the file in the tree and loads it', async () => {
    renderAt('/manifests?path=skills/skill_01.json');
    await waitFor(() => expect(editor().value).toBe(SKILL));
    expect(screen.getByRole('treeitem', { name: /Input Standardization/ }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('skills/skill_01.json');
  });
});
