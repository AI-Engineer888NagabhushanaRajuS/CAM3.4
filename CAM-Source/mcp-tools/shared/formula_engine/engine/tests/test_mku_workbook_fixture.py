"""Source-linked compatibility/propagation experiment, not client acceptance.
Source Drive165CKfftJSjIZS5BbtbiTpYrgjmJe__AR, master CAM-197 issue summary.
Original source mail/attachment relationship remains unverified.
"""
import os,datetime,decimal,json
import pytest
from excel_formula_engine import Workbook

PATH='/downloads/CE-005862-MKU-SEEYA_OLED_DRIVER_BOARD-Internal_09-Sep-2026_Rev0.xlsx'

@pytest.mark.skipif(not os.path.exists(PATH),reason='Private original workbook not present; recover exact Drive source, do not synthesize replacement')
def test_mku_original_precision_and_real_dependency_edit():
    wb=Workbook(PATH,today=datetime.date(2026,11,11))
    baseline=wb.cell_value_now('Summary',10,8)
    assert baseline == 29608.490302351627
    unit=wb.cell_value_now('CBOM VL-1',11,5)
    assert unit == 4.934748383725271
    # A rounded display price4.9347 is NOT the stored source unit price.
    rounded_product=float(decimal.Decimal('4.9347')*decimal.Decimal('6000'))
    assert rounded_product == 29608.2
    assert baseline != rounded_product
    # Change only a real source quantity cell in memory. No file is written.
    wb.set_value('CBOM VL-1',11,6,1234.0)
    expected=float(decimal.Decimal(str(unit))*decimal.Decimal('1234'))
    actual=wb.cell_value_now('Summary',10,8)
    assert abs(actual-expected)<1e-9
    assert wb.cell_value_now('CBOM VL-1',11,7) == actual
    wb.set_value('CBOM VL-1',11,6,6000.0)
    assert wb.cell_value_now('Summary',10,8) == baseline

CBOM='/downloads/CBOM_Report_CE_005862_20260921_102742_4b8d409e.xlsx'

@pytest.mark.skipif(not os.path.exists(CBOM),reason='Exact archived CAM197 output unavailable')
def test_cam197_observed_static_extended_inconsistency_without_rewrite():
    from excel_formula_engine.provenance import describe_cell,arithmetic_product_diagnostic
    wb=Workbook(CBOM,today=datetime.date(2026,11,11));s='7.0 CBOM VL-2'
    u=wb.cell_value_now(s,10,5);q=wb.cell_value_now(s,10,6);g=wb.cell_value_now(s,10,7)
    assert g == 198810.5955655095
    assert describe_cell(wb,s,10,7).storage == 'literal'
    assert arithmetic_product_diagnostic(u,q,g)['status']=='inconsistent'
    assert wb.cell_value_now('Summary',8,7) == g
    assert wb.cell_value_now(s,10,7) == g  # validator never repairs source data
    # Stored quantity populations explain the gap; not an approved correction.
    delta=0.0
    for row in [26,27,28]:
        part_qty=wb.cell_value_now(s,row,9)
        ext_qty=wb.cell_value_now(s,row,10)
        price=wb.cell_value_now(s,row,11)
        assert ext_qty==6000
        assert part_qty<1
        delta+=(ext_qty-part_qty*q)*price
    assert abs((g-u*q)-delta)<1e-8
    # Changing a hypothetical J only affects the actual formula O, not literal G.
    wb.set_value(s,26,10,60)
    assert abs(wb.cell_value_now(s,26,15)-60*wb.cell_value_now(s,26,11))<1e-10
    assert wb.cell_value_now(s,10,7)==g

@pytest.mark.skipif(not os.path.exists(CBOM),reason='Exact archived CAM197 output unavailable')
def test_cam199_context_last_volume_lt_edit_updates_count_buckets():
    wb=Workbook(CBOM,today=datetime.date(2026,11,11));s='Lead Time (FG Wise)'
    assert wb.cell_value_now(s,4,2)==4
    assert wb.cell_value_now(s,5,2)==2
    wb.set_value('7.0 CBOM VL-2',25,19,10)
    assert wb.cell_value_now(s,4,2)==3
    assert wb.cell_value_now(s,5,2)==3
    assert wb.cell_value_now(s,13,2)==29

