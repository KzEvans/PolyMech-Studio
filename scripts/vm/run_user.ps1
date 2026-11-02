# Run a program once in the console user's interactive session with no visible
# window: a one-shot scheduled task (registered by SYSTEM, LogonType Interactive)
# starts pythonw.exe hidden_run.py, which runs the target with CREATE_NO_WINDOW
# and writes stdout/stderr to $Log and the exit code to "$Log.rc".
# Params: $User, $Pythonw, $Runner, $Log, $CmdArgs (pre-quoted), $TimeoutS
$ErrorActionPreference = "Stop"
$name = "PolyMech_OneShot_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
Remove-Item -Force -ErrorAction SilentlyContinue $Log, "$Log.rc"
$action = New-ScheduledTaskAction -Execute $Pythonw -Argument "`"$Runner`" `"$Log`" $CmdArgs"
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds ([int]$TimeoutS + 60))
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
try {
    Start-ScheduledTask -TaskName $name
    $deadline = (Get-Date).AddSeconds([int]$TimeoutS)
    while (-not (Test-Path "$Log.rc") -and (Get-Date) -lt $deadline) { Start-Sleep 1 }
    if (-not (Test-Path "$Log.rc")) { "run_user: timed out after $TimeoutS s" }
} finally {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
}
