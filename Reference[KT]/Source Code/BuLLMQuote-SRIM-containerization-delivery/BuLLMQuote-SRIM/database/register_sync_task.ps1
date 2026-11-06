# Registers (or re-registers) the Windows Scheduled Task that keeps
# BuLLMQuote-SRIM's local database/ folder synced from CAM's live DuckDB
# files. Read-only on CAM's side -- see sync_from_cam.py's own docstring.
#
# Run this once, manually, from an elevated or normal PowerShell prompt:
#   powershell -ExecutionPolicy Bypass -File register_sync_task.ps1
#
# To remove the task later:
#   Unregister-ScheduledTask -TaskName "BuLLMQuoteSRIM-DuckDB-Sync" -Confirm:$false

$TaskName = "BuLLMQuoteSRIM-DuckDB-Sync"
$ScriptPath = Join-Path $PSScriptRoot "sync_from_cam.py"
$PythonExe = (Get-Command python).Source

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $PSScriptRoot
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Read-only hourly sync of CAM's live DuckDB files into BuLLMQuote-SRIM's own database/ folder. Never writes back to CAM." | Out-Null

Write-Host "Registered scheduled task '$TaskName', running sync_from_cam.py hourly."
Write-Host "Check status with: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
