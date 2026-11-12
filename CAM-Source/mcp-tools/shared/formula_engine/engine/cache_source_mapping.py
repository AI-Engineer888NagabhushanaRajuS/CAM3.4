"""Audit-only transitional XLSX mapping. Fail closed, no external retrieval.

Not an evaluator or universal OPC/OOXML resolver. Only xl/workbook.xml and
internal worksheet relationships are supported. Caller must bind the raw formula
and sheet/coordinate to its separately loaded model before using evidence.
"""
from dataclasses import dataclass
from pathlib import PurePosixPath
import posixpath,zipfile,xml.etree.ElementTree as E
from raw_cache_provenance import explicit_empty_formula_cache,Q,NS
import re
from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import range_boundaries,coordinate_to_tuple
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
@dataclass(frozen=True)
class FormulaCacheSource:
    sheet: str
    cell: str
    part: str
    formula: object
    empty_string_snapshot: bool

def read_sources(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate-zip-entry')
        wb=E.fromstring(z.read('xl/workbook.xml'))
        if wb.tag!=Q+'workbook':raise ValueError('unsupported-workbook-namespace')
        relroot=E.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        if relroot.tag!='{'+P+'}Relationships':raise ValueError('unsupported-relationships-namespace')
        rels={}
        for rel in relroot:
            if rel.tag!='{'+P+'}Relationship':raise ValueError('unsupported-relationship-element')
            rid=rel.get('Id')
            if not rid or rid in rels:raise ValueError('missing-or-duplicate-relationship-id')
            rels[rid]=rel
        sheets=wb.findall(Q+'sheets')
        if len(sheets)!=1:raise ValueError('missing-or-duplicate-sheets')
        seen_names=set();seen_parts=set();out={}
        for s in sheets[0]:
            if s.tag!=Q+'sheet':raise ValueError('unsupported-sheet-element')
            title=s.get('name','');key=title.lower()
            if not title or key in seen_names:raise ValueError('missing-or-duplicate-sheet-name')
            seen_names.add(key);rel=rels.get(s.get('{'+R+'}id'))
            if rel is None:raise ValueError('missing-sheet-relationship')
            if rel.get('Type')!=R+'/worksheet' or rel.get('TargetMode','Internal')!='Internal':raise ValueError('unsupported-sheet-relationship')
            target=rel.get('Target','')
            if not target or any(c in target for c in [':','\\','?','#','%']):raise ValueError('unsupported-target')
            part=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not part.startswith('xl/worksheets/') or '..' in PurePosixPath(part).parts or not part.endswith('.xml'):raise ValueError('unsupported-target-part')
            if part in seen_parts:raise ValueError('duplicate-sheet-part')
            seen_parts.add(part);root=E.fromstring(z.read(part))
            if root.tag!=Q+'worksheet':raise ValueError('unsupported-worksheet-namespace')
            data=root.findall(Q+'sheetData')
            if len(data)!=1:raise ValueError('missing-or-duplicate-sheetData')
            masters={}
            for master_row in data[0].findall(Q+'row'):
                for fc in master_row.findall(Q+'c'):
                    ff=fc.findall(Q+'f')
                    if len(ff)==1 and ff[0].get('t')=='shared' and ff[0].text:
                        origin=fc.get('r','')
                        m=re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]*)',origin)
                        # Keep invalid entries as poison, so they cannot become an
                        # eligible master or hide a duplicate shared-group master.
                        valid=m is not None and master_row.get('r')==m[2]
                        if valid:
                            rr,cc=coordinate_to_tuple(origin)
                            valid=1<=rr<=1048576 and 1<=cc<=16384
                        masters.setdefault(ff[0].get('si'),[]).append((origin,ff[0],valid))
            cells={}
            for row in data[0].findall(Q+'row'):
                for c in row.findall(Q+'c'):
                    coord=c.get('r','')
                    if coord in cells:raise ValueError('duplicate-cell-coordinate')
                    cells[coord]=True
                    fs=c.findall(Q+'f')
                    if not fs:continue
                    evidence=explicit_empty_formula_cache(c)
                    # Also bind row identity before recording an empty snapshot.
                    m=re.search(r'([0-9]+)$',coord)
                    row_ok=m is not None and row.get('r')==m[1]
                    formula=_bound_formula(fs,coord,masters)
                    out[(key,coord)]=FormulaCacheSource(title,coord,part,formula,evidence.known and row_ok)
        return out

def bound_empty_snapshot(sources,sheet,coord,model_formula):
    record=sources.get((sheet.lower(),coord))
    # Formula expansion is guarded by source master identity and declared range.
    if not record or not record.formula:return False
    return record.empty_string_snapshot and record.formula==model_formula.removeprefix('=')


def _bound_formula(fs,coord,masters):
    if len(fs)!=1:return None
    f=fs[0]
    if f.get('t')!='shared':return f.text
    si=f.get('si','')
    if not re.fullmatch(r'(0|[1-9][0-9]*)',si):return None
    group=masters.get(si,[])
    if len(group)!=1:return None
    origin,master,master_eligible=group[0]
    if not master_eligible:return None
    ref=master.get('ref','')
    if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]*:[A-Z]{1,3}[1-9][0-9]*|[A-Z]{1,3}[1-9][0-9]*',ref):return None
    try:
        c1,r1,c2,r2=range_boundaries(ref)
        rr,cc=coordinate_to_tuple(coord);mr,mc=coordinate_to_tuple(origin)
        if not(1<=c1<=c2<=16384 and 1<=r1<=r2<=1048576):return None
        if not(c1<=cc<=c2 and r1<=rr<=r2 and c1<=mc<=c2 and r1<=mr<=r2):return None
        if f is not master and (f.text is not None or f.get('ref') is not None):return None
        return master.text if f is master else Translator('='+master.text,origin=origin).translate_formula(coord).removeprefix('=')
    except (ValueError,TypeError,KeyError,IndexError):return None
