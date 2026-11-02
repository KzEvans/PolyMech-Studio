param(
    [Parameter(Mandatory=$true)][string]$Exe,
    [string]$Python = '',
    [string]$WorkRoot = '',
    [int]$InspectionDelaySeconds = 0
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Python) {$Python = Join-Path (Split-Path $root) 'venv\Scripts\python.exe'}
if (-not $WorkRoot) {$WorkRoot = Join-Path $env:TEMP ('PolyMech-SYNTHETIC-' + [guid]::NewGuid().ToString('N'))}
if (@(Get-Process -Name polymech-studio -ErrorAction SilentlyContinue).Count -gt 0) {throw 'Close PolyMech Studio before running this self-test.'}
New-Item -ItemType Directory -Force "$WorkRoot\data", "$WorkRoot\downloads" | Out-Null
$env:POLYMECH_DATA_DIR = "$WorkRoot\data"
$env:POLYMECH_DOWNLOAD_DIR = "$WorkRoot\downloads"
$env:POLYMECH_DESKTOP_SELFTEST = "$WorkRoot\result.txt"
$env:POLYMECH_NO_KEYCHAIN = '1'
# Existing files are deliberate sentinels. Both download paths must avoid overwriting them.
Set-Content -Encoding ASCII "$WorkRoot\downloads\selftest_link.json" 'SYNTHETIC sentinel'
Set-Content -Encoding ASCII "$WorkRoot\downloads\selftest_blob.txt" 'SYNTHETIC sentinel'
$log = Join-Path $env:LOCALAPPDATA 'PolyMechStudio\logs\backend.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
[IO.File]::WriteAllText($log, '')
$process = $null
try {
    foreach ($kind in @('link', 'blob')) {
        $env:POLYMECH_SELFTEST_DOWNLOAD_KIND = $kind
        $process = Start-Process -FilePath $Exe -PassThru
        $deadline = (Get-Date).AddSeconds(240)
        $port = ''
        while ((Get-Date) -lt $deadline) {
            if ($process.HasExited) {throw 'Desktop shell exited before backend startup.'}
            if (Test-Path $log) {
                $matchesFound = Select-String -Path $log -Pattern 'on 127\.0\.0\.1:(\d+)'
                if ($matchesFound) {$port = $matchesFound[-1].Matches[0].Groups[1].Value; break}
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not $port) {throw 'Backend startup timed out.'}
        if ($kind -eq 'link') {
            & $Python "$root\scripts\desktop\smoke.py" "http://127.0.0.1:$port"
            if ($LASTEXITCODE -ne 0) {throw "Backend smoke failed: $LASTEXITCODE"}
            $second = Start-Process -FilePath $Exe -PassThru
            if (-not $second.WaitForExit(15000)) {throw 'Second shell did not exit (single-instance failure).'}
        }
        $extension = if ($kind -eq 'link') {'json'} else {'txt'}
        $download = "$WorkRoot\downloads\selftest_$kind (1).$extension"
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline -and -not (Test-Path $download)) {Start-Sleep -Milliseconds 500}
        if (-not (Test-Path $download)) {throw "Download did not finish: $download"}
        $backends = @(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'polymech-backend.exe' -and $_.CommandLine -like '*--control-stdin*'})
        $owned = @($backends.ProcessId)
        if ($InspectionDelaySeconds -gt 0) {
            Write-Output "Native window ready for inspection: $kind."
            Start-Sleep -Seconds ([Math]::Min($InspectionDelaySeconds, 60))
        }
        if (-not $process.CloseMainWindow()) {throw 'Could not close desktop window normally.'}
        if (-not $process.WaitForExit(100000)) {throw 'Desktop did not exit normally.'}
        Start-Sleep -Seconds 2
        foreach ($backendPid in $owned) {
            if (Get-Process -Id $backendPid -ErrorAction SilentlyContinue) {throw "Orphan backend: $backendPid"}
        }
        if (@(Get-Process -Name polymech-bridge -ErrorAction SilentlyContinue).Count -gt 0) {throw 'Orphan local Bridge.'}
        [IO.File]::WriteAllText($log, '')
    }
    foreach ($file in @('selftest_link.json', 'selftest_blob.txt')) {
        if ((Get-Content -Raw "$WorkRoot\downloads\$file").Trim() -ne 'SYNTHETIC sentinel') {throw "Sentinel was overwritten: $file"}
    }
    if ((Get-Content -Raw "$WorkRoot\downloads\selftest_link (1).json" | ConvertFrom-Json).status -ne 'ok') {throw 'Link download failed.'}
    if ((Get-Content -Raw "$WorkRoot\downloads\selftest_blob (1).txt") -notmatch 'PolyMech') {throw 'Blob download failed.'}
    Write-Output "SELFTEST_PASSED $WorkRoot"
} finally {
    if ($process -and -not $process.HasExited) {Stop-Process -Id $process.Id -Force}
    foreach ($name in @('POLYMECH_DATA_DIR','POLYMECH_DOWNLOAD_DIR','POLYMECH_DESKTOP_SELFTEST','POLYMECH_SELFTEST_DOWNLOAD_KIND','POLYMECH_NO_KEYCHAIN')) {Remove-Item "Env:\$name" -ErrorAction SilentlyContinue}
}
