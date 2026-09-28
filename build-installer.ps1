# Сборка установщика VPN-LAUNCHER-<версия>-Setup.exe
#
#   .\build-installer.ps1 -Version 1.0.3
#
# В один exe запекается zip с файлами программы, поэтому пользователю достаточно
# скачать один файл и запустить его. Права администратора не нужны: программа
# ставится в профиль пользователя. Скрипту нужен только .NET Framework.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$SingBox = '',
    [string]$Launcher = '',
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$srcDir = Join-Path $root 'src'
$insDir = Join-Path $root 'installer'
if (-not $OutDir) { $OutDir = Join-Path $root 'dist' }

$stage = Join-Path $env:TEMP ("vpl-setup-" + $Version)
$payload = Join-Path $env:TEMP ("vpl-payload-" + $Version + ".zip")
$setup = Join-Path $OutDir ("VPN-LAUNCHER-" + $Version + "-Setup.exe")

# ---------- проверки ----------

if (-not (Test-Path (Join-Path $insDir 'Setup.cs'))) { throw "Нет $insDir\Setup.cs" }
if (-not (Test-Path (Join-Path $srcDir 'VPN.ps1'))) { throw "Нет $srcDir\VPN.ps1" }
if (-not (Test-Path (Join-Path $srcDir 'app.ico'))) { throw "Нет $srcDir\app.ico" }

if (-not $SingBox) {
    $guess = Join-Path $env:LOCALAPPDATA 'MyVPN\sing-box.exe'
    if (Test-Path $guess) { $SingBox = $guess }
}
if (-not (Test-Path $SingBox)) { throw 'Нет sing-box.exe. Укажи -SingBox.' }

if (-not $Launcher) { $Launcher = Join-Path $root 'bin\VPNLauncher.exe' }
if (-not (Test-Path $Launcher)) {
    throw 'Нет VPNLauncher.exe. Собери его через build-exe.ps1 или укажи -Launcher.'
}

# ---------- сцена ----------

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage, $OutDir -Force | Out-Null
if (Test-Path $payload) { Remove-Item $payload -Force }
if (Test-Path $setup) { Remove-Item $setup -Force }

# плоская раскладка: установленная папка не должна содержать исходников
foreach ($f in @('VPN.ps1', 'core.ps1', 'theme.ps1', 'app.ico')) {
    Copy-Item (Join-Path $srcDir $f) $stage
}
foreach ($f in @('MyVPN.cmd', 'LICENSE')) {
    $p = Join-Path $root $f
    if (Test-Path $p) { Copy-Item $p $stage }
}
Copy-Item $SingBox (Join-Path $stage 'sing-box.exe')
Copy-Item $Launcher (Join-Path $stage 'VPNLauncher.exe')

# ---------- переводы строк ----------
# .ps1 обязателен с BOM для PowerShell 5.1, .cmd - с BOM и CRLF, иначе cmd.exe
# печатает кракозябры, а bat с голыми LF ломается молча.

$bomExt = @('.bat', '.cmd', '.ps1')
$textExt = @('.bat', '.cmd', '.ps1', '.md', '.txt')
Get-ChildItem $stage -File | Where-Object { $textExt -contains $_.Extension.ToLower() } | ForEach-Object {
    $ext = $_.Extension.ToLower()
    $raw = [System.IO.File]::ReadAllText($_.FullName)
    $norm = ($raw -replace "`r`n", "`n") -replace "`n", "`r`n"
    $b = [System.IO.File]::ReadAllBytes($_.FullName)
    $hasBom = ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)
    $wantBom = if ($bomExt -contains $ext) { $true } else { $hasBom }
    if ($norm -ne $raw -or $wantBom -ne $hasBom) {
        [System.IO.File]::WriteAllText($_.FullName, $norm, (New-Object System.Text.UTF8Encoding($wantBom)))
        Write-Host ('  {0}: привёл к CRLF{1}' -f $_.Name, $(if ($wantBom -and -not $hasBom) { ' +BOM' } else { '' }))
    }
}

# ---------- лицензия sing-box ----------

$sbSha = (Get-FileHash (Join-Path $stage 'sing-box.exe') -Algorithm SHA256).Hash.ToLower()
$sbVer = (& (Join-Path $stage 'sing-box.exe') version 2>&1 | Select-Object -First 1) -replace '^sing-box version\s*', ''
$notice = @"
sing-box - included binary component
====================================

This program bundles sing-box.exe, which is a separate work by SagerNet,
distributed under the GNU General Public License v3.0. It is NOT part of
the VPN LAUNCHER BY @YoncFALL source code and is covered by its own license.

Version : $sbVer
SHA-256 : $sbSha
Source  : https://github.com/SagerNet/sing-box
License : https://github.com/SagerNet/sing-box/blob/dev/LICENSE

