param(
    [string]$ToolsRoot = "$env:LOCALAPPDATA\PolyMechBuild\tools",
    [string]$Python = "$env:LOCALAPPDATA\PolyMechBridge\venv\Scripts\python.exe",
    [switch]$SkipChecks
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:CARGO_HOME = Join-Path $ToolsRoot 'rust\cargo'
$env:RUSTUP_HOME = Join-Path $ToolsRoot 'rust\rustup'
$env:RUSTUP_TOOLCHAIN = '1.99.1-x86_64-pc-windows-msvc'
$node = Join-Path $ToolsRoot 'node-v24.22.1-win-x64'
$uv = Join-Path $ToolsRoot 'uv\uv.exe'
$pnpm = Join-Path $ToolsRoot 'pnpm\node_modules\.bin\pnpm.cmd'
$env:PATH = (Join-Path $ToolsRoot 'uv') + ';' + $node + ';' + (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:PATH
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Split-Path $root) 'venv'
$env:UV_CACHE_DIR = Join-Path (Split-Path $root) 'cache\uv'
# Import the installed x64 compiler environment without changing the user's global PATH.
$vcvars = Join-Path (Split-Path $root) 'BuildTools\VC\Auxiliary\Build\vcvars64.bat'
$compilerEnv = & cmd.exe /d /s /c ('"' + $vcvars + '" >nul && set')
if ($LASTEXITCODE -ne 0) {throw "vcvars64 failed: $LASTEXITCODE"}
foreach ($line in $compilerEnv) {
    if ($line -match '^([^=]+)=(.*)$') {[Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')}
}
function Invoke-Checked([string]$File, [string[]]$Arguments) {
    # Windows PowerShell 5.1 turns redirected native stderr into ErrorRecord objects.
    # Progress on stderr is valid; only the native exit code determines failure.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $File @Arguments 2>&1 | ForEach-Object { $_.ToString() }
        $nativeExitCode = $LASTEXITCODE
    } finally {$ErrorActionPreference = $previous}
    if ($nativeExitCode -ne 0) {throw "$File failed with exit code $nativeExitCode"}
}
$started = Get-Date
Push-Location $root
try {
    Invoke-Checked $uv @('sync', '--locked', '--group', 'windows-bridge', '--python', $Python, '--no-python-downloads')
    $pythonExe = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\python.exe'
    Invoke-Checked $pythonExe @('-c', "import platform,struct,sysconfig; print(platform.python_version(), sysconfig.get_platform(), struct.calcsize('P')*8); assert sysconfig.get_platform()=='win-amd64'")
    Invoke-Checked $pnpm @('-C', 'apps\web', 'install', '--frozen-lockfile')
    Invoke-Checked $pnpm @('-C', 'apps\desktop', 'install', '--frozen-lockfile')
    if (-not $SkipChecks) {
        Invoke-Checked $uv @('run', '--locked', '--group', 'windows-bridge', 'pytest')
        Invoke-Checked $pnpm @('-C', 'apps\web', 'test', '--run', '--maxWorkers=1')
    }
    Invoke-Checked $pnpm @('-C', 'apps\web', 'build')
    Push-Location (Join-Path $root 'apps\desktop')
    try {
        Invoke-Checked $pythonExe @('-m', 'PyInstaller', '--noconfirm', '--log-level', 'WARN', '--distpath', "$root\build\desktop\backend", '--workpath', "$root\build\desktop\work-backend", 'backend.spec')
        Invoke-Checked $pythonExe @('-m', 'PyInstaller', '--noconfirm', '--log-level', 'WARN', '--distpath', "$root\build\desktop\bridge", '--workpath', "$root\build\desktop\work-bridge", 'bridge.spec')
    } finally {Pop-Location}
    New-Item -ItemType Directory -Force "$root\build\desktop\licenses" | Out-Null
    Invoke-Checked $pythonExe @('scripts\desktop\licenses.py', "$root\build\desktop\licenses")
    Invoke-Checked $pnpm @('-C', 'apps\desktop', 'tauri', 'build', '--target', 'x86_64-pc-windows-msvc', '--bundles', 'nsis')
    $artifacts = @(Get-ChildItem "$root\apps\desktop\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\nsis\*.exe")
    if ($artifacts.Count -eq 0) {throw 'No NSIS installer was produced.'}
    $manifest = foreach ($file in $artifacts) {
        [ordered]@{name=$file.Name; bytes=$file.Length; sha256=(Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 "$root\build\desktop\artifacts.json"
    Write-Output "BUILD_PASSED elapsed=$(((Get-Date)-$started).TotalSeconds) seconds"
    $manifest | ConvertTo-Json -Depth 4
} finally {Pop-Location}
