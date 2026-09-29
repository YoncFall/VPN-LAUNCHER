# Build VPNLauncher: PyInstaller onedir + portable zip.
#
#   .\build-app.ps1                # version from vpn_launcher\__init__.py
#   .\build-app.ps1 -Version 2.0.0
#
# Output:
#   dist\VPNLauncher\              app folder (VPNLauncher.exe + _internal)
#   dist\VPN-LAUNCHER-<ver>.zip    portable archive
#
# sing-box.exe (repo root) is copied next to VPNLauncher.exe: frozen
# paths.install_root() is the exe folder, so the engine must live there.

[CmdletBinding()]
param(
    [string]$Version = ''
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

if (-not $Version) {
    $init = [System.IO.File]::ReadAllText((Join-Path $root 'vpn_launcher\__init__.py'))
    $m = [regex]::Match($init, '__version__\s*=\s*"(\d+\.\d+\.\d+)')
    if (-not $m.Success) { throw 'Cannot read version from vpn_launcher\__init__.py' }
    $Version = $m.Groups[1].Value
}
Write-Host "version: $Version"

$pyi = Join-Path $root 'venv\Scripts\pyinstaller.exe'
if (-not (Test-Path $pyi)) {
    throw 'venv\Scripts\pyinstaller.exe not found. Run: venv\Scripts\pip install -r requirements.txt'
}
if (-not (Test-Path (Join-Path $root 'sing-box.exe'))) { throw 'sing-box.exe not found in repo root.' }
if (-not (Test-Path (Join-Path $root 'installer\app.ico'))) { throw 'installer\app.ico not found.' }

$env:VPN_VERSION = $Version
& $pyi --clean --noconfirm (Join-Path $root 'VPNLauncher.spec')
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed with code $LASTEXITCODE" }

$dist = Join-Path $root 'dist\VPNLauncher'
if (-not (Test-Path (Join-Path $dist 'VPNLauncher.exe'))) {
    throw 'dist\VPNLauncher\VPNLauncher.exe missing after build'
}

# engine next to the exe (do NOT touch the engine file itself)
Copy-Item (Join-Path $root 'sing-box.exe') (Join-Path $dist 'sing-box.exe') -Force

# portable zip for users who prefer archiving
$zip = Join-Path $root ("dist\VPN-LAUNCHER-" + $Version + ".zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $dist '*') -DestinationPath $zip -CompressionLevel Optimal

$dirSize = (Get-ChildItem $dist -Recurse -File | Measure-Object -Property Length -Sum).Sum
$exe = Get-Item (Join-Path $dist 'VPNLauncher.exe')
Write-Host ''
Write-Host ("app folder : {0}" -f $dist) -ForegroundColor Green
Write-Host ("app size   : {0:N1} MB" -f ($dirSize / 1MB))
Write-Host ("exe        : {0:N0} bytes" -f $exe.Length)
Write-Host ("portable   : {0} ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
