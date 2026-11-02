# Provision an isolated x64 CPython + venv for the PolyMech Origin Bridge.
# Everything lives under %LOCALAPPDATA%\PolyMechBridge; nothing global is changed.
# Usage from macOS: scripts/vm/run_ps.sh bridge/windows-origin/setup_env.ps1 'Root=%BRIDGE%'
$ErrorActionPreference = "Stop"
if (-not $PyVersion) { $PyVersion = "3.12" }
# $Root is passed by scripts/vm/run_ps.sh (which runs as SYSTEM); default for manual runs.
$root = if ($Root) { $Root } else { Join-Path $env:LOCALAPPDATA "PolyMechBridge" }
$uvDir = Join-Path $root "uv"
New-Item -ItemType Directory -Force -Path $root, $uvDir | Out-Null
$uv = Join-Path $uvDir "uv.exe"
if (-not (Test-Path $uv)) {
    # x86_64 build: runs under Windows-on-ARM x64 emulation, same as Origin64.exe
    $zip = Join-Path $root "uv.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip
    Expand-Archive -Force -Path $zip -DestinationPath $uvDir
    Remove-Item $zip
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root "python"
$env:UV_CACHE_DIR = Join-Path $root "uv-cache"
& $uv --version
& $uv python install --no-bin "cpython-$PyVersion-windows-x86_64-none"
$venv = Join-Path $root "venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $uv venv --python "cpython-$PyVersion-windows-x86_64-none" $venv
}
$req = Join-Path $root "app\requirements.txt"
& $uv pip install --python (Join-Path $venv "Scripts\python.exe") -r $req
& (Join-Path $venv "Scripts\python.exe") -c "import sys,platform,struct; print(sys.version); print('machine', platform.machine(), 'ptr', struct.calcsize('P')*8)"
