import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import { modelPath, monaco, registerSchema } from './monacoSetup';

export interface EditorHandle {
  jumpTo: (line: number, column: number) => void;
  format: () => void;
}
interface Props {
  path: string;
  kind: string;
  schema: object | null;
  value: string;
  readOnly: boolean;
  onChange: (text: string) => void;
  onSave: () => void;
}

const isDark = () => document.documentElement.classList.contains('dark');

export const ManifestEditor = forwardRef<EditorHandle, Props>(function ManifestEditor({ path, kind, schema, value, readOnly, onChange, onSave }, ref) {
  const editor = useRef<Parameters<OnMount>[0] | null>(null);
  const save = useRef(onSave);
  save.current = onSave;
  const [dark, setDark] = useState(isDark);

  useEffect(() => {
    const obs = new MutationObserver(() => setDark(isDark()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => obs.disconnect();
  }, []);

  useEffect(() => { if (schema) registerSchema(path, kind, schema); }, [path, kind, schema]);

  useImperativeHandle(ref, () => ({
    jumpTo: (line, column) => {
      const ed = editor.current;
      if (!ed) return;
      ed.setPosition({ lineNumber: line, column });
      ed.revealLineInCenter(line);
      ed.focus();
    },
    format: () => { void editor.current?.getAction('editor.action.formatDocument')?.run(); },
  }), []);

  return (
    <Editor
      height="100%"
      language="json"
      path={modelPath(path)}
      value={value}
      theme={dark ? 'vs-dark' : 'light'}
      loading={<p className="p-4 text-sm text-muted-foreground">Loading editor...</p>}
      onChange={(v) => onChange(v ?? '')}
      onMount={(ed) => {
        editor.current = ed;
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => save.current());
      }}
      options={{
        readOnly, tabSize: 2, insertSpaces: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false,
        automaticLayout: true, wordWrap: 'on', ariaLabel: `JSON manifest editor: ${path}`, formatOnPaste: false,
        domReadOnly: readOnly, fixedOverflowWidgets: true,
      }}
    />
  );
});
