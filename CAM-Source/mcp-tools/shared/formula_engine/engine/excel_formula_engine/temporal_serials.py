"""Read exact XLSX serials only for cells openpyxl converted to temporal objects.

The conversion can lose serial60, epoch offsets and sub-millisecond precision.
Never infer these original numbers by reversing a Python datetime.
"""
import datetime
from collections import Counter
import math
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

_TEMPORAL=(datetime.date,datetime.time,datetime.timedelta)
_MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def source_temporal_values(path, value_workbook):
    """Return exact numeric serials/ISO markers keyed by sheet and coordinate.

    Reads only worksheets containing temporal objects in the data-only view.
    Retains only requested coordinates, never copies other cell contents. Raises
    on missing source bindings so the caller can fail closed with diagnostics.
    Formula caches are source observations, not evaluation fallback authority.
    """
    # The workbook is already fully loaded by openpyxl; _cells avoids expanding
    # an inflated worksheet dimension just to identify occupied temporal cells.
    wanted={s.title:{c.coordinate for c in s._cells.values()
                    if isinstance(c.value,_TEMPORAL)} for s in value_workbook}
    wanted={s:coords for s,coords in wanted.items() if coords}
    if not wanted:return {}
    result={}
    with ZipFile(path) as archive:
        member_counts=Counter(archive.namelist())
        for member in ['xl/workbook.xml','xl/_rels/workbook.xml.rels']:
            if member_counts[member]!=1:raise ValueError('ambiguous workbook ZIP member')
        relationships=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets={};seen_ids=set()
        for relationship in relationships:
            rid=relationship.attrib['Id']
            if rid in seen_ids:raise ValueError('duplicate workbook relationship identity')
            seen_ids.add(rid)
            if relationship.attrib.get('TargetMode')!='External' and relationship.attrib.get('Type','').endswith('/worksheet'):
                targets[rid]=relationship.attrib['Target']
        book=ET.fromstring(archive.read('xl/workbook.xml'))
        sheet_paths={}
        for sheet in book.findall('{'+_MAIN+'}sheets/{'+_MAIN+'}sheet'):
            name=sheet.attrib['name'];rid=sheet.attrib.get('{'+_REL+'}id')
            if name not in wanted:continue
            if name in sheet_paths:raise ValueError('duplicate temporal worksheet name')
            target=targets.get(rid)
            if target is None:raise ValueError('temporal worksheet relationship missing')
            member=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl',target))
            if not member.startswith('xl/'):raise ValueError('temporal worksheet target outside workbook')
            sheet_paths[name]=member
        for name,coords in wanted.items():
            member=sheet_paths.get(name)
            if member is None:raise ValueError('temporal worksheet source missing')
            if member_counts[member]!=1:raise ValueError('ambiguous temporal worksheet ZIP member')
            found={}
            with archive.open(member) as stream:
                for event,node in ET.iterparse(stream,events=('end',)):
                    if node.tag=='{'+_MAIN+'}row':
                        node.clear()
                        continue
                    if node.tag!='{'+_MAIN+'}c':continue
                    coord=node.attrib.get('r')
                    if coord in coords:
                        if coord in found:raise ValueError('duplicate temporal cell coordinate')
                        kind=node.attrib.get('t','n');value=node.findtext('{'+_MAIN+'}v')
                        if kind=='d':found[coord]=('iso',None)
                        elif kind=='n' and value is not None:
                            serial=float(value)
                            if not math.isfinite(serial):raise ValueError('nonfinite temporal serial')
                            found[coord]=('number',serial)
                        else:raise ValueError('temporal source type cannot bind')
                    node.clear()
            if set(found)!=coords:raise ValueError('temporal cell source missing')
            result[name]=found
    return result
