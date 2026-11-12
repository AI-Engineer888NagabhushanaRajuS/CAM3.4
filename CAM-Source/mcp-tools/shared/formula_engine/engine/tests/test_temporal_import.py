"""Candidate temporal import regression, not full date-function certification."""
import datetime
import zipfile
from xml.etree import ElementTree as ET
import pytest
import openpyxl
from openpyxl.utils.datetime import CALENDAR_MAC_1904,CALENDAR_WINDOWS_1900
from excel_formula_engine import Workbook,NAME_ERR,DIV0


def test_numeric_temporal_serials_keep_epoch_leap_alias_and_raw_precision(tmp_path):
    for epoch,day in [(CALENDAR_WINDOWS_1900,40729),(CALENDAR_MAC_1904,39267)]:
        raw=openpyxl.Workbook();raw.epoch=epoch;s=raw.active;s.title='A & Dates'
        serials=[1,59,60,61,day,day+.123456789,.000000123456789,2.25,-1]
        for row,serial in enumerate(serials,1):
            s.cell(row,1,serial).number_format='yyyy-mm-dd hh:mm:ss.000'
            s.cell(row,2,f'=A{row}+1')
        s['A10']=2.25;s['A10'].number_format='[h]:mm:ss';s['B10']='=SUM(A10,1)'
        p=tmp_path/('date_'+str(epoch.year)+'.xlsx');raw.save(p)
        with zipfile.ZipFile(p) as z:
            root=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            exact={c.attrib['r']:float(c.findtext('m:v',namespaces=ns)) for c in root.findall('.//m:c',ns) if c.attrib['r'].startswith('A')}
        w=Workbook(str(p))
        for row in range(1,11):
            assert w.cell_value_now(s.title,row,1)==exact[f'A{row}']
            assert w.cell_value_now(s.title,row,2)==exact[f'A{row}']+1
        assert not w.notes
        w.set_value(s.title,5,1,12.5)
        assert w.cell_value_now(s.title,5,2)==13.5


def test_iso_temporal_epoch_duration_and_sheet_relationship_identity(tmp_path):
    for epoch,day in [(CALENDAR_WINDOWS_1900,40729),(CALENDAR_MAC_1904,39267)]:
        raw=openpyxl.Workbook();raw.epoch=epoch;raw.iso_dates=True
        s=raw.active;s.title='Second identity';other=raw.create_sheet('First identity');raw._sheets.reverse()
        for sheet,value in [(s,datetime.datetime(2011,7,5,12,0,0,123000)),(other,datetime.date(2011,7,5))]:
            sheet['A1']=value;sheet['B1']='=A1+1';sheet['C1']='=TODAY()'
        s['A2']=datetime.time(6,0,0,123000);s['A3']=datetime.timedelta(days=2,hours=6)
        p=tmp_path/('iso_'+str(epoch.year)+'.xlsx');raw.save(p);w=Workbook(str(p))
        assert abs(w.cell_value_now(s.title,1,1)-(day+.5+.123/86400))<1e-10
        assert w.cell_value_now(other.title,1,1)==day
        assert w.cell_value_now(s.title,2,1)==(6*3600+.123)/86400
        assert w.cell_value_now(s.title,3,1)==2.25
        if epoch.year==1904:
            assert w.cell_value_now(s.title,1,3)==NAME_ERR
            assert any('today:1904-date-system' in n for n in w.notes)


def test_formula_date_cache_is_not_used_as_evaluation_fallback(tmp_path):
    raw=openpyxl.Workbook();s=raw.active;s.title='S';s['A1']='=1/0';s['A1'].number_format='yyyy-mm-dd';s['B1']='=IFERROR(A1,7)'
    p=tmp_path/'cache.xlsx';raw.save(p)
    with zipfile.ZipFile(p) as z:contents={n:z.read(n) for n in z.namelist()}
    contents['xl/worksheets/sheet1.xml']=contents['xl/worksheets/sheet1.xml'].replace(b'<v></v>',b'<v>45000</v>',1)
    with zipfile.ZipFile(p,'w') as z:
        for n,b in contents.items():z.writestr(n,b)
    w=Workbook(str(p));assert w.sheets['s'].cached[(1,1)]==45000
    assert w.cell_value_now('S',1,1)==DIV0
    assert w.cell_value_now('S',1,2)==7


def test_unbound_temporal_source_refuses_with_masked_diagnostic(tmp_path,monkeypatch):
    from excel_formula_engine import temporal_serials
    raw=openpyxl.Workbook();s=raw.active;s.title='S';s['A1']=datetime.date(2011,7,5);s['B1']='=IFERROR(A1,7)';p=tmp_path/'unbound.xlsx';raw.save(p)
    def fail(*args):raise ValueError('synthetic source binding failure')
    monkeypatch.setattr(temporal_serials,'source_temporal_values',fail)
    w=Workbook(str(p));assert w.cell_value_now('S',1,1)==NAME_ERR
    assert w.cell_value_now('S',1,2)==7
    assert 'temporal-source-load:ValueError' in w.notes
    assert 'temporal-source-unbound:S!A1' in w.notes


def test_ambiguous_temporal_source_bindings_fail_closed(tmp_path):
    import copy,re,warnings
    from excel_formula_engine.temporal_serials import source_temporal_values
    raw=openpyxl.Workbook();sheet=raw.active;sheet.title='S';sheet['A1']=59;sheet['A1'].number_format='yyyy-mm-dd';sheet['B1']='=IFERROR(A1,7)'
    original=tmp_path/'original.xlsx';raw.save(original)
    with zipfile.ZipFile(original) as z:base={n:z.read(n) for n in z.namelist()}
    for kind in ['cell','relationship','sheet','zip_sheet','zip_workbook','zip_relationships']:
        content=base.copy()
        if kind=='cell':
            member='xl/worksheets/sheet1.xml';match=re.search(br'<c r="A1".*?</c>',content[member]);assert match
            content[member]=content[member].replace(match.group(),match.group()+match.group().replace(b'<v>59</v>',b'<v>61</v>'))
        elif kind=='relationship':
            member='xl/_rels/workbook.xml.rels';root=ET.fromstring(content[member]);r=next(r for r in root if r.attrib.get('Type','').endswith('/worksheet'));root.append(copy.deepcopy(r));content[member]=ET.tostring(root)
        elif kind=='sheet':
            member='xl/workbook.xml';root=ET.fromstring(content[member]);sheets=root.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets');sheets.append(copy.deepcopy(sheets[0]));content[member]=ET.tostring(root)
        p=tmp_path/(kind+'.xlsx')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(p,'w') as z:
                for member,data in content.items():z.writestr(member,data)
                if kind.startswith('zip_'):
                    duplicate={'zip_sheet':'xl/worksheets/sheet1.xml','zip_workbook':'xl/workbook.xml','zip_relationships':'xl/_rels/workbook.xml.rels'}[kind];z.writestr(duplicate,content[duplicate])
        # Direct source binder and integrated candidate both reject ambiguities.
        with pytest.raises(ValueError):source_temporal_values(p,openpyxl.load_workbook(original,data_only=True))
        w=Workbook(str(p));assert w.cell_value_now('S',1,1)==NAME_ERR
        assert w.cell_value_now('S',1,2)==7
        assert 'temporal-source-load:ValueError' in w.notes
