# Generation logic: cbom_vl

Source: GitHub solutionsDigibull/BuLLMQuote_SRIM @ 540918090b1b, mcp-tools/reporting/superset/reports/cbom_vl.py
Method: static read of the module (docstrings, function bodies, constants). Statements labelled INFERENCE are not stated in code.

## Module docstring

Python port of the 7.0 CBOM VL report (Laravel PHP).

Two layers, mirroring the PHP pipeline:
  1. cbom_vl_rows() — port of CBOMVolumeSheetExcelFormula::generateRows():
     builds the literal 2D row layout (top summary section, padding, and
     per-Assembly/FG data blocks) for one volume (or 'proto'), matching the
     input/output JSON documented in cbom-vl-report.md. Supports both the
     hierarchical_order-driven ordering and the alphabetical FG-then-Assembly
     fallback.
  2. build_cbom_vl_sheet() — port of the same class's static layout: sheet
     title, header/data/TOTAL row coloring, per-assembly block coloring, and
     the currency reference table (J1:K4).

# ponytail: the shipped PHP class also overwrites ~15 columns (K, N, O, U,
# AG-AW), the J10:K17 validation/Status counts, and the M9/M11 MOQ Cost cells
# with live, self-referential Excel formulas (SUMPRODUCT/INDEX-MATCH over the
# sheet's own just-written rows, plus a cross-sheet reference into this
# volume's own Ex Inv VL sheet for MOQ Cost) — all now reproduced in
# build_cbom_vl_sheet() with dynamic (not hardcoded) row bounds.

No DB access happens here — cbomJson is supplied by the caller.

v2 source schema note: `_data_row()` already reads `v.get("batch_qty", "")`
and `v.get("supplierType", "")` as plain dict lookups -- no code change was
needed when their confirmed sources became the `batch` table (fg, volume,
batch_qty) and `quote_win.supplier_type` respectively (previously gaps; see
cbom-database-schema-design.md). Only the loader that builds the per-volume
dicts under `data[assembly][fg][i]["volumes"]` needs to populate those two
keys now instead of leaving them blank.

## Module constants

- `NUM_COLS = 50`
- `_RESERVED_KEYS = {"summary", "validation_counts", "project_name", "total_MOQ_costs", "hierarchical_order"}`
- `_VALIDATION_LABELS = [     "Count of Total CPNs", "Count of Unique CPNs", "Count of Shared CPNs",     "Total Occurrences of Shared CPNs", "Total Line Items", "Uncosted Line Items Count",     "CPNs wit`
- `_HEADER_FILL = PatternFill("solid", fgColor="2F5496")`
- `_HEADER_FONT = Font(bold=True, color="FFFFFF")`
- `_DATA_FILL = PatternFill("solid", fgColor="F2F6FC")`
- `_TOTAL_FILL = PatternFill("solid", fgColor="FFD966")`
- `_ISSUE_FILL = PatternFill("solid", fgColor="FFFF0000")`
- `_THIN_SIDE = Side(style="thin", color="000000")`
- `_THIN_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)`

## Functions (line, name, first docstring line)

