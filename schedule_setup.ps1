# ============================================================================
# schedule_setup.ps1 — register run_pipeline.bat in Windows Task Scheduler (3x/day).
#   PowerShell version (schtasks.exe mishandles the spaced path in this folder).
#
#   Run ONCE:   powershell -ExecutionPolicy Bypass -File schedule_setup.ps1
#   Remove:     powershell -File schedule_setup.ps1 -Remove
#   Test one:   Start-ScheduledTask -TaskName refresh-14 -TaskPath "\StockKG\"
#   Status:     Get-ScheduledTaskInfo -TaskName refresh-14 -TaskPath "\StockKG\"
# ============================================================================
param([switch]$Remove)

$bat = Join-Path $PSScriptRoot "run_pipeline.bat"
$times = @(@("08", "08:00"), @("14", "14:00"), @("20", "20:00"))

if ($Remove) {
    foreach ($p in $times) { Unregister-ScheduledTask -TaskName "refresh-$($p[0])" -TaskPath "\StockKG\" -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Output "Removed StockKG refresh tasks."
    return
}

if (-not (Test-Path $bat)) { Write-Error "run_pipeline.bat not found at $bat"; exit 1 }

foreach ($p in $times) {
    $name = "refresh-$($p[0])"
    $action  = New-ScheduledTaskAction -Execute $bat
    $trigger = New-ScheduledTaskTrigger -Daily -At $p[1]
    # run only while logged on, don't fight battery, start if a scheduled run was missed
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
    Register-ScheduledTask -TaskName $name -TaskPath "\StockKG\" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Output "registered: StockKG\$name at $($p[1])"
}
Write-Output ""
Write-Output "Done. Runs only while PC is on; skips cleanly if Docker/Neo4j is off. Logs: logs\refresh.log"
