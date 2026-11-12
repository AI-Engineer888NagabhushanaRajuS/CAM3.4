"""Read-only, cell-level storage evidence. Never a calculation fallback.

An explicit cached-empty-string is a snapshot, not a correctness/freshness claim.
No package fetching, cache editing, engine imports, or generic None conversion.
Only transitional SpreadsheetML in scope; other namespaces fail closed.
"""
from dataclasses import dataclass
import re
import xml.etree.ElementTree as E
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
Q='{'+NS+'}'
@dataclass(frozen=True)
class EmptyCacheEvidence:
    known: bool
    value: object
    reason: str

def explicit_empty_formula_cache(cell):
    def unknown(reason):return EmptyCacheEvidence(False,None,reason)
    if cell.tag != Q+'c':return unknown('unsupported-cell-namespace')
    coord=cell.get('r','')
    m=re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]*)',coord)
    if not m:return unknown('invalid-coordinate')
    col=0
    for c in m[1]:col=col*26+ord(c)-64
    if col>16384 or int(m[2])>1048576:return unknown('out-of-bounds-coordinate')
    fs=cell.findall(Q+'f');vs=cell.findall(Q+'v')
    if len(fs)!=1:return unknown('missing-or-duplicate-formula')
    if cell.get('t')!='str':return unknown('not-explicit-string-type')
    if len(vs)!=1:return unknown('missing-or-duplicate-value')
    if cell.find(Q+'is') is not None:return unknown('conflicting-inline-string')
    v=vs[0]
    if list(v) or v.attrib:return unknown('unsupported-value-structure')
    if v.text not in (None,''):return unknown('nonempty-string-value')
    return EmptyCacheEvidence(True,'','explicit-string-formula-present-empty-value')
