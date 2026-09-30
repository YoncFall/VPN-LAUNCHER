# Build VPNLauncher: PyInstaller onedir + portable zip.
#
#   .\build-app.ps1                # version from vpn_launcher\__init__.py
#   .\build-app.ps1 -Version 2.0.1
#   .\build-app.ps1 -DistPath dist-alt   # build elsewhere (running exe locks
#                                        # dist\VPNLauncher); output goes to
#                                        # <DistPath>\VPNLauncher
#
# Output:
#   dist\VPNLauncher\              app folder (VPNLauncher.exe + _internal)
#   dist\VPN-LAUNCHER-<ver>.zip    portable archive (no runtime files)
#
# sing-box.exe (repo root) is copied next to VPNLauncher.exe: frozen
# paths.install_root() is the exe folder, so the engine must live there.

[CmdletBinding()]
param(
    [string]$Version = '',
    [string]$DistPath = ''
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
if (-not $DistPath) { $DistPath = Join-Path $root 'dist' }
elseif (-not [System.IO.Path]::IsPathRooted($DistPath)) { $DistPath = Join-Path $root $DistPath }
& $pyi --clean --noconfirm --distpath $DistPath (Join-Path $root 'VPNLauncher.spec')
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed with code $LASTEXITCODE" }

$dist = Join-Path $DistPath 'VPNLauncher'
if (-not (Test-Path (Join-Path $dist 'VPNLauncher.exe'))) {
    throw "VPNLauncher.exe missing after build (looked in $dist)"
}

# engine next to the exe (do NOT touch the engine file itself)
Copy-Item (Join-Path $root 'sing-box.exe') (Join-Path $dist 'sing-box.exe') -Force

# docs travel with the app: GPL requires license texts next to the bundled
# sing-box binary; they also go into the portable zip and the installer payload
foreach ($f in @('LICENSE', 'NOTICE.md', 'README.md')) {
    $p = Join-Path $root $f
    if (Test-Path $p) { Copy-Item $p $dist -Force }
}
$sbFile = Join-Path $dist 'sing-box.exe'
$sbSha = (Get-FileHash $sbFile -Algorithm SHA256).Hash.ToLower()
$sbVer = (& $sbFile version 2>&1 | Select-Object -First 1) -replace '^sing-box version\s*', ''
$notice = @"
sing-box - included binary component
====================================

This program bundles sing-box.exe, which is a separate work by SagerNet,
distributed under the GNU General Public License v3.0. It is NOT part of
the VPN LAUNCHER source code and is covered by its own license.

Version : $sbVer
SHA-256 : $sbSha
Source  : https://github.com/SagerNet/sing-box
License : https://github.com/SagerNet/sing-box/blob/dev/LICENSE

If you redistribute this program you must keep this file, keep sing-box
unmodified, and offer the corresponding source of both components:

  sing-box   : https://github.com/SagerNet/sing-box
  launcher   : https://github.com/YoncFall/VPN-LAUNCHER

You may obtain a copy of the GPL-3.0 from
<https://www.gnu.org/licenses/gpl-3.0.txt> or
<https://github.com/YoncFall/VPN-LAUNCHER/blob/main/LICENSE>.
"@
[System.IO.File]::WriteAllText((Join-Path $dist 'SING-BOX-LICENSE.txt'),
    ($notice -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))

# portable zip for users who prefer archiving
$zip = Join-Path $root ("dist\VPN-LAUNCHER-" + $Version + ".zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
# runtime files of a local run must never reach users: state.json carries
# a personal subscription URL - stage a clean copy before zipping
$zipStage = Join-Path $env:TEMP ("vpl-zip-" + $Version)
if (Test-Path $zipStage) { Remove-Item $zipStage -Recurse -Force }
New-Item -ItemType Directory -Path $zipStage | Out-Null
Copy-Item (Join-Path $dist '*') $zipStage -Recurse -Force
foreach ($f in @('state.json', 'config.json', 'vpn-launcher.log', 'singbox.log',
                 'singbox.log.err', 'cache.db', 'app.pid')) {
    $p = Join-Path $zipStage $f
    if (Test-Path $p) { Remove-Item $p -Force; Write-Host "  excluded from zip: $f" }
}
Compress-Archive -Path (Join-Path $zipStage '*') -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $zipStage -Recurse -Force

$dirSize = (Get-ChildItem $dist -Recurse -File | Measure-Object -Property Length -Sum).Sum
$exe = Get-Item (Join-Path $dist 'VPNLauncher.exe')
Write-Host ''
Write-Host ("app folder : {0}" -f $dist) -ForegroundColor Green
Write-Host ("app size   : {0:N1} MB" -f ($dirSize / 1MB))
Write-Host ("exe        : {0:N0} bytes" -f $exe.Length)
Write-Host ("portable   : {0} ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
