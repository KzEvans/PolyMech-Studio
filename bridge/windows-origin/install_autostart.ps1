# Register "PolyMech Origin Bridge" to start hidden at the console user's logon, and start it now.
# Run from macOS (as SYSTEM via prlctl):  scripts/vm/run_ps.sh bridge/windows-origin/install_autostart.ps1 'Root=%BRIDGE%' 'User=<console user>'
# Undo:  scripts/vm/run_ps.sh bridge/windows-origin/uninstall_autostart.ps1
$ErrorActionPreference = "Stop"
$name = "PolyMech Origin Bridge"
$pyw = Join-Path $Root "venv\Scripts\pythonw.exe"
$app = Join-Path $Root "app"
if (-not (Test-Path $pyw)) { throw "bridge venv missing: run deploy_bridge.sh first" }
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m polymech_bridge" -WorkingDirectory $app
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $name
Start-Sleep 8
"task: " + (Get-ScheduledTask -TaskName $name).State
$ep = Join-Path $Root "bridge-endpoint.txt"
if (Test-Path $ep) { "endpoint: " + (Get-Content $ep) }
