param(
    [Parameter(Mandatory=$true)][ValidateSet('msvc', 'user')][string]$Stage,
    [Parameter(Mandatory=$true)][string]$ToolsRoot,
    [string]$BuildRoot = 'C:\PolyMechBuild',
    [string]$Account = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$downloadClient = New-Object Net.WebClient
if ($env:HTTPS_PROXY) {$downloadClient.Proxy = New-Object Net.WebProxy($env:HTTPS_PROXY)}
$downloads = Join-Path $ToolsRoot 'downloads'
New-Item -ItemType Directory -Force $downloads | Out-Null

function Get-VerifiedFile([string]$Url, [string]$Destination, [string]$Sha256) {
    if (-not (Test-Path $Destination)) {
        Write-Output "Downloading $(Split-Path -Leaf $Destination)"
        $downloadClient.DownloadFile($Url, $Destination)
    }
    $actual = (Get-FileHash -Algorithm SHA256 $Destination).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256.ToLowerInvariant()) {throw "SHA256 mismatch: $Destination"}
    Write-Output "Verified $(Split-Path -Leaf $Destination): $actual"
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

if ($Stage -eq 'msvc') {
    if ((Get-PSDrive C).Free -lt 18GB) {throw 'MSVC setup requires at least 18 GiB free before installation and build caches.'}
    $installer = Join-Path $downloads 'vs_BuildTools-17.14.37824.6.exe'
    Get-VerifiedFile 'https://download.visualstudio.microsoft.com/download/pr/4bc08c27-bd31-470c-9a30-3b62707fbf0f/4aad1082e180f558598c346eb105b465b4908148cb9f7f0511aa1105620e0c30/vs_BuildTools.exe' $installer '4aad1082e180f558598c346eb105b465b4908148cb9f7f0511aa1105620e0c30'
    $target = Join-Path $BuildRoot 'BuildTools'
    $argsList = @('--quiet', '--wait', '--norestart', '--nocache', '--installPath', $target,
        '--add', 'Microsoft.VisualStudio.Workload.VCTools',
        '--add', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
        '--add', 'Microsoft.VisualStudio.Component.Windows11SDK.26100')
    $proc = Start-Process -FilePath $installer -ArgumentList $argsList -Wait -PassThru
    Write-Output "VS setup exit code: $($proc.ExitCode)"
    if ($proc.ExitCode -notin @(0, 3010)) {throw "VS setup failed: $($proc.ExitCode)"}
    if ($Account) {
        Invoke-Checked 'icacls.exe' @($BuildRoot, '/grant', ($Account + ':(OI)(CI)M'))
    }
    if ($proc.ExitCode -eq 3010) {
        New-Item -ItemType Directory -Force (Join-Path $ToolsRoot 'logs') | Out-Null
        'MSVC setup returned 3010: installed, restart pending. Do not restart automatically.' |
            Set-Content -Encoding UTF8 (Join-Path $ToolsRoot 'logs\restart-pending.txt')
        Write-Output 'MSVC installed with restart pending. Verify compilation before deciding whether a restart is needed.'
    } else {
        Write-Output 'MSVC installation completed without a restart request.'
    }
    exit 0
}

$nodeVersion = 'v24.22.1'
$nodeZip = Join-Path $downloads "node-$nodeVersion-win-x64.zip"
$sums = $downloadClient.DownloadString("https://nodejs.org/dist/$nodeVersion/SHASUMS256.txt")
$line = ($sums -split "`n" | Where-Object {$_ -match "  node-$nodeVersion-win-x64.zip\s*$"} | Select-Object -First 1)
if (-not $line) {throw 'Node archive checksum is absent from the official manifest.'}
Get-VerifiedFile "https://nodejs.org/dist/$nodeVersion/node-$nodeVersion-win-x64.zip" $nodeZip ($line -split '\s+')[0]
$nodeRoot = Join-Path $ToolsRoot "node-$nodeVersion-win-x64"
if (-not (Test-Path (Join-Path $nodeRoot 'node.exe'))) {Expand-Archive $nodeZip $ToolsRoot -Force}
$env:PATH = $nodeRoot + ';' + $env:PATH
Invoke-Checked (Join-Path $nodeRoot 'node.exe') @('--version')

$pnpmRoot = Join-Path $ToolsRoot 'pnpm'
Invoke-Checked (Join-Path $nodeRoot 'npm.cmd') @('install', '--prefix', $pnpmRoot, '--no-audit', '--no-fund', 'pnpm@12.14.0')
Invoke-Checked (Join-Path $pnpmRoot 'node_modules\.bin\pnpm.cmd') @('--version')

$uvZip = Join-Path $downloads 'uv-0.13.6-win-x64.zip'
Get-VerifiedFile 'https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-pc-windows-msvc.zip' $uvZip 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f'
$uvRoot = Join-Path $ToolsRoot 'uv'
if (-not (Test-Path (Join-Path $uvRoot 'uv.exe'))) {Expand-Archive $uvZip $uvRoot -Force}
Invoke-Checked (Join-Path $uvRoot 'uv.exe') @('--version')

$env:CARGO_HOME = Join-Path $ToolsRoot 'rust\cargo'
$env:RUSTUP_HOME = Join-Path $ToolsRoot 'rust\rustup'
$env:RUSTUP_TOOLCHAIN = '1.99.1-x86_64-pc-windows-msvc'
$rustup = Join-Path $downloads 'rustup-init.exe'
$rustUrl = 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe'
$rustHash = ($downloadClient.DownloadString($rustUrl + '.sha256') -split '\s+')[0]
Get-VerifiedFile $rustUrl $rustup $rustHash
$cargo = Join-Path $env:CARGO_HOME 'bin\cargo.exe'
if (-not (Test-Path $cargo)) {
    Invoke-Checked $rustup @('-y', '--no-modify-path', '--profile', 'minimal', '--default-host', 'x86_64-pc-windows-msvc', '--default-toolchain', 'none')
}
Invoke-Checked (Join-Path $env:CARGO_HOME 'bin\rustup.exe') @('toolchain', 'install', '1.99.1-x86_64-pc-windows-msvc', '--profile', 'minimal', '--component', 'rustfmt', '--force-non-host')
Invoke-Checked $cargo @('--version')
Invoke-Checked (Join-Path $env:CARGO_HOME 'bin\rustc.exe') @('-vV')
Write-Output 'User build tools installed without changing the global PATH.'
