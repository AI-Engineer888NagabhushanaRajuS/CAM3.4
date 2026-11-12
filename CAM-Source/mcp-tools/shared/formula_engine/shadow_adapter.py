"""Read-only generated-workbook shadow transactions, never application writes.

Reuses the existing engine and offline fixture typed/locator/provenance boundary.
No DB ports, exporter, subprocess, HTTP, cache writer or backend selection exists.
"""
from pathlib import Path
import copy,datetime,hashlib,io,json,math,re,sys,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parent/'engine'))
from excel_formula_engine import Workbook
from excel_formula_engine.workbook import CalculationBudgetExceeded
from excel_formula_engine.provenance import describe_cell
from offline_fixture import typed,decode,cell

class ShadowRejected(ValueError):
 def __init__(self,code):super().__init__(code);self.code=code

class ShadowSession:
 """Compare-and-swap revision, preflight, private candidate, atomic acceptance.

 Acceptance means only this selected-cell local shadow transaction succeeded.
 It never establishes application row identity, financial approval or readiness.
 """
 def __init__(self,path,*,source_sha256,as_of,observations,budget_seconds=30):
  self._lock=threading.RLock();self._path=Path(path);self._sha=source_sha256
  if type(as_of)is not datetime.date:raise ShadowRejected('explicit_date_required')
  if type(source_sha256)is not str or not re.fullmatch('[0-9a-f]{64}',source_sha256):raise ShadowRejected('source_hash_invalid')
  self._date=as_of;self._generation=0;self._overrides={}
  deadline=self._deadline(budget_seconds);self._verify_source(deadline)
  self._w=self._load();self._check_time(deadline)
  if type(observations)is not list or not 1<=len(observations)<=200:raise ShadowRejected('observation_scope_invalid')
  self._observations=[];seen=set()
  for locator in observations:
   key=self._locator(locator,self._w)
   if key in seen:raise ShadowRejected('duplicate_observation')
   seen.add(key);self._observations.append(key)
  self._snapshot=self._evaluate(self._w,deadline)
  self._verify_source(deadline);self._revision=self._revision_id()

 @staticmethod
 def _deadline(seconds):
  if type(seconds)not in(int,float)or not math.isfinite(seconds)or not 0<seconds<=300:raise ShadowRejected('budget_invalid')
  return time.monotonic()+seconds
 @staticmethod
 def _check_time(deadline):
  if time.monotonic()>=deadline:raise ShadowRejected('budget_exhausted')
 def _verify_source(self,deadline):
  self._check_time(deadline)
  try:actual=hashlib.sha256(self._path.read_bytes()).hexdigest()
  except OSError:raise ShadowRejected('source_unreadable')from None
  if actual!=self._sha:raise ShadowRejected('source_hash_changed')
  self._check_time(deadline)
 def _load(self):
  # The owning loader reads formulas, cached values and raw XML separately.
  # One verified immutable byte snapshot prevents mixed-version/ABA reads.
  try:data=self._path.read_bytes()
  except OSError:raise ShadowRejected('source_unreadable')from None
  if hashlib.sha256(data).hexdigest()!=self._sha:raise ShadowRejected('source_hash_changed')
  try:return Workbook(io.BytesIO(data),today=self._date)
  except Exception:raise ShadowRejected('source_load_failed')from None
 @staticmethod
 def _locator(locator,w):
  try:return cell(locator,w)
  except (ValueError,TypeError,KeyError):raise ShadowRejected('cell_locator_invalid')from None
 def _revision_id(self,generation=None,overrides=None):
  generation=self._generation if generation is None else generation
  overrides=self._overrides if overrides is None else overrides
  payload={'source':self._sha,'date':self._date.isoformat(),'generation':generation,'overrides':[(list(k),typed(v))for k,v in sorted(overrides.items())]}
  return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 def _evaluate(self,w,deadline):
  values=[]
  try:
   for key in self._observations:
    self._check_time(deadline);value=w.cell_value_now(*key,budget_seconds=max(0,deadline-time.monotonic()));self._check_time(deadline)
    values.append({'cell':dict(zip(('sheet','row','col'),key)),'actual':typed(value),'storage':describe_cell(w,*key).storage})
  except CalculationBudgetExceeded:raise ShadowRejected('budget_exhausted')from None
  except ShadowRejected:raise
  except Exception:raise ShadowRejected('evaluation_failed')from None
  notes=list(dict.fromkeys(w.notes));blockers=[]
  if notes:blockers.append('diagnostics_including_masked_failures')
  if any(v['actual']['type']=='error'for v in values):blockers.append('selected_error_outputs')
  return {'values':values,'diagnostics':notes,'calculation_blockers':blockers,'selected_scope_clean':not blockers}
 def _render(self,revision,generation,snapshot):
  return copy.deepcopy({'revision':revision,'generation':generation,'source_sha256':self._sha,'as_of':self._date.isoformat(),**snapshot,'release_ready':False,'scope':'Only declared workbook cells and reached dependencies; not whole-workbook or application state','business_identity_binding':'unverified; coordinates do not establish database row or editable field','runtime_binding':'local prototype only; no deployed application connection','mutation':'local memory only; no workbook/database/cache/export/network writes'})
 def read(self):
  with self._lock:return self._render(self._revision,self._generation,self._snapshot)
 def apply(self,request,*,budget_seconds=30):
  with self._lock:
   deadline=self._deadline(budget_seconds)
   if type(request)is not dict or set(request)!={'revision','source_sha256','edits'}:raise ShadowRejected('request_schema_invalid')
   if request['revision']!=self._revision:raise ShadowRejected('stale_revision')
   if request['source_sha256']!=self._sha:raise ShadowRejected('request_source_mismatch')
   self._verify_source(deadline)
   edits=request['edits']
   if type(edits)is not list or not 1<=len(edits)<=200:raise ShadowRejected('edit_count_invalid')
   plan={}
   for edit in edits:
    if type(edit)is not dict or set(edit)!={'cell','before','after'}:raise ShadowRejected('edit_schema_invalid')
    key=self._locator(edit['cell'],self._w)
    if key in plan:raise ShadowRejected('duplicate_edit')
    if self._w.array_output_region(*key) is not None:raise ShadowRejected('array_output_overwrite_forbidden')
    if describe_cell(self._w,*key).storage=='formula':raise ShadowRejected('formula_overwrite_forbidden')
    try:before,after=decode(edit['before']),decode(edit['after'])
    except (ValueError,TypeError,KeyError):raise ShadowRejected('typed_edit_invalid')from None
    self._check_time(deadline)
    if typed(self._w.cell_value_now(*key))!=typed(before):raise ShadowRejected('edit_baseline_mismatch')
    plan[key]=after
   # Never mutate the accepted model while preparing a transaction. Rebuild a
   # private candidate from the pinned source and accepted literal overrides.
   candidate=self._load();overrides={**self._overrides,**plan}
   for key,value in overrides.items():candidate.set_value(*key,value)
   result=self._evaluate(candidate,deadline);self._verify_source(deadline)
   if result['calculation_blockers']:
    return {'accepted':False,'reason':'candidate_calculation_blocked','accepted_state':self.read(),'candidate':copy.deepcopy(result),'release_ready':False}
   # Build every reply/copy/hash/diff before the single acceptance point.
   # No serialization or other fallible work follows the state assignment.
   try:
    prior=self.read();generation=self._generation+1;revision=self._revision_id(generation,overrides)
    current=self._render(revision,generation,result)
    diff=[{'cell':a['cell'],'before':a['actual'],'after':b['actual']}for a,b in zip(prior['values'],current['values'])if a['actual']!=b['actual']]
    response={'accepted':True,'prior_revision':prior['revision'],'state':current,'selected_changes':diff,'release_ready':False}
   except ShadowRejected:raise
   except Exception:raise ShadowRejected('response_preparation_failed')from None
   self._verify_source(deadline)
   self._w,self._overrides,self._snapshot,self._generation,self._revision=candidate,overrides,result,generation,revision
   return response
