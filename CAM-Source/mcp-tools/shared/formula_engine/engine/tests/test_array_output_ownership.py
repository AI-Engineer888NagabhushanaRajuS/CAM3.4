"""Declared array output snapshots must not masquerade as fresh literal inputs."""
import datetime,hashlib,sys,zipfile
from pathlib import Path
import openpyxl,pytest
from openpyxl.worksheet.formula import ArrayFormula
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from excel_formula_engine import Workbook
from excel_formula_engine.values import NAME_ERR
from excel_formula_engine.provenance import describe_cell


def source(tmp_path,ref='D1:D3',formula='=UNIQUE(C1:C9)'):
    raw=openpyxl.Workbook();s=raw.active;s.title='S'
    for r,v in enumerate(['A','B','A','C'],1):s.cell(r,3,v)
    s['D1']=ArrayFormula(ref=ref,text=formula);s['D2']='B';s['D3']='C';s['F1']='=D2';s['F2']='=IFERROR(D2,"masked")';s['F3']='=IF(TRUE,"safe",D2)';s['F4']='=SUM(D2:D3)'
    p=tmp_path/'array.xlsx';raw.save(p);return p


def test_direct_and_formula_child_reads_never_return_saved_snapshot(tmp_path):
    w=Workbook(source(tmp_path))
    for row,col in [(2,4),(3,4),(1,6),(4,6)]:assert w.cell_value_now('s',row,col)==NAME_ERR
    assert any('array-output-uncomputed:'in x for x in w.notes)
    assert w.sheets['s'].cached[2,4]=='B'  # retained evidence, never calculation fallback
    w.set_value('S',2,3,'new authored input')
    assert w.cell_value_now('S',2,4)==NAME_ERR


def test_masked_failure_diagnostic_and_lazy_unreached_output(tmp_path):
    w=Workbook(source(tmp_path));assert w.cell_value_now('S',3,6)=='safe';assert not w.notes
    assert w.cell_value_now('S',2,6)=='masked';assert any('array-output-uncomputed:'in x for x in w.notes)


def test_followers_block_even_injected_calculation_cache(tmp_path):
    w=Workbook(source(tmp_path));w.cache['s',2,4]='stale'
    assert w.cell_value_now('S',2,4)==NAME_ERR


def test_direct_and_formula_edits_cannot_detach_array_ownership(tmp_path):
    w=Workbook(source(tmp_path))
    for r in [1,2,3]:
        with pytest.raises(ValueError,match='array-output-edit-unsupported'):w.set_value('S',r,4,'X')
        with pytest.raises(ValueError,match='array-output-edit-unsupported'):w.set_formula('S',r,4,'=7')
    assert w.sheets['s'].cached[2,4]=='B'


def test_provenance_not_literal_input(tmp_path):
    w=Workbook(source(tmp_path));o=describe_cell(w,'S',2,4)
    assert o.storage=='array-output-snapshot';assert o.origin_role=='array-derived-uncomputed';assert o.has_saved_value
    assert describe_cell(w,'S',1,4).storage=='formula'
    assert describe_cell(w,'S',1,3).storage=='literal'


def test_single_anchor_metadata_does_not_infer_adjacent_ownership(tmp_path):
    w=Workbook(source(tmp_path,ref='D1'))
    assert w.cell_value_now('S',1,4)==NAME_ERR
    assert w.cell_value_now('S',2,4)=='B'
    w.set_value('S',2,4,'independent authored literal');assert w.cell_value_now('S',2,4)=='independent authored literal'
    assert not any('array-output-uncomputed:'in x for x in w.notes)


def test_general_legacy_array_follower_also_not_scalar_anchor_result(tmp_path):
    w=Workbook(source(tmp_path,formula='=C1:C3'))
    assert w.cell_value_now('S',1,4)=='A'
    assert w.cell_value_now('S',2,4)==NAME_ERR
    assert w.cell_value_now('S',3,4)==NAME_ERR


@pytest.mark.parametrize('ref',['D2:D3','D1:D1048577','D1:XFE3','D1:D0','D1:D3 F1:F3'])
def test_invalid_geometry_fails_loading_instead_of_guessing(tmp_path,ref):
    with pytest.raises(ValueError,match='array-output-metadata-unsupported'):Workbook(source(tmp_path,ref=ref))


def test_overlapping_declared_regions_rejected(tmp_path):
    p=source(tmp_path);w=openpyxl.load_workbook(p);w['S']['D2']=ArrayFormula(ref='D2:D4',text='=C2:C4');w.save(p)
    with pytest.raises(ValueError,match='array-output-metadata-overlap'):Workbook(p)


def test_declared_empty_follower_and_cross_sheet_read_are_refused(tmp_path):
    p=source(tmp_path,ref='D1:D8');raw=openpyxl.load_workbook(p);t=raw.create_sheet('Other');t['A1']='=S!D8';raw.save(p);w=Workbook(p)
    assert w.cell_value_now('S',8,4)==NAME_ERR
    assert w.cell_value_now('Other',1,1)==NAME_ERR


def test_shadow_selected_and_masked_snapshots_block_and_edits_rejected(tmp_path):
    import importlib.util
    path=Path(__file__).resolve().parents[2]/'shadow_adapter.py';spec=importlib.util.spec_from_file_location('array_owned_shadow_adapter',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);ShadowSession,ShadowRejected=mod.ShadowSession,mod.ShadowRejected
    p=source(tmp_path);h=hashlib.sha256(p.read_bytes()).hexdigest()
    for row,col in [(2,4),(2,6)]:
        session=ShadowSession(p,source_sha256=h,as_of=datetime.date(2026,11,11),observations=[{'sheet':'S','row':row,'col':col}]);state=session.read();assert not state['selected_scope_clean'];assert 'diagnostics_including_masked_failures'in state['calculation_blockers']
    session=ShadowSession(p,source_sha256=h,as_of=datetime.date(2026,11,11),observations=[{'sheet':'S','row':1,'col':3}]);before=session.read()
    with pytest.raises(ShadowRejected,match='array_output_overwrite_forbidden'):
        session.apply({'revision':before['revision'],'source_sha256':h,'edits':[{'cell':{'sheet':'S','row':2,'col':4},'before':{'type':'text','value':'B'},'after':{'type':'text','value':'X'}}]})
    assert session.read()==before;assert hashlib.sha256(p.read_bytes()).hexdigest()==h


def test_missing_array_anchor_formula_text_cannot_become_cached_literal(tmp_path):
    with pytest.raises(ValueError,match='array-formula-text-unavailable'):Workbook(source(tmp_path,formula='='))


def test_large_legal_declared_rectangle_stays_compact_and_refuses_far_follower(tmp_path):
    w=Workbook(source(tmp_path,ref='D1:XFD1048576'))
    assert w.sheets['s'].array_regions==[(1,4,1048576,16384)]
    assert w.cell_value_now('S',1048576,16384)==NAME_ERR
