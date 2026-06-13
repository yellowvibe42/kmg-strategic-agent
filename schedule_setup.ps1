# schedule_setup.ps1
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $python = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\*\python.exe" -ErrorAction SilentlyContinue |
              Select-Object -First 1 -ExpandProperty FullName
}
if (-not $python) { Write-Host "Python not found"; exit 1 }

$agentDir = "C:\Users\user\Desktop\MTM_KMG\kmg_agent"
$logFile  = "$agentDir\data\scheduler.log"
$py       = $python
$main     = "$agentDir\main.py"

Write-Host "Python: $py"

schtasks /Create /F /TN "KMG_Agent_Collect"      /TR "`"$py`" -X utf8 `"$main`" --collect"      /SC DAILY  /ST 07:00 /RL LIMITED
schtasks /Create /F /TN "KMG_Agent_Briefing"     /TR "`"$py`" -X utf8 `"$main`" --all"          /SC DAILY  /ST 07:30 /RL LIMITED
schtasks /Create /F /TN "KMG_Agent_Alerts"       /TR "`"$py`" -X utf8 `"$main`" --alerts"       /SC HOURLY /MO 2     /RL LIMITED
schtasks /Create /F /TN "KMG_Agent_WeeklyReport" /TR "`"$py`" -X utf8 `"$main`" --report"       /SC WEEKLY /D MON /ST 08:00 /RL LIMITED

Write-Host "Done. Check Task Scheduler for KMG_Agent_* tasks."
Write-Host "Log: $logFile"
