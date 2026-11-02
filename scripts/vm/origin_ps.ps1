# Diagnostic: list Origin processes and Phase 0 outputs (read-only).
Get-CimInstance Win32_Process -Filter "Name='Origin64.exe'" | Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine | Format-Table -AutoSize | Out-String -Width 200
$w = Join-Path $env:LOCALAPPDATA "PolyMechBridge\work\phase0"
if (Test-Path $w) { Get-ChildItem $w | Select-Object Name,Length,LastWriteTime | Format-Table -AutoSize | Out-String -Width 200 }
