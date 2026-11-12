import datetime,hashlib,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).parent),'/downloads/formula_engine']
import pytest,openpyxl
from shadow_adapter import ShadowSession,ShadowRejected
D=datetime.date(2026,11,11)
def loc(row,col,sheet='S'):return {'sheet':sheet,'row':row,'col':col}
def typed(v):return {'type':'number','value':v}
def setup(tmp_path,formula='=A1*2'):
 p=tmp_path/'w.xlsx';w=openpyxl.Workbook();w.active.title='S';w['S']['A1']=2;w['S']['B1']=formula;w.save(p);sha=hashlib.sha256(p.read_bytes()).hexdigest();return p,ShadowSession(p,source_sha256=sha,as_of=D,observations=[loc(1,2)])
def request(s,before=2,after=3):
 state=s.read();return {'revision':state['revision'],'source_sha256':state['source_sha256'],'edits':[{'cell':loc(1,1),'before':typed(before),'after':typed(after)}]}
def test_atomic_success_diff_and_source_unchanged(tmp_path):
 p,s=setup(tmp_path);old=p.read_bytes();a=s.read();r=s.apply(request(s));assert r['accepted'];assert r['state']['values'][0]['actual']==typed(6);assert r['selected_changes'][0]['before']==typed(4);assert p.read_bytes()==old;assert not r['release_ready'];assert a['revision']!=s.read()['revision']
def test_stale_revision_baseline_duplicate_and_formula_overwrite_reject(tmp_path):
 p,s=setup(tmp_path);r=request(s);s.apply(r);snapshot=s.read()
 with pytest.raises(ShadowRejected,match='stale_revision'):s.apply(r)
 for mode,code in [('before','baseline_mismatch'),('duplicate','duplicate_edit'),('formula','formula_overwrite')]:
  r=request(s,3,4)
  if mode=='before':r['edits'][0]['before']=typed(999)
  elif mode=='duplicate':r['edits']+=r['edits']
  else:r['edits'][0]['cell']=loc(1,2)
  with pytest.raises(ShadowRejected,match=code):s.apply(r)
  assert s.read()==snapshot
def test_masked_failure_rejected_and_recovery(tmp_path):
 p,s=setup(tmp_path,'=IF(A1=3,IFERROR(UNKNOWN(),0),A1*2)');a=s.read();r=s.apply(request(s));assert not r['accepted'];assert any('UNKNOWN'in x for x in r['candidate']['diagnostics']);assert s.read()==a
 r=s.apply(request(s,2,4));assert r['accepted'];assert s.read()['values'][0]['actual']==typed(8)
def test_error_rejected_restore_and_aba_revision(tmp_path):
 p,s=setup(tmp_path,'=1/(A1-3)');a=s.read();r=s.apply(request(s));assert not r['accepted'];assert s.read()==a
 b=s.apply(request(s,2,4));assert b['accepted'];c=s.apply(request(s,4,2));assert c['accepted'];assert s.read()['values']==a['values'];assert s.read()['revision']!=a['revision']
def test_source_replaced_rejects_without_model_commit(tmp_path):
 p,s=setup(tmp_path);a=s.read();p.write_bytes(p.read_bytes()+b'changed')
 with pytest.raises(ShadowRejected,match='source_hash_changed'):s.apply(request(s))
 assert s.read()==a
def test_no_returned_object_can_mutate_session(tmp_path):
 _,s=setup(tmp_path);a=s.read();a['values'][0]['actual']['value']=999;assert s.read()['values'][0]['actual']==typed(4)
@pytest.mark.parametrize('value',[True,0,-1,float('nan'),float('inf'),301])
def test_bad_budget_refused(tmp_path,value):
 _,s=setup(tmp_path)
 with pytest.raises(ShadowRejected,match='budget_invalid'):s.apply(request(s),budget_seconds=value)
def test_budget_exhaustion_preserves_state_and_can_retry(tmp_path,monkeypatch):
 _,s=setup(tmp_path);a=s.read();original=s._evaluate
 def exhausted(*args):raise ShadowRejected('budget_exhausted')
 monkeypatch.setattr(s,'_evaluate',exhausted)
 with pytest.raises(ShadowRejected,match='budget_exhausted'):s.apply(request(s))
 assert s.read()==a;monkeypatch.setattr(s,'_evaluate',original);assert s.apply(request(s))['accepted']
def test_case_insensitive_duplicate_locators(tmp_path):
 _,s=setup(tmp_path);r=request(s);r['edits'].append({**r['edits'][0],'cell':loc(1,1,'s')})
 with pytest.raises(ShadowRejected,match='duplicate_edit'):s.apply(r)
def test_formula_looking_text_type_rejected(tmp_path):
 _,s=setup(tmp_path);r=request(s);r['edits'][0]['after']={'type':'text','value':'=1+1'}
 with pytest.raises(ShadowRejected,match='typed_edit_invalid'):s.apply(r)

def test_source_change_during_candidate_evaluation_rejects(tmp_path,monkeypatch):
 p,s=setup(tmp_path);a=s.read();original=s._evaluate
 def changed(w,deadline):
  result=original(w,deadline);p.write_bytes(p.read_bytes()+b'changed');return result
 monkeypatch.setattr(s,'_evaluate',changed)
 with pytest.raises(ShadowRejected,match='source_hash_changed'):s.apply(request(s))
 assert s.read()==a

