# Dynamic check in native Excel: open the report the app downloaded, read the Summary, change ONE typed input (a part price),
# let Excel recalculate, read the Summary again. The file on disk is never saved (a copy is opened).
# usage: powershell -File excel_dynamic_check.ps1 -Report <path to the downloaded CBOM_Report .xlsx>
param([Parameter(Mandatory = $true)][string]$Report)
$ErrorActionPreference = 'Stop'
$work = Join-Path $env:TEMP ('cam-dynamic-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$copy = Join-Path $work 'report-copy.xlsx'
Copy-Item -LiteralPath $Report -Destination $copy
$sheetInput = '7.0 CBOM VL-1'
$cellInput = 'L26'                      # Price #1 (Original) of AC0603KRX7R9BB104, a typed number (0.0046 USD)
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.ScreenUpdating = $false
$result = [ordered]@{}
try {
  $wb = $xl.Workbooks.Open($copy, 0, $false)
  $xl.Calculation = -4105   # xlCalculationAutomatic: a change recalculates the dependents by itself
  $sum = $wb.Worksheets.Item('Summary')
  $inp = $wb.Worksheets.Item($sheetInput).Range($cellInput)
  $watch = @('E4', 'E5', 'G4', 'G5')
  $before = @{}; foreach ($a in $watch) { $before[$a] = $sum.Range($a).Value2 }
  $old = $inp.Value2
  $inp.Value2 = [double]$old * 10          # ten times the price
  $xl.CalculateFull()
  $after = @{}; foreach ($a in $watch) { $after[$a] = $sum.Range($a).Value2 }
  $result.input = "$sheetInput!$cellInput"
  $result.input_before = $old
  $result.input_after = [double]$old * 10
  foreach ($a in $watch) { $result["summary_$a"] = [ordered]@{ before = $before[$a]; after = $after[$a]; changed = ($before[$a] -ne $after[$a]) } }
  $wb.Close($false)
} finally {
  $xl.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null
  Remove-Item -LiteralPath $work -Recurse -Force
}
$result | ConvertTo-Json -Depth 4
