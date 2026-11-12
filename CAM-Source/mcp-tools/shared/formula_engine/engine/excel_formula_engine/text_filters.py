"""Strict stored worksheet ASCII text-list filter metadata, not hidden-row inference.

Only explicit literal text lists with optional blank selection or equal/notEqual
custom text criteria.
SUBTOTAL1-11 execution handled separately, including statistical domain guards.
No table/numeric/date/wildcard/top10/color/icon/extension semantics.
"""
from collections import Counter
import posixpath,re
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from openpyxl.utils.cell import range_boundaries
M='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
def _tag(name):return '{'+M+'}'+name

def ascii_literal(value):
 return type(value)is str and bool(value)and value.isascii()and all(32<=ord(c)<=126 for c in value)and not re.search(r'_[xX][0-9A-Fa-f]{4}_',value)and not any(x in value for x in '*?~')and not re.fullmatch(r'[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?',value.strip())

def parse_region(node):
 if node.tag!=_tag('autoFilter')or not set(node.attrib)<= {'ref','{http://schemas.microsoft.com/office/spreadsheetml/2014/revision}uid'}or 'ref'not in node.attrib:return None
 ref=node.attrib['ref']
 if not re.fullmatch(r'\$?[A-Z]+\$?[1-9]\d*:\$?[A-Z]+\$?[1-9]\d*',ref):return None
 left,top,right,bottom=range_boundaries(ref)
 if not(1<=left<=right<=16384 and 1<=top<bottom<=1048576):return None
 columns=[];seen=set()
 for col in node:
  if col.tag!=_tag('filterColumn')or not set(col.attrib)<= {'colId','hiddenButton','showButton'}:return None
  try:offset=int(col.attrib['colId'])
  except(ValueError,KeyError):return None
  if str(offset)!=col.attrib['colId']or offset in seen or not 0<=offset<=right-left:return None
  seen.add(offset)
  if len(col)!=1:return None
  childset=col[0]
  if childset.tag==_tag('filters'):
   if not set(childset.attrib)<= {'blank'}or childset.attrib.get('blank','0')not in('0','1','false','true'):return None
   values=[]
   for child in childset:
    if child.tag!=_tag('filter')or set(child.attrib)!={'val'}or len(child)or not ascii_literal(child.attrib['val']):return None
    values.append(child.attrib['val'].lower())
   include_blank=childset.get('blank','0')in('1','true')
   if(not values and not include_blank)or len(values)!=len(set(values)):return None
   columns.append((left+offset,{'kind':'list','blank':True,'values':tuple(values)}if include_blank else tuple(values)))
  elif childset.tag==_tag('customFilters'):
   if not set(childset.attrib)<= {'and'}or childset.attrib.get('and','0')not in('0','1','false','true')or not 1<=len(childset)<=2:return None
   criteria=[]
   for child in childset:
    if child.tag!=_tag('customFilter')or not set(child.attrib)<= {'operator','val'}or 'val'not in child.attrib or len(child):return None
    op=child.get('operator','equal');value=child.get('val')
    if op not in('equal','notEqual')or not ascii_literal(value):return None
    criteria.append((op,value.lower()))
   columns.append((left+offset,{'kind':'custom','and':childset.get('and','0')in('1','true'),'criteria':tuple(criteria)}))
  else:return None
 if not columns:return None
 return {'bounds':(left,top,right,bottom),'columns':tuple(columns)}

def source_text_filters(path):
 """Bind exact transitional worksheet identities or raise; never a generic OPC resolver."""
 from pathlib import PurePosixPath
 P='http://schemas.openxmlformats.org/package/2006/relationships'
 with ZipFile(path)as z:
  names=z.namelist()
  if len(names)!=len(set(names)):raise ValueError('duplicate-filter-zip-member')
  rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
  if rels.tag!='{'+P+'}Relationships':raise ValueError('unsupported-filter-relationships-namespace')
  targets={}
  for el in rels:
   if el.tag!='{'+P+'}Relationship':raise ValueError('unsupported-filter-relationship-element')
   rid=el.get('Id')
   if not rid or rid in targets:raise ValueError('missing-or-duplicate-filter-relationship-id')
   targets[rid]=el
  wb=ET.fromstring(z.read('xl/workbook.xml'))
  if wb.tag!=_tag('workbook'):raise ValueError('unsupported-filter-workbook-namespace')
  sheets=wb.findall(_tag('sheets'))
  if len(sheets)!=1:raise ValueError('missing-or-duplicate-filter-sheets')
  out={};seen_names=set();seen_parts=set();seen_sheetids=set();seen_rids=set()
  for el in sheets[0]:
   if el.tag!=_tag('sheet'):raise ValueError('unsupported-filter-sheet-element')
   name=el.get('name','');key=name.lower();sid=el.get('sheetId');rid=el.get('{'+R+'}id')
   if not name or key in seen_names or not sid or not re.fullmatch(r'[1-9][0-9]*',sid)or sid in seen_sheetids or rid in seen_rids:raise ValueError('ambiguous-filter-sheet-identity')
   seen_names.add(key);seen_sheetids.add(sid);seen_rids.add(rid);rel=targets.get(rid)
   if rel is None or rel.get('Type')!=R+'/worksheet'or rel.get('TargetMode','Internal')!='Internal':raise ValueError('unsupported-filter-sheet-relationship')
   target=rel.get('Target','')
   if not target or any(c in target for c in [':','\\','?','#','%']):raise ValueError('unsupported-filter-target')
   member=posixpath.normpath(target.lstrip('/')if target.startswith('/')else'xl/'+target)
   if not member.startswith('xl/worksheets/')or '..'in PurePosixPath(member).parts or not member.endswith('.xml')or member in seen_parts:raise ValueError('unsupported-or-duplicate-filter-target-part')
   seen_parts.add(member);root=ET.fromstring(z.read(member))
   if root.tag!=_tag('worksheet')or len(root.findall(_tag('sheetData')))!=1:raise ValueError('unsupported-filter-worksheet-structure')
   nodes=root.findall(_tag('autoFilter'))
   if len(nodes)!=1 or root.find(_tag('extLst'))is not None or root.find(_tag('tableParts'))is not None:out[name]=None;continue
   out[name]=parse_region(nodes[0])
  return out

def custom_text_match(value, specification):
 """Caller validates ASCII nonnumeric, nonblank scalar before this predicate."""
 results=[(value.lower()==criterion)if op=='equal'else(value.lower()!=criterion) for op,criterion in specification['criteria']]
 return all(results)if specification['and']else any(results)