- L65 `_headers(display_volume)` 
- L80 `_find_volume(volumes, volume)` 
- L87 `_spacer_row()` 
- L93 `_data_row(item, assembly, v)` 
- L119 `_assembly_label(assembly, fg, item)` 
- L126 `cbom_vl_rows(data, volume)` Port of CBOMVolumeSheetExcelFormula::generateRows(): the full 2D sheet layout.
- L227 `cbom_vl_bounds(data, volume)` Computes the same (first_data_row, last_data_row) that consumers elsewhere
- L254 `_style_range(ws, start_row, end_row, start_col, end_col, fill, font)` 
- L264 `_apply_number_format(ws, col, row1, row2, fmt)` 
- L269 `build_scrap_factor_sheet(wb)` Creates the hidden "Scrap Factor" configuration sheet -- one row per active tier
- L302 `build_batch_settings_sheet(wb, data)` Creates the hidden "Batch Settings" configuration sheet -- one row per (FG,
- L338 `build_cbom_vl_sheet(wb, data, volume, expected_row_count)` Port of CBOMVolumeSheetExcelFormula: writes and styles a '7.0 CBOM VL-n' sheet.
- L934 `_demo()` 

## Authored formula sites (line: template string; placeholders in braces are Python f-string fields)

- L443: `=SUMIFS($AX$`
- L443: `=SUMIFS($AX${first_data_row}:$AX${last_data_row}, $A${first_data_row}:$A${last_data_row}, $C{_summary_row}, $AH${first_data_row}:$AH${last_data_row}, "<>TRUE")`
- L447: `=SUM(E`
- L447: `=SUM(E{summary_data_start}:E{summary_data_end})`
- L448: `=SUM(G`
- L448: `=SUM(G{summary_data_start}:G{summary_data_end})`
- L498: `=SUMPRODUCT(($AP$`
- L498: `=SUMPRODUCT(($AP${first_data_row}:$AP${last_data_row}=1)*($C${first_data_row}:$C${last_data_row}<>""))`
- L501: `=K10-K12`
- L503: `=SUMPRODUCT(($AP$`
- L503: `=SUMPRODUCT(($AP${first_data_row}:$AP${last_data_row}=2)*($C${first_data_row}:$C${last_data_row}<>""))`
- L506: `=K14-K11`
- L508: `=SUMPRODUCT(--((LOWER(TRIM($AF$`
- L508: `=SUMPRODUCT(--((LOWER(TRIM($AF${first_data_row}:$AF${last_data_row}))="true")+(LOWER(TRIM($AF${first_data_row}:$AF${last_data_row}))="false")))`
- L528: `=COUNTIFS($AO$`
- L528: `=COUNTIFS($AO${first_data_row}:$AO${last_data_row},FALSE,$AF${first_data_row}:$AF${last_data_row},TRUE)`
- L532: `=SUMPRODUCT(($AM$`
- L532: `=SUMPRODUCT(($AM${first_data_row}:$AM${last_data_row}=FALSE)*($AP${first_data_row}:$AP${last_data_row}=1)*--(($AF${first_data_row}:$AF${last_data_row}=TRUE)+($AF${first_data_row}:$AF${last_data_row}="TRUE")+($AF${first_data_row}:$AF${last_data_row}=1)>0))`
- L539: `=SUMPRODUCT(($AN$`
- L539: `=SUMPRODUCT(($AN${first_data_row}:$AN${last_data_row}=FALSE)*($AP${first_data_row}:$AP${last_data_row}=1)*--(($AF${first_data_row}:$AF${last_data_row}=TRUE)+($AF${first_data_row}:$AF${last_data_row}="TRUE")+($AF${first_data_row}:$AF${last_data_row}=1)>0))`
- L554: `=SUMPRODUCT(($AQ$`
- L554: `=SUMPRODUCT(($AQ${first_data_row}:$AQ${last_data_row}=FALSE)*{_is_data_test})`
- L568: `=SUMPRODUCT(($AR$`
- L568: `=SUMPRODUCT(($AR${first_data_row}:$AR${last_data_row}=FALSE)*{_is_data_test})`
- L571: `=SUMPRODUCT(($AS$`
- L571: `=SUMPRODUCT(($AS${first_data_row}:$AS${last_data_row}=FALSE)*{_is_data_test})`
- L574: `=SUMPRODUCT(($AT$`
- L574: `=SUMPRODUCT(($AT${first_data_row}:$AT${last_data_row}=FALSE)*{_is_data_test})`
- L577: `="")+ISBLANK($E$`
- L577: `=SUMPRODUCT(`
- L577: `=SUMPRODUCT({_is_data_test}*(($E${first_data_row}:$E${last_data_row}="")+ISBLANK($E${first_data_row}:$E${last_data_row})>0))`
- L591: `='{ex_inv_sheet}'!$A$2`
- L593: `=IFERROR($M$11/G`
- L593: `=IFERROR($M$11/G{total_row},0)`
- L714: `=IF($AF`
- L714: `=IF($AF{_r}, IFERROR(IF(OR($M{_r}="", $L{_r}=""), "", $L{_r}/INDEX($K$1:$K${currency_table_last_row},MATCH($M{_r},$J$1:$J${currency_table_last_row},0))*INDEX($K$1:$K${currency_table_last_row},MATCH($N$1,$J$1:$J${currency_table_last_row},0))), ""), "")`
- L729: `=IF(AND($AF`
- L729: `=IF(AND($AF{_r},$K{_r}<>""),$I{_r}*$K{_r},"")`
- L730: `=IF(AND($AF`
- L730: `=IF(AND($AF{_r},$K{_r}<>""),$J{_r}*$K{_r},"")`
- L743: `=IF(AND($AF`
- L743: `=IF(AND($AF{_r},$K{_r}<>"",$AW{_r}<>""),$AW{_r}*$K{_r},"")`
- L748: `=0), 0, IFERROR($T`
- L748: `=IF($AF`
- L748: `=IF($AF{_r}, IF(OR($T{_r}="", $T{_r}=0), 0, IFERROR($T{_r}/INDEX($K$1:$K${currency_table_last_row},MATCH($M{_r},$J$1:$J${currency_table_last_row},0))*INDEX($K$1:$K${currency_table_last_row},MATCH($N$1,$J$1:$J${currency_table_last_row},0)), "")), "")`
- L780: `=IF($AF`
- L780: `=IF($AF{_r}, IF($A{_r}=$B{_r}, $I{_r}*IFERROR(INDEX('Batch Settings'!$C$2:$C${batch_settings_last_row}, MATCH($A{_r}&"|"&"{volume}", 'Batch Settings'!$D$2:$D${batch_settings_last_row}, 0)), 0), $I{_r}*IFERROR(INDEX($AG:$AG, SUMPRODUCT(($A${first_data_row}:$A${last_data_row}=$A{_r})*($C${first_data_r`
- L844: `=IF($AF`
- L844: `=IF($AF{_r}, AND(NOT(ISERROR(MATCH($AV{_r}, $AU${first_data_row}:$AU${last_data_row}, 0))), SUMIFS($N${first_data_row}:$N${last_data_row}, $A${first_data_row}:$A${last_data_row}, $A{_r}, $B${first_data_row}:$B${last_data_row}, $C{_r})<>0), "")`
- L851: `=IF($AF`
- L851: `=IF($AF{_r}, IFERROR(LEFT($AE{_r}, FIND("@", SUBSTITUTE($AE{_r}, ".", "@", LEN($AE{_r})-LEN(SUBSTITUTE($AE{_r}, ".", ""))))-1), $AE{_r}), "")`
- L870: `=IF($AF`
- L870: `=IF($AF{_r}, IF($K{_r}<>"", INDEX('Scrap Factor'!$C$2:$C${scrap_last_row}, MATCH($K{_r}, 'Scrap Factor'!$A$2:$A${scrap_last_row}, 1)), ""), "")`
- L874: `=IF($AF`
- L874: `=IF($AF{_r}, IF($K{_r}<>"", INDEX('Scrap Factor'!$D$2:$D${scrap_last_row}, MATCH($K{_r}, 'Scrap Factor'!$A$2:$A${scrap_last_row}, 1)), ""), "")`
- L879: `="",TRUE,ROUND(SUMIFS($K$`
- L879: `=IF($AF`
- L879: `=IF($AF{_r},IF($K{_r}="",TRUE,ROUND(SUMIFS($K${first_data_row}:$K${last_data_row},$C${first_data_row}:$C${last_data_row},$C{_r})/COUNTIFS($C${first_data_row}:$C${last_data_row},$C{_r}),3)=ROUND($K{_r},3)),"")`
- L884: `=IF($AF`
- L884: `=IF($AF{_r}, IF(COUNTIFS($G${first_data_row}:$G${last_data_row}, "<>"&$G{_r}, $C${first_data_row}:$C${last_data_row}, $C{_r}) > 0, FALSE, TRUE), "")`
- L887: `=IF($AF`
- L887: `=IF($AF{_r}, AND($K{_r}<>0, $K{_r}<>""), "")`
- L888: `=IF($C`
- L888: `=IF($C{_r}<>"", COUNTIF($C$1:$C{_r}, $C{_r}), "")`
- L903: `=IF($AF`
- L903: `=IF($AF{_r}, $B{_r}&"_"&$AI{_r}, "")`
- L904: `=IF($AF`
- L904: `=IF($AF{_r}, $C{_r}&"_"&$AE{_r}, "")`
- L1025: `="",TRUE,ROUND(SUMIFS($K$`
- L1025: `=IF($AF`
- L1025: `=IF($AF{data_row_num},IF($K{data_row_num}="",TRUE,ROUND(SUMIFS($K${first_data_row}:$K${last_data_row},$C${first_data_row}:$C${last_data_row},$C{data_row_num})/COUNTIFS($C${first_data_row}:$C${last_data_row},$C{data_row_num}),3)=ROUND($K{data_row_num},3)),"")`
- L1030: `=IF($AF`
- L1030: `=IF($AF{data_row_num}, IF(COUNTIFS($G${first_data_row}:$G${last_data_row}, "<>"&$G{data_row_num}, $C${first_data_row}:$C${last_data_row}, $C{data_row_num}) > 0, FALSE, TRUE), "")`
- L1034: `=IF($C`
- L1034: `=IF($C{data_row_num}<>"", COUNTIF($C$1:$C{data_row_num}, $C{data_row_num}), "")`
- L1046: `=IF($AF`
- L1046: `=IF($AF{data_row_num}, AND(NOT(ISERROR(MATCH($AV{data_row_num}, $AU${first_data_row}:$AU${last_data_row}, 0))), SUMIFS($N${first_data_row}:$N${last_data_row}, $A${first_data_row}:$A${last_data_row}, $A{data_row_num}, $B${first_data_row}:$B${last_data_row}, $C{data_row_num})<>0), "")`
- L1060: `=IF($AF`
- L1060: `=IF($AF{data_row_num}, IF($K{data_row_num}<>"", INDEX('Scrap Factor'!$C$2:$C${scrap_last_row}, MATCH($K{data_row_num}, 'Scrap Factor'!$A$2:$A${scrap_last_row}, 1)), ""), "")`
- L1064: `=IF($AF`
- L1064: `=IF($AF{data_row_num}, IF($K{data_row_num}<>"", INDEX('Scrap Factor'!$D$2:$D${scrap_last_row}, MATCH($K{data_row_num}, 'Scrap Factor'!$A$2:$A${scrap_last_row}, 1)), ""), "")`
- L1082: `=IF($AF`
- L1082: `=IF($AF{data_row_num}, IF($A{data_row_num}=$B{data_row_num}, $I{data_row_num}*IFERROR(INDEX('Batch Settings'!$C$2:$C${batch_settings_last_row}, MATCH($A{data_row_num}&"|"&"1", 'Batch Settings'!$D$2:$D${batch_settings_last_row}, 0)), 0), $I{data_row_num}*IFERROR(INDEX($AG:$AG, SUMPRODUCT(($A${first_d`
- L1095: `=IF(AND($AF`
- L1095: `=IF(AND($AF{data_row_num},$K{data_row_num}<>"",$AW{data_row_num}<>""),$AW{data_row_num}*$K{data_row_num},"")`
- L1110: `=SUMIFS($AX$`
- L1110: `=SUMIFS($AX${first_data_row}:$AX${last_data_row}, $A${first_data_row}:$A${last_data_row}, $C10, $AH${first_data_row}:$AH${last_data_row}, "<>TRUE")`
- L1115: `=SUM(E10:E10)`
- L1116: `=SUM(G10:G10)`
- L1123: `=SUMPRODUCT(($AP$`
- L1123: `=SUMPRODUCT(($AP${first_data_row}:$AP${last_data_row}=1)*($C${first_data_row}:$C${last_data_row}<>""))`
- L1125: `=K10-K12`
- L1126: `=K14-K11`
- L1128: `=COUNTIFS($AO$`
- L1128: `=COUNTIFS($AO${first_data_row}:$AO${last_data_row},FALSE,$AF${first_data_row}:$AF${last_data_row},TRUE)`
- L1132: `=IFERROR($M$11/G`
- L1132: `=IFERROR($M$11/G{11},0)`
- L1143: `=SUMPRODUCT(($AQ$`
- L1143: `=SUMPRODUCT(($AQ${first_data_row}:$AQ${last_data_row}=FALSE)*{is_data_test})`
- L1146: `=SUMPRODUCT(($AR$`
- L1146: `=SUMPRODUCT(($AR${first_data_row}:$AR${last_data_row}=FALSE)*{is_data_test})`
- L1149: `=SUMPRODUCT(($AS$`
- L1149: `=SUMPRODUCT(($AS${first_data_row}:$AS${last_data_row}=FALSE)*{is_data_test})`
- L1152: `=SUMPRODUCT(($AT$`
- L1152: `=SUMPRODUCT(($AT${first_data_row}:$AT${last_data_row}=FALSE)*{is_data_test})`
- L1155: `="")+ISBLANK($E$`
- L1155: `=SUMPRODUCT(`
- L1155: `=SUMPRODUCT({is_data_test}*(($E${first_data_row}:$E${last_data_row}="")+ISBLANK($E${first_data_row}:$E${last_data_row})>0))`

## Assembly rules read from code

(see section 'Hand analysis' of 4_generation_logic_overview.md for cross-report rules: IFERROR wrapping, bounded ranges, row anchoring)
