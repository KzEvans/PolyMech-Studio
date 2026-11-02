param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$WorkRoot,
    [string]$SyntheticData = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if (@(Get-Process -Name polymech-studio,polymech-backend,polymech-bridge -ErrorAction SilentlyContinue).Count) {throw 'Close desktop test processes first.'}
New-Item -ItemType Directory -Path $WorkRoot | Out-Null
$destination = Join-Path $env:LOCALAPPDATA 'Programs\PolyMech Studio'
$data = Join-Path $env:APPDATA 'PolyMechStudio'
$canary = Join-Path $data ('SYNTHETIC-installer-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $canary -Force | Out-Null
foreach ($name in @('raw.csv','settings.json','export.txt')) {
    [IO.File]::WriteAllText((Join-Path $canary $name), 'SYNTHETIC installer preservation sentinel')
}
if ($SyntheticData) {
    if (-not (Test-Path (Join-Path $SyntheticData 'polymech.sqlite'))) {throw 'Synthetic database is missing.'}
    Copy-Item $SyntheticData (Join-Path $canary 'synthetic-data') -Recurse
}
function Get-DataHashes {
    $hashes = [ordered]@{}
    Get-ChildItem $data -File -Recurse | Sort-Object FullName | ForEach-Object {
        $hashes[$_.FullName.Substring($data.Length)] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
    return $hashes
}
function Assert-DataUnchanged([string]$Stage) {
    if ((Get-DataHashes | ConvertTo-Json -Compress) -ne $script:beforeJson) {throw "Data changed during $Stage"}
}
function Install-TestBuild {
    $setup = Start-Process -FilePath $Installer -ArgumentList @('/S', ('/D=' + $destination)) -Wait -PassThru
    if ($setup.ExitCode -ne 0) {throw "NSIS installation failed: $($setup.ExitCode)"}
    if (-not (Test-Path (Join-Path $destination 'polymech-studio.exe'))) {throw 'Installed executable is missing.'}
}
$before = Get-DataHashes
$beforeJson = $before | ConvertTo-Json -Compress
Install-TestBuild
Assert-DataUnchanged 'same-version upgrade'
$uninstallers = @(Get-ChildItem $destination -File -Filter '*uninstall*.exe')
if ($uninstallers.Count -ne 1) {throw 'Cannot identify the installed NSIS uninstaller.'}
$uninstall = Start-Process -FilePath $uninstallers[0].FullName -ArgumentList '/S' -Wait -PassThru
if ($uninstall.ExitCode -ne 0) {throw "NSIS uninstall failed: $($uninstall.ExitCode)"}
$deadline = (Get-Date).AddSeconds(60)
while ((Test-Path (Join-Path $destination 'polymech-studio.exe')) -and (Get-Date) -lt $deadline) {Start-Sleep -Milliseconds 500}
if (Test-Path (Join-Path $destination 'polymech-studio.exe')) {throw 'Uninstall left the application executable.'}
Assert-DataUnchanged 'uninstall'
if (@(Get-Process -Name polymech-studio,polymech-backend,polymech-bridge -ErrorAction SilentlyContinue).Count) {throw 'Uninstall left application processes.'}
Install-TestBuild
Assert-DataUnchanged 'reinstall'
$result = [ordered]@{
    same_version_upgrade=$true
    uninstall=$true
    reinstall=$true
    data_files_preserved=$before.Count
    preserved_hashes=$before
    synthetic_canary=$canary
    installed_directory=$destination
    installer_sha256=(Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
}
$result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $WorkRoot 'installer.json')
Write-Output 'WINDOWS_INSTALL_UPGRADE_UNINSTALL_PASSED'
