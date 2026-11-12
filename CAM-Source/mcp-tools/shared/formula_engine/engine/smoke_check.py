"""Standalone synthetic smoke check. Creates no external or private dependencies."""
import datetime
import json
import tempfile
from pathlib import Path
import openpyxl
from excel_formula_engine import Workbook, VALUE_ERR
from audit_workbook import audit


def run():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'smoke.xlsx'
        raw = openpyxl.Workbook()
        s = raw.active
        s.title = 'Inputs'
        s.append(['Part', 'Qty', 'Unit price', 'Extended'])
        s.append(['A', 2, 3.5, '=B2*C2'])
        s['F2'] = '=IFERROR(_XLUDF.NUMBERVALUE("1"),0)'
        raw.save(p)
        w = Workbook(str(p), today=datetime.date(2026,11,11))
        assert w.cell_value_now('Inputs',2,4) == 7
        w.set_value('Inputs',2,2,4)
        assert w.cell_value_now('Inputs',2,4) == 14
        assert w.cell_value_now('Inputs',2,6) == 0
        report = audit(p, datetime.date(2026,11,11))
        assert report['complete'] and not report['error_outputs']
        assert any('function:_XLUDF.NUMBERVALUE' in n for n in report['diagnostics'])
        assert 'diagnostics_require_review_including_masked_failures' in report['calculation_gate_blockers']
        assert not report['release_ready']
        s.auto_filter.ref='A1:D2'
        s.auto_filter.add_filter_column(0,['A'])
        s['G2']='=SUBTOTAL(9,D2:D2)'
        raw.save(p)
        filtered = Workbook(str(p))
        assert filtered.cell_value_now('Inputs',2,7) == VALUE_ERR
    return {'checks_passed': ['scalar formula', 'edit invalidation', 'masked diagnostic blocks gate',
                              'active-filter subtotal refuses'],
            'private_sources_required': False, 'production_ready': False}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
