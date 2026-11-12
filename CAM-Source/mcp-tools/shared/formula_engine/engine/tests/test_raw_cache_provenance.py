import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/"engine"),str(Path(__file__).parent)]
import xml.etree.ElementTree as E
import pytest
from raw_cache_provenance import explicit_empty_formula_cache,NS

def ev(body,attrs='r="A1" t="str"',ns=NS):
 return explicit_empty_formula_cache(E.fromstring(f'<c xmlns="{ns}" {attrs}>{body}</c>'))
def test_empty():assert ev('<f>""</f><v/>').known and ev('<f>""</f><v/>').value==''
def test_shared_formula_present():assert ev('<f t="shared" si="0"/><v/>').known
def test_absent_formula():assert not ev('<v/>').known
def test_absent_value():assert not ev('<f>""</f>').known
@pytest.mark.parametrize('attrs',['r="A1"','r="A1" t="n"','r="A1" t="b"','r="A1" t="e"','r="A1" t="s"','r="A1" t="inlineStr"'])
def test_non_string_types(attrs):assert not ev('<f>""</f><v/>',attrs).known
@pytest.mark.parametrize('body',['<f>1</f><v>0</v>','<f>1</f><v> </v>','<f>1</f><v>00123</v>','<f>1</f><v>#N/A</v>'])
def test_nonempty(body):assert not ev(body).known
@pytest.mark.parametrize('body',['<f>1</f><f>1</f><v/>','<f>1</f><v/><v/>','<f>1</f><v/><is><t/></is>','<f>1</f><v><t/></v>','<f>1</f><v x="1"/>'])
def test_ambiguous(body):assert not ev(body).known
@pytest.mark.parametrize('coord',['A0','XFE1','A1048577','a1','A01','A1:B2',''])
def test_badcoords(coord):assert not ev('<f>1</f><v/>',f'r="{coord}" t="str"').known
def test_maxcoord():assert ev('<f>1</f><v/>','r="XFD1048576" t="str"').known
def test_namespace_unknown():assert not ev('<f>1</f><v/>',ns='urn:other').known
def test_wrong_child_namespace():assert not ev('<f xmlns="urn:other">1</f><v/>').known
def test_readonly():
 c=E.fromstring(f'<c xmlns="{NS}" r="A1" t="str"><f>1</f><v/></c>');before=E.tostring(c);explicit_empty_formula_cache(c);assert E.tostring(c)==before
