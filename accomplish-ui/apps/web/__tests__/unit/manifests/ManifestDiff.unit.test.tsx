import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/lib/session', () => ({ getSessionToken: () => 'tok', getSession: () => null, clearSession: vi.fn() }));
vi.mock('@/config/endpoints', () => ({ backendUrl: (p: string) => `http://daemon${p}` }));
const diffProps = vi.hoisted(() => ({ last: null as null | { original: string; modified: string } }));
vi.mock('@monaco-editor/react', async () => {
  const React = await import('react');
  return {
    DiffEditor: (p: { original: string; modified: string; onMount?: (ed: unknown) => void }) => {
      diffProps.last = { original: p.original, modified: p.modified };
      React.useEffect(() => {
        // a fake editor: one modified line, one added line
        p.onMount?.({ onDidUpdateDiff: () => ({ dispose() {} }), getLineChanges: () => [
          { originalStartLineNumber: 2, originalEndLineNumber: 2, modifiedStartLineNumber: 2, modifiedEndLineNumber: 2 },
          { originalStartLineNumber: 5, originalEndLineNumber: 0, modifiedStartLineNumber: 6, modifiedEndLineNumber: 7 },
        ] });
      }, []); // eslint-disable-line react-hooks/exhaustive-deps
      return <pre data-testid="diff-editor">{p.original} {'->'} {p.modified}</pre>;
    },
  };
});
vi.mock('@/components/manifests/monacoSetup', () => ({ modelPath: (p: string) => `inmemory://${p}` }));

import { ChangesView } from '@/components/manifests/ChangesView';
import { comparable, normalizeJson, pickBaseline, summarizeLineChanges } from '@/lib/manifestDiff';

describe('manifestDiff rules', () => {
  it('counts added, removed and modified lines from the hunks', () => {
    expect(summarizeLineChanges([
      { originalStartLineNumber: 1, originalEndLineNumber: 0, modifiedStartLineNumber: 1, modifiedEndLineNumber: 3 }, // 3 added
      { originalStartLineNumber: 4, originalEndLineNumber: 5, modifiedStartLineNumber: 6, modifiedEndLineNumber: 0 }, // 2 removed
      { originalStartLineNumber: 9, originalEndLineNumber: 9, modifiedStartLineNumber: 10, modifiedEndLineNumber: 11 }, // 2 modified
    ])).toEqual({ added: 3, removed: 2, modified: 2 });
    expect(summarizeLineChanges(null)).toEqual({ added: 0, removed: 0, modified: 0 });
  });

  it('compares on one JSON layout when both sides are JSON, raw otherwise', () => {
    const base = '{"a":1,"b":[1,2]}';
    const now = '{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}\n';
    const c = comparable(base, now);
    expect(c.normalized).toBe(true);
    expect(c.base).toBe(c.now); // same data, different layout: no change at all
    expect(comparable('{"a":1}', '{"a":').normalized).toBe(false);
    expect(normalizeJson('not json')).toBeNull();
  });

  it('never invents an earlier version', () => {
    expect(pickBaseline('saved', 'S', null)).toEqual({ kind: 'diff', label: 'saved on disk', base: 'S' });
    expect(pickBaseline('previous', 'S', null)).toMatchObject({ kind: 'none', reason: expect.stringContaining('no earlier saved version') });
    expect(pickBaseline('previous', 'S', 'loading').kind).toBe('none');
    expect(pickBaseline('previous', 'S', 'error')).toMatchObject({ kind: 'none', reason: expect.stringContaining('could not be loaded') });
    expect(pickBaseline('previous', 'S', { text: 'OLD', savedAt: '2026-11-06T10:00:00.000Z' })).toMatchObject({ kind: 'diff', base: 'OLD' });
  });
});

const answer = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => body }) as Response;
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  diffProps.last = null;
  fetchMock = vi.fn(async (url: string) => {
    if (url.includes('/history/file')) return answer({ stamp: '20261105T100000000Z', savedAt: '2026-11-05T10:00:00.000Z', text: '{"a":0}', hash: 'h', version: '1.0.0' });
    return answer({ path: 'skills/s.json', versions: [{ stamp: '20261105T100000000Z', savedAt: '2026-11-05T10:00:00.000Z' }] });
  });
  vi.stubGlobal('fetch', fetchMock);
});

describe('ChangesView', () => {
  it('says there are no unsaved changes when the editor matches the disk, and offers no diff', async () => {
    render(<ChangesView path="skills/s.json" current={'{"a":1}'} saved={'{"a":1}'} />);
    expect(await screen.findByText(/No unsaved changes/)).toBeTruthy();
    expect(screen.queryByTestId('diff-editor')).toBeNull();
  });

  it('shows the diff against the disk copy with the colour key and the counts', async () => {
    render(<ChangesView path="skills/s.json" current={'{"a":2}'} saved={'{"a":1}'} />);
    expect(await screen.findByTestId('diff-editor')).toBeTruthy();
    expect(screen.getByLabelText('Colour key').textContent).toMatch(/Added.*Removed.*Modified/);
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('3 changed lines: 2 added · 0 removed · 1 modified'));
    expect(diffProps.last?.original).toContain('"a": 1');
  });

  it('compares with the previous saved version on request, ignoring layout, and says so', async () => {
    render(<ChangesView path="skills/s.json" current={'{"a":0}'} saved={'{"a":0}'} />);
    await screen.findByText(/No unsaved changes/);
    fireEvent.click(screen.getByRole('button', { name: 'Previous saved version' }));
    // previous text is {"a":0} too: identical on the same layout -> nothing differs, no fake diff
    expect(await screen.findByText(/matches the previous saved version/)).toBeTruthy();
    expect(fetchMock.mock.calls.map((c) => String(c[0])).join('\n')).toContain('/api/manifests/history?path=skills%2Fs.json');
  });

  it('shows the layout note when the previous version differs in data', async () => {
    render(<ChangesView path="skills/s.json" current={'{"a": 5}'} saved={'{"a": 5}'} />);
    fireEvent.click(screen.getByRole('button', { name: 'Previous saved version' }));
    expect(await screen.findByTestId('diff-editor')).toBeTruthy();
    expect(screen.getByText(/spacing and line breaks are ignored/)).toBeTruthy();
  });

  it('with no earlier saved version it says nothing can be compared', async () => {
    fetchMock.mockImplementation(async () => answer({ path: 'skills/s.json', versions: [] }));
    render(<ChangesView path="skills/s.json" current={'{"a":1}'} saved={'{"a":1}'} />);
    fireEvent.click(screen.getByRole('button', { name: 'Previous saved version' }));
    expect(await screen.findByText(/no earlier saved version yet/)).toBeTruthy();
    expect(screen.queryByTestId('diff-editor')).toBeNull();
  });
});
