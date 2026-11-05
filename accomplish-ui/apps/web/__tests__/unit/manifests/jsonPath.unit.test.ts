import { describe, it, expect } from 'vitest';
import { offsetForPath, positionAt, splitJsonPath } from '@/components/manifests/jsonPath';

const TEXT = '{\n  "a": 1,\n  "skills": [\n    { "id": "x", "steps": [] }\n  ]\n}';

describe('manifest JSON path -> editor position', () => {
  it('splits pointer, dotted and bracket paths the same way', () => {
    expect(splitJsonPath('/skills/0/id')).toEqual(['skills', '0', 'id']);
    expect(splitJsonPath('$.skills[0].id')).toEqual(['skills', '0', 'id']);
    expect(splitJsonPath('skills.0.id')).toEqual(['skills', '0', 'id']);
  });

  it('finds the line of the offending value', () => {
    for (const p of ['/skills/0/id', '$.skills[0].id', 'skills.0.id']) {
      expect(positionAt(TEXT, offsetForPath(TEXT, p)).line).toBe(4);
    }
    expect(positionAt(TEXT, offsetForPath(TEXT, '/a'))).toEqual({ line: 2, column: 8 });
  });

  it('falls back to the nearest existing ancestor, then the top of the file', () => {
    expect(positionAt(TEXT, offsetForPath(TEXT, '/skills/0/missing')).line).toBe(4);
    expect(offsetForPath(TEXT, '/nope/deeper')).toBe(0);
    expect(offsetForPath('{ not json', '/a')).toBe(0);
  });
});