RAW_FAILURE_SOURCE='/downloads/Top 100 MPN Pricing from Mouser.xlsx'

@pytest.mark.skipif(not os.path.exists(RAW_FAILURE_SOURCE),reason='Original raw-failure source unavailable')
def test_original_malformed_source_error_not_substituted_for_parse_failure():
    from excel_formula_engine.values import ErrorValue,NAME_ERR
    wb=Workbook(RAW_FAILURE_SOURCE,today=datetime.date(2026,11,11))
    sd=wb._sheet('ERP Data')
    assert sd.formulas[3349,4]=='+TypeCOUNTERSUNK SCR M3X8,INOX'
    assert sd.cached[3349,4]=='#ERROR!'  # original XML t=str, not typed e
    got=wb.cell_value_now('ERP Data',3349,4)
    assert got==NAME_ERR
    assert got!=sd.cached[3349,4]  # source error is evidence, never target-output fallback


CAM189='/downloads/CBOM_Report_CE_005864_20260916_112632_b321ceda.xlsx'
@pytest.mark.skipif(not os.path.exists(CAM189),reason='Private filename-matched archive candidate absent; not a synthetic replacement')
def test_cam189_blank_scrap_formula_error_preserved_not_cached_output_substituted():
    from excel_formula_engine.values import VALUE_ERR
    wb=Workbook(CAM189,today=datetime.date(2026,9,16))
    for sn in ['Ex Inv VL-1','Ex Inv VL-2']:
        # IFERROR does not change a successfully returned empty string to zero.
        assert wb.cell_value_now(sn,5,11)==''
        assert wb.cell_value_now(sn,5,12)==VALUE_ERR
        assert wb.cell_value_now(sn,5,14)==VALUE_ERR
        assert wb.cell_value_now(sn,5,28)==VALUE_ERR


@pytest.mark.skipif(not os.path.exists(CAM189),reason='Private filename-matched archive candidate absent')
def test_cam192_last_volume_edit_updates_formula_not_literal_lt_snapshots():
    wb=Workbook(CAM189,today=datetime.date(2026,9,16))
    assert wb.cell_value_now('Ex Inv VL-2',14,21)==4
    assert wb.cell_value_now('Lead Time (FG Wise)',3,2)==8
    assert wb.cell_value_now('Lead Time Consolidated',3,2)==11
    wb.set_value('7.0 CBOM VL-2',25,19,10)  # hypothetical, not the client requested edit
    assert wb.cell_value_now('Ex Inv VL-2',14,21)==10
    assert wb.cell_value_now('Lead Time (FG Wise)',3,2)==8
    assert wb.cell_value_now('Lead Time Consolidated',3,2)==11


CAM205='/downloads/CBOM_Report_CE_005864C_20261005_162715_474fcc86 -- 05-Oct-2026.xlsx'
@pytest.mark.skipif(not os.path.exists(CAM205),reason='Private filename-matched CAM205 candidate absent')
def test_cam205_existing_bucket_recounts_new_bucket_not_created_static_fg_total():
    wb=Workbook(CAM205,today=datetime.date(2026,10,5))
    fg='Lead Time (FG Wise)';allfg='Lead Time Consolidated'
    assert wb.cell_value_now(fg,3,2)==9
    assert wb.cell_value_now(allfg,3,2)==13
    assert wb.cell_value_now(allfg,13,2)==45
    wb.set_value('7.0 CBOM VL-2',26,19,6)
    assert wb.cell_value_now(fg,3,2)==8
    assert wb.cell_value_now(fg,4,2)==2
    assert wb.cell_value_now(allfg,3,2)==12
    assert wb.cell_value_now(allfg,4,2)==2
    assert wb.cell_value_now(allfg,13,2)==45
    wb.set_value('7.0 CBOM VL-2',26,19,10)
    assert wb.cell_value_now(fg,3,2)==8
    assert wb.cell_value_now(fg,4,2)==1
    assert wb.cell_value_now(fg,13,2)==33  # stored literal, not a refreshed total
    assert wb.cell_value_now(allfg,13,2)==44  # no10week label to receive the row