def test_missing_source_and_candidate_load_failure_rollback(tmp_path,monkeypatch):
 p,s=setup(tmp_path);a=s.read();original=s._load
 def failed():raise ShadowRejected('source_load_failed')
 monkeypatch.setattr(s,'_load',failed)
 with pytest.raises(ShadowRejected,match='source_load_failed'):s.apply(request(s))
 assert s.read()==a
 monkeypatch.setattr(s,'_load',original);p.unlink()
 with pytest.raises(ShadowRejected,match='source_unreadable'):s.apply(request(s))
 assert s.read()==a

def test_concurrent_same_revision_only_one_commit(tmp_path):
 from concurrent.futures import ThreadPoolExecutor
 _,s=setup(tmp_path);r=request(s)
 def attempt():
  try:return s.apply(r)['accepted']
  except ShadowRejected as e:return e.code
 with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(lambda _:attempt(),range(2)))
 assert sorted(map(str,results))==['True','stale_revision'];assert s.read()['generation']==1

@pytest.mark.parametrize('field,value,code',[
 ('extra',True,'request_schema_invalid'),('source_sha256','wrong','request_source_mismatch'),('edits',[],'edit_count_invalid')])
def test_request_rejection_no_state_change(tmp_path,field,value,code):
 _,s=setup(tmp_path);a=s.read();r=request(s);r[field]=value
 with pytest.raises(ShadowRejected,match=code):s.apply(r)
 assert s.read()==a

def test_invalid_date_hash_and_duplicate_observations(tmp_path):
 p,s=setup(tmp_path);sha=s.read()['source_sha256']
 with pytest.raises(ShadowRejected,match='explicit_date_required'):ShadowSession(p,source_sha256=sha,as_of='2026-11-11',observations=[loc(1,2)])
 with pytest.raises(ShadowRejected,match='source_hash_invalid'):ShadowSession(p,source_sha256='oops',as_of=D,observations=[loc(1,2)])
 with pytest.raises(ShadowRejected,match='duplicate_observation'):ShadowSession(p,source_sha256=sha,as_of=D,observations=[loc(1,2),loc(1,2,'s')])

def test_unobserved_edit_not_whole_workbook_certification(tmp_path):
 _,s=setup(tmp_path);r=request(s);r['edits'][0]['cell']=loc(10,10);r['edits'][0]['before']={'type':'blank','value':None};response=s.apply(r);assert response['accepted'];assert response['selected_changes']==[];assert not response['state']['release_ready'];assert response['state']['business_identity_binding'].startswith('unverified')

def test_loader_uses_single_verified_immutable_source_not_path_reopens(tmp_path,monkeypatch):
 import shadow_adapter as module
 p,s=setup(tmp_path);original_bytes=p.read_bytes();real=module.Workbook;seen=[]
 def inspect(source,**kwargs):
  assert hasattr(source,'read')and hasattr(source,'seek');source.seek(0);seen.append(hashlib.sha256(source.read()).hexdigest());source.seek(0)
  # Simulated external file replacement and restoration cannot change the
  # bytes passed to separate formula/cache/raw XML reads inside Workbook.
  p.write_bytes(b'transient replacement');result=real(source,**kwargs);p.write_bytes(original_bytes);return result
 monkeypatch.setattr(module,'Workbook',inspect);assert s.apply(request(s))['accepted'];assert seen==[s.read()['source_sha256']];assert p.read_bytes()==original_bytes

def test_post_evaluation_precommit_copy_over_budget_rolls_back(tmp_path,monkeypatch):
 import time
 _,s=setup(tmp_path);r=request(s);original=s.read;a=original()
 def slow():time.sleep(.08);return original()
 monkeypatch.setattr(s,'read',slow)
 with pytest.raises(ShadowRejected,match='budget_exhausted'):s.apply(r,budget_seconds=.05)
 assert original()==a;monkeypatch.setattr(s,'read',original);assert s.apply(r)['accepted']

def test_precommit_reply_failure_does_not_partially_commit(tmp_path,monkeypatch):
 _,s=setup(tmp_path);a=s.read();r=request(s);original=s._render
 def failed(*args):raise RuntimeError('authored reply-copy failure')
 monkeypatch.setattr(s,'_render',failed)
 with pytest.raises(ShadowRejected,match='response_preparation_failed'):s.apply(r)
 monkeypatch.setattr(s,'_render',original);assert s.read()==a;assert s.apply(r)['accepted']

def test_prospective_revision_failure_bounded_and_no_partial_commit(tmp_path,monkeypatch):
 _,s=setup(tmp_path);a=s.read();r=request(s);original=s._revision_id
 def failed(*args):raise TypeError('authored serialization failure')
 monkeypatch.setattr(s,'_revision_id',failed)
 with pytest.raises(ShadowRejected,match='response_preparation_failed'):s.apply(r)
 assert s.read()==a;monkeypatch.setattr(s,'_revision_id',original);assert s.apply(r)['accepted']
