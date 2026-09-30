# Build VPN-LAUNCHER-<version>-Setup.exe: single-file installer with the
# whole app embedded as payload.zip inside the exe.
#
#   .\build-app.ps1            # first: dist\VPNLauncher must exist
#   .\build-installer.ps1
#   .\build-installer.ps1 -AppDist dist-alt\VPNLauncher   # pack a staged build
#
# What the user gets: download ONE file, double-click, install. No admin
# rights (installs to %LOCALAPPDATA%\Programs\VPNLauncher), no internet,
# nothing to download - Python/PySide6 runtime and sing-box.exe are inside.
# The same exe copied to the app folder works as uninstaller.

[CmdletBinding()]
param(
    [string]$Version = '',
    [string]$OutDir = '',
    [string]$AppDist = ''   # app folder to pack (default dist\VPNLauncher)
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$insDir = Join-Path $root 'installer'
if (-not $OutDir) { $OutDir = Join-Path $root 'dist' }

# ---------- version (same parse as build-app.ps1) ----------

if (-not $Version) {
    $init = [System.IO.File]::ReadAllText((Join-Path $root 'vpn_launcher\__init__.py'))
    $m = [regex]::Match($init, '__version__\s*=\s*"(\d+\.\d+\.\d+)')
    if (-not $m.Success) { throw 'Cannot read version from vpn_launcher\__init__.py' }
    $Version = $m.Groups[1].Value
}
Write-Host "version: $Version"

$stage = Join-Path $env:TEMP ("vpl-setup-" + $Version)
$payload = Join-Path $env:TEMP ("vpl-payload-" + $Version + ".zip")
$setup = Join-Path $OutDir ("VPN-LAUNCHER-" + $Version + "-Setup.exe")

# ---------- checks ----------

foreach ($f in @('Setup.cs', 'app.ico', 'app.manifest')) {
    if (-not (Test-Path (Join-Path $insDir $f))) { throw "installer\$f not found" }
}
if (-not $AppDist) { $AppDist = Join-Path $root 'dist\VPNLauncher' }
elseif (-not [System.IO.Path]::IsPathRooted($AppDist)) { $AppDist = Join-Path $root $AppDist }
if (-not (Test-Path (Join-Path $AppDist 'VPNLauncher.exe'))) {
    throw 'VPNLauncher.exe not found in the app folder. Run .\build-app.ps1 first.'
}
$sing = Join-Path $root 'sing-box.exe'
if (-not (Test-Path $sing)) { throw 'sing-box.exe not found in repo root.' }

# ---------- stage: copy app tree ----------

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage, $OutDir -Force | Out-Null
if (Test-Path $payload) { Remove-Item $payload -Force }
if (Test-Path $setup) { Remove-Item $setup -Force }

Copy-Item (Join-Path $appDist '*') $stage -Recurse -Force
Copy-Item $sing (Join-Path $stage 'sing-box.exe') -Force   # engine at app root

# runtime leftovers must never reach users (logs/state of a local test run)
foreach ($f in @('state.json', 'config.json', 'vpn-launcher.log', 'singbox.log',
                 'singbox.log.err', 'cache.db', 'app.pid')) {
    $p = Join-Path $stage $f
    if (Test-Path $p) { Remove-Item $p -Force; Write-Host "  excluded runtime file: $f" }
}

# docs next to the app
foreach ($f in @('LICENSE', 'NOTICE.md', 'README.md')) {
    $p = Join-Path $root $f
    if (Test-Path $p) { Copy-Item $p $stage }
}

# ---------- license notice: written by build-app.ps1, just verify ----------

$sbExe = Join-Path $stage 'sing-box.exe'
$sbSha = (Get-FileHash $sbExe -Algorithm SHA256).Hash.ToLower()
$sbVer = (& $sbExe version 2>&1 | Select-Object -First 1) -replace '^sing-box version\s*', ''
if (-not (Test-Path (Join-Path $stage 'SING-BOX-LICENSE.txt'))) {
    throw 'SING-BOX-LICENSE.txt missing in dist. Re-run .\build-app.ps1 (it writes the notice).'
}

# ---------- payload zip ----------

Write-Host ''
Write-Host 'packing payload...'
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $payload -CompressionLevel Optimal

# ---------- Setup.cs with the actual version (UTF8 + BOM for csc) ----------

$setupSrc = [System.IO.File]::ReadAllText((Join-Path $insDir 'Setup.cs'))
$vm = [regex]::Match($setupSrc, 'const string Version = "[0-9]+\.[0-9]+\.[0-9]+";')
if (-not $vm.Success) { throw 'Version const not found in Setup.cs' }
$stamped = $setupSrc.Replace($vm.Value, ('const string Version = "' + $Version + '";'))
$stagedSrc = Join-Path $stage 'Setup.cs'
[System.IO.File]::WriteAllText($stagedSrc, $stamped, (New-Object System.Text.UTF8Encoding($true)))

# ---------- compile setup.exe ----------

$csc = $null
foreach ($r in @(($env:WINDIR + '\Microsoft.NET\Framework64'), ($env:WINDIR + '\Microsoft.NET\Framework'))) {
    $cand = Join-Path $r 'v4.0.30319\csc.exe'
    if (Test-Path $cand) { $csc = $cand; break }
}
if (-not $csc) { throw 'csc.exe not found. .NET Framework 4.x required.' }

Write-Host 'compiling installer...'
$cargs = @(
    '/nologo',
    '/target:winexe',
    '/optimize+',
    '/platform:anycpu',
    '/reference:System.Core.dll',
    '/reference:System.Drawing.dll',
    '/reference:System.Windows.Forms.dll',
    '/reference:System.IO.Compression.dll',
    '/reference:System.IO.Compression.FileSystem.dll',
    "/win32icon:$(Join-Path $insDir 'app.ico')",
    "/win32manifest:$(Join-Path $insDir 'app.manifest')",
    "/resource:$payload,payload.zip",
    "/resource:$(Join-Path $insDir 'app.ico'),appicon.ico",
    "/out:$setup",
    $stagedSrc
)
$log = & $csc @cargs 2>&1
if ($LASTEXITCODE -ne 0) {
    $log | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "csc failed with code $LASTEXITCODE"
}
$log | Where-Object { $_ } | ForEach-Object { Write-Host $_ }

# ---------- result checks ----------

$fi = Get-Item $setup
$bytes = [System.IO.File]::ReadAllBytes($setup)
$peOff = [System.BitConverter]::ToInt32($bytes, 0x3C)
$subsys = [System.BitConverter]::ToUInt16($bytes, $peOff + 0x5C)
if ($subsys -ne 2) { throw "Subsystem must be GUI (2), got $subsys" }

Add-Type -Namespace InsChk -Name Ico -MemberDefinition @'
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern uint ExtractIconEx(string file, int index, IntPtr[] large, IntPtr[] small, uint count);
'@
$lg = New-Object IntPtr[] 1
$sm = New-Object IntPtr[] 1
$ic = [InsChk.Ico]::ExtractIconEx($setup, 0, $lg, $sm, 1)
if ($ic -lt 1) { throw 'Icon not embedded into setup.exe' }

$zipLen = (Get-Item $payload).Length
if ($fi.Length -lt $zipLen) { throw "Suspiciously small exe: $($fi.Length) vs zip $zipLen" }

# payload must contain the app, the engine and the python runtime
Add-Type -AssemblyName System.IO.Compression.FileSystem
$check = [System.IO.Compression.ZipFile]::OpenRead($payload)
$names = @($check.Entries | ForEach-Object { $_.FullName -replace '\\', '/' })
$check.Dispose()
$need = @('VPNLauncher.exe', 'sing-box.exe', 'SING-BOX-LICENSE.txt')
$miss = $need | Where-Object { $names -notcontains $_ }
if ($miss) { throw "Payload misses: $($miss -join ', ')" }
if (-not ($names | Where-Object { $_ -like '_internal/*' })) {
    throw 'Payload misses _internal (python runtime)'
}

Write-Host ''
Write-Host ('setup    : {0}' -f $fi.FullName) -ForegroundColor Green
Write-Host ('size     : {0:N0} bytes ({1:N1} MB)' -f $fi.Length, ($fi.Length / 1MB))
Write-Host ('sing-box : {0}  sha256 {1}' -f $sbVer, $sbSha.Substring(0, 32))
Write-Host ('payload  : {0} entries' -f $names.Count)

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $payload -Force -ErrorAction SilentlyContinue