If you redistribute this program you must keep this file, keep sing-box
unmodified, and offer the corresponding source of both components:

  sing-box   : https://github.com/SagerNet/sing-box
  launcher   : https://github.com/yoncfall-tech/VPN-LAUNCHER

You may obtain a copy of the GPL-3.0 from
<https://www.gnu.org/licenses/gpl-3.0.txt> or
<https://github.com/yoncfall-tech/VPN-LAUNCHER/blob/main/LICENSE>.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'SING-BOX-LICENSE.txt'), ($notice -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))

# ---------- zip с файлами программы ----------

Write-Host ''
Write-Host 'упаковка файлов программы...'
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $payload -CompressionLevel Optimal

# ---------- компиляция установщика ----------

$csc = $null
foreach ($r in @(($env:WINDIR + '\Microsoft.NET\Framework64'), ($env:WINDIR + '\Microsoft.NET\Framework'))) {
    $cand = Join-Path $r 'v4.0.30319\csc.exe'
    if (Test-Path $cand) { $csc = $cand; break }
}
if (-not $csc) { throw 'Не найден csc.exe. Нужен .NET Framework 4.x.' }

Write-Host 'компиляция установщика...'
$cargs = @(
    '/nologo'
    '/target:winexe'
    '/optimize+'
    '/platform:anycpu'
    '/reference:System.Core.dll'
    '/reference:System.Drawing.dll'
    '/reference:System.Windows.Forms.dll'
    '/reference:System.IO.Compression.dll'
    '/reference:System.IO.Compression.FileSystem.dll'
    "/win32icon:$(Join-Path $srcDir 'app.ico')"
    "/resource:$payload,payload.zip"
    "/resource:$(Join-Path $srcDir 'app.ico'),appicon.ico"
    "/out:$setup"
    (Join-Path $insDir 'Setup.cs')
)
$log = & $csc @cargs 2>&1
if ($LASTEXITCODE -ne 0) {
    $log | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "csc вернул код $LASTEXITCODE"
}
$log | Where-Object { $_ } | ForEach-Object { Write-Host $_ }

# ---------- проверки результата ----------

$fi = Get-Item $setup
$bytes = [System.IO.File]::ReadAllBytes($setup)
$peOff = [System.BitConverter]::ToInt32($bytes, 0x3C)
$subsys = [System.BitConverter]::ToUInt16($bytes, $peOff + 0x5C)
$subsysName = switch ($subsys) { 2 { 'GUI' } 3 { 'Console' } default { "?$subsys" } }
if ($subsys -ne 2) { throw "Подсистема должна быть GUI (2), получилось $subsys" }

Add-Type -Namespace InsChk -Name Ico -MemberDefinition @'
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern uint ExtractIconEx(string file, int index, IntPtr[] large, IntPtr[] small, uint count);
'@
$lg = New-Object IntPtr[] 1
$sm = New-Object IntPtr[] 1
$ic = [InsChk.Ico]::ExtractIconEx($setup, 0, $lg, $sm, 1)
if ($ic -lt 1) { throw 'Иконка не встроена в установщик.' }

$zipLen = (Get-Item $payload).Length
if ($fi.Length -lt $zipLen) { throw "Подозрительно малый exe: $($fi.Length) при zip $zipLen" }

# внутри установщика должен быть ровно один payload.zip и все нужные файлы
Add-Type -AssemblyName System.IO.Compression.FileSystem
$check = [System.IO.Compression.ZipFile]::OpenRead($payload)
$names = @($check.Entries | ForEach-Object { $_.FullName })
$check.Dispose()
$need = @('VPN.ps1', 'core.ps1', 'theme.ps1', 'VPNLauncher.exe', 'sing-box.exe', 'app.ico', 'SING-BOX-LICENSE.txt')
$miss = $need | Where-Object { $names -notcontains $_ }
if ($miss) { throw "В payload нет: $($miss -join ', ')" }

Write-Host ''
Write-Host ('установщик : {0}' -f $fi.FullName) -ForegroundColor Green
Write-Host ('размер     : {0:N0} байт ({1:N1} MB)' -f $fi.Length, ($fi.Length / 1MB))
Write-Host ('подсистема : {0} ({1})' -f $subsys, $subsysName)
Write-Host ('иконок     : {0}' -f $ic)
Write-Host ('sing-box   : {0}  sha256 {1}' -f $sbVer, $sbSha.Substring(0, 32))
Write-Host ('внутри     : {0} файлов' -f $names.Count)
Write-Host ('состав     : {0}' -f (($names | Sort-Object) -join ', '))

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $payload -Force -ErrorAction SilentlyContinue
