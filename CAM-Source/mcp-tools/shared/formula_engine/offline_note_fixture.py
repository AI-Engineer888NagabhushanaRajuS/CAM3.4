"""Read-only cell-bound note checks through the same source/edit evaluator fixture.

All row IDs are explicit fixture labels, never inferred application lineage.
"""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'engine'))
from excel_formula_engine import is_blank, is_error
from excel_formula_engine.note_lineage import audit_note_lineage
from offline_fixture import run, cell, typed


def _prepare(w, specification):
    if not isinstance(specification,dict) or set(specification)!={'field_map','source_rows','output_rows'}:
        raise ValueError('Explicit note field map and source/output cell rows required')
    # Reuse the helper's exact field-contract validation before any edit.
    audit_note_lineage([],[],source_id_field='id',output_source_id_field='source_id',field_map=specification['field_map'])
    result={}
    for side,idfield in [('source_rows','id'),('output_rows','source_id')]:
        rows=specification[side]
        if not isinstance(rows,list) or len(rows)>200:raise ValueError('Note row budget exceeded or invalid rows')
        prepared=[]
        for row in rows:
            if not isinstance(row,dict) or set(row)!={idfield,'cells'}:
                raise ValueError('Note rows require explicit fixture ID and cells')
            cells=row['cells']
            if not isinstance(cells,dict) or not cells or len(cells)>20:
                raise ValueError('Note field budget exceeded or empty fields')
            if any(not isinstance(k,str) or not k.strip() or k in ('id','source_id') for k in cells):
                raise ValueError('Invalid or reserved note field name')
            prepared.append((idfield,row[idfield],{name:cell(locator,w) for name,locator in cells.items()}))
        result[side]=prepared
    return result


def run_with_note_cells(workbook_path,fixture,specification):
    """Run the unchanged schema-1 calculation contract plus cell projections.

    This research helper uses the same Workbook before/after its validated literal
    edits. The observer cannot be requested by JSON and writes no workbook.
    """
    prepared=None
    snapshots=[]
    def observe(w,stage):
        nonlocal prepared
        if prepared is None:prepared=_prepare(w,specification)
        rows={};projected=[];errors=[]
        for side,items in prepared.items():
            materialized=[]
            for index,(idfield,identity,cells) in enumerate(items):
                record={idfield:identity}
                for name,locator in cells.items():
                    value=w.cell_value_now(*locator)
                    projected.append({'side':side,'row_index':index,'field':name,
                                      'cell':{'sheet':locator[0],'row':locator[1],'col':locator[2]},'actual':typed(value)})
                    if is_error(value):
                        errors.append({'side':side,'row_index':index,'field':name,'error':str(value)})
                        record[name]=None
                    else:record[name]=None if is_blank(value) else value
                materialized.append(record)
            rows[side]=materialized
        checked=audit_note_lineage(rows['source_rows'],rows['output_rows'],source_id_field='id',
                                  output_source_id_field='source_id',field_map=specification['field_map'])
        snapshots.append({'stage':stage,'projections':projected,'projection_errors':errors,'lineage':checked})
    calculation=run(workbook_path,fixture,_observer=observe)
    passed=(calculation['all_expected_values_match'] and not calculation['diagnostics']
            and not calculation['observed_error_outputs'] and len(snapshots)==2
            and all(s['lineage']['correspondence_gate_passed'] and not s['projection_errors'] for s in snapshots))
    return {'schema_version':1,'calculation':calculation,'note_snapshots':snapshots,
            'fixture_gate_passed':passed,'release_ready':False,'mutation':calculation['mutation'],
            'scope':'Same source-hash/date/literal-edit Workbook and dependency invalidation; only explicitly projected note cells. '
                    'Fixture IDs/field map are authored research bindings, not application lineage. '
                    'No omitted-source, duplicate-output, cardinality, injective-join, financial, source-authority or acceptance claim.'}


def main():
    import argparse,json
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('workbook');p.add_argument('fixture');p.add_argument('note_cells')
    a=p.parse_args()
    try:result=run_with_note_cells(a.workbook,json.loads(Path(a.fixture).read_text()),json.loads(Path(a.note_cells).read_text()))
    except (ValueError,KeyError,TypeError) as exc:p.error(str(exc))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
