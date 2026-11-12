"""Offline source-bound fixture runner. Never writes a workbook or calls an app."""
import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent/'engine'))
from excel_formula_engine import Workbook, BLANK, is_blank, is_error
from excel_formula_engine.provenance import describe_cell


def typed(value):
    if is_error(value): return {'type':'error','value':str(value)}
    if is_blank(value): return {'type':'blank','value':None}
    if isinstance(value,bool): return {'type':'boolean','value':value}
    if isinstance(value,(int,float)) and math.isfinite(value): return {'type':'number','value':value}
    if isinstance(value,str): return {'type':'text','value':value}
    raise ValueError('Value outside supported finite scalar types')


def decode(record):
    if not isinstance(record,dict) or set(record)!={'type','value'}:
        raise ValueError('Typed value must contain exactly type and value')
    kind,value=record['type'],record['value']
    if kind=='blank' and value is None:return BLANK
    if kind=='boolean' and type(value) is bool:return value
    if kind=='number' and type(value) in (int,float) and math.isfinite(value):return value
    if kind=='text' and isinstance(value,str) and not value.startswith('='):return value
    # Refuse formula-looking text to keep the fixture boundary unambiguously literal.
    raise ValueError('Invalid typed edit/expectation; formulas and error injection are not allowed')


def cell(record,w):
    if not isinstance(record,dict) or set(record)!={'sheet','row','col'}:
        raise ValueError('Cell locator must contain exactly sheet, row and col')
    sheet,row,col=record.get('sheet'),record.get('row'),record.get('col')
    if not isinstance(sheet,str) or w._sheet(sheet) is None:raise ValueError('Unknown sheet')
    if type(row) is not int or type(col) is not int or not 1<=row<=1048576 or not 1<=col<=16384:
        raise ValueError('Invalid cell coordinates')
    return w._sheet(sheet).title,row,col


def run(workbook_path,fixture, *, _observer=None):
    # Validate the hash and complete schema before any in-memory edit.
    required={'schema_version','workbook_sha256','as_of','evidence','observations','edits'}
    if not isinstance(fixture,dict) or set(fixture)!=required or type(fixture['schema_version']) is not int or fixture['schema_version']!=1:
        raise ValueError('Unsupported fixture schema')
    path=Path(workbook_path);before_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    if fixture['workbook_sha256']!=before_hash:raise ValueError('Workbook hash does not match fixture')
    as_of=datetime.date.fromisoformat(fixture['as_of'])
    evidence=fixture['evidence']
    if not isinstance(evidence,dict) or set(evidence)!={'kind','reference','limits'}:
        raise ValueError('Evidence must state kind, reference and limits')
    if evidence['kind'] not in ('synthetic','hypothetical-source-edit','historical-source-snapshot'):
        raise ValueError('Only research evidence kinds are accepted; no approval grant is inferred')
    if not all(isinstance(evidence[k],str) and evidence[k].strip() for k in ('reference','limits')):
        raise ValueError('Evidence reference and limits must be nonempty')
    if not isinstance(fixture['observations'],list) or not fixture['observations']:
        raise ValueError('At least one observation is required')
    if not isinstance(fixture['edits'],list) or len(fixture['edits'])>200:raise ValueError('Edit budget exceeded')
    w=Workbook(str(path),today=as_of)
    obs=[];seen=set()
    for record in fixture['observations']:
        if not isinstance(record,dict) or set(record)!={'cell','expected_before','expected_after'}:raise ValueError('Invalid observation record')
        key=cell(record['cell'],w)
        if key in seen:raise ValueError('Duplicate observation')
        seen.add(key)
        obs.append((key,typed(decode(record['expected_before'])),typed(decode(record['expected_after']))))
    plan=[];seen=set()
    for record in fixture['edits']:
        if not isinstance(record,dict) or set(record)!={'cell','before','after'}:raise ValueError('Invalid edit record')
        key=cell(record['cell'],w)
        if key in seen:raise ValueError('Duplicate edit')
        seen.add(key)
        if describe_cell(w,*key).storage=='formula':raise ValueError('Fixture edits may not overwrite formula cells')
        old,new=decode(record['before']),decode(record['after'])
        if typed(w.cell_value_now(*key))!=typed(old):raise ValueError('Edit baseline does not match workbook')
        plan.append((key,new))
    checks=[]
    def snapshot(stage,index):
        for key,expected_before,expected_after in obs:
            expected=(expected_before,expected_after)[index]
            actual=typed(w.cell_value_now(*key))
            origin=describe_cell(w,*key)
            checks.append({'stage':stage,'cell':{'sheet':key[0],'row':key[1],'col':key[2]},
                           'storage':origin.storage,'actual':actual,'expected':expected,
                           'matches_exactly':actual==expected})
        if _observer is not None:_observer(w,stage)
    snapshot('before',0)
    for key,value in plan:w.set_value(*key,value)
    snapshot('after',1)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before_hash
    diagnostics=list(dict.fromkeys(w.notes))
    return {'schema_version':1,'workbook_sha256':before_hash,'as_of':as_of.isoformat(),
            'evidence':evidence,'evidence_authority':'Fixture metadata is a research label, never user/client approval.',
            'checks':checks,'all_expected_values_match':all(x['matches_exactly'] for x in checks),
            'diagnostics':diagnostics,'observed_error_outputs':sum(x['actual']['type']=='error' for x in checks),
            'observation_scope':'Only explicitly listed cells and evaluated dependency paths, not all workbook anchors.',
            'mutation':'In-memory literal edits only. Original file hash unchanged. No app/database/export/network call.',
            'release_ready':False,
            'release_boundary':'Matches prove only this source-bound research fixture. Diagnostics, independent expected outputs, client policy, runtime revision and production authority remain separate gates.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('workbook');p.add_argument('fixture')
    args=p.parse_args()
    try:result=run(args.workbook,json.loads(Path(args.fixture).read_text()))
    except (ValueError,KeyError,TypeError) as exc:p.error(str(exc))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
