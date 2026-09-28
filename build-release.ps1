# Сборка архива релиза: раскладка, нормализация переводов строк, zip, хеши.
#
#   .\build-release.ps1 -Version 1.0.2 -SingBox "C:\path\to\sing-box.exe"
#
# sing-box в репозиторий не коммитится (GPL-3.0, качается отдельно), поэтому
# путь к нему передаётся параметром. Готовую обёртку можно взять из
# build-exe.ps1 или указать -Launcher путём к своему VPNLauncher.exe.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$SingBox = '',
    [string]$Launcher = '',
    [string]$OutDir = '',
    [string]$Screenshot = ''
)

$ErrorActionPreference = 'Stop'

if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'dist' }
$stage = Join-Path $env:TEMP ("vpl-stage-" + $Version)
$zip = Join-Path $OutDir ("VPN-LAUNCHER-" + $Version + '.zip')

# ---------- проверки ----------

$root = $PSScriptRoot
$srcDir = Join-Path $root 'src'
if (-not (Test-Path (Join-Path $srcDir 'VPN.ps1'))) { throw "Нет $srcDir\VPN.ps1" }

if (-not $SingBox) {
    $guess = Join-Path $env:LOCALAPPDATA 'MyVPN\sing-box.exe'
    if (Test-Path $guess) { $SingBox = $guess }
}
if (-not (Test-Path $SingBox)) { throw 'Нет sing-box.exe. Укажи -SingBox.' }

if (-not $Launcher) {
    $guess = Join-Path $root 'bin\VPNLauncher.exe'
    if (Test-Path $guess) { $Launcher = $guess }
}
if (-not (Test-Path $Launcher)) {
    Write-Warning 'VPNLauncher.exe не найден: в архив попадёт запасной MyVPN.cmd с окном консоли. Собери его через build-exe.ps1.'
    $Launcher = ''
}

if (-not $Screenshot) { $Screenshot = Join-Path $root 'docs\screenshot.png' }

# ---------- чистка сцены ----------

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
if (Test-Path $zip) { Remove-Item $zip -Force }
New-Item -ItemType Directory -Path $stage, (Join-Path $stage 'src'), (Join-Path $stage 'bin') | Out-Null

# ---------- раскладка ----------

foreach ($f in @('install.bat', 'uninstall.bat', 'README.md', 'LICENSE', 'NOTICE.md')) {
    $p = Join-Path $root $f
    if (Test-Path $p) { Copy-Item $p $stage }
}
Copy-Item (Join-Path $srcDir '*') (Join-Path $stage 'src') -Recurse
if (Test-Path $Screenshot) {
    if (-not (Test-Path (Join-Path $stage 'docs'))) { New-Item -ItemType Directory -Path (Join-Path $stage 'docs') | Out-Null }
    Copy-Item $Screenshot (Join-Path $stage 'docs')
}
Copy-Item $SingBox (Join-Path $stage 'bin\sing-box.exe')
if ($Launcher) { Copy-Item $Launcher (Join-Path $stage 'bin\VPNLauncher.exe') }

# ---------- переводы строк ----------
# cmd.exe не понимает bat-файлы с голыми LF: скрипт молча ломается.
# .gitattributes требует CRLF, но рабочая копия может быть в LF, поэтому
# нормализуем прямо здесь, перед упаковкой.

# .bat и .cmd содержат кириллицу в echo, поэтому им нужен BOM, иначе
# cmd.exe напечатает кракозябры. .ps1 с BOM обязателен для PowerShell 5.1,
# .md и .txt BOM не нужен.
$bomExt = @('.bat', '.cmd', '.ps1')
$textExt = @('.bat', '.cmd', '.ps1', '.md', '.txt')
$fixed = 0
Get-ChildItem $stage -Recurse -File | Where-Object { $textExt -contains $_.Extension.ToLower() } | ForEach-Object {
    $ext = $_.Extension.ToLower()
    $raw = [System.IO.File]::ReadAllText($_.FullName)
    $norm = ($raw -replace "`r`n", "`n") -replace "`n", "`r`n"
    $b = [System.IO.File]::ReadAllBytes($_.FullName)
    $hasBom = ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)
    $wantBom = if ($bomExt -contains $ext) { $true } else { $hasBom }
    if ($norm -ne $raw -or $wantBom -ne $hasBom) {
        [System.IO.File]::WriteAllText($_.FullName, $norm, (New-Object System.Text.UTF8Encoding($wantBom)))
        $what = if ($norm -ne $raw) { 'CRLF' } else { 'BOM' }
        Write-Host ('  {0}: {1}{2}' -f $_.Name, $what, $(if ($wantBom -and -not $hasBom) { ' +BOM' } else { '' }))
        $fixed++
    }
}
Write-Host ('нормализовано файлов: {0}' -f $fixed)

# ---------- лицензия sing-box ----------

$sbSha = (Get-FileHash (Join-Path $stage 'bin\sing-box.exe') -Algorithm SHA256).Hash.ToLower()
$sbVer = (& (Join-Path $stage 'bin\sing-box.exe') version 2>&1 | Select-Object -First 1) -replace '^sing-box version\s*', ''
$notice = @"
sing-box - included binary component
====================================

This archive bundles sing-box.exe, which is a separate work by SagerNet,
distributed under the GNU General Public License v3.0. It is NOT part of
the VPN LAUNCHER BY @YoncFALL source code and is covered by its own license.

Version : $sbVer
SHA-256 : $sbSha
Source  : https://github.com/SagerNet/sing-box
License : https://github.com/SagerNet/sing-box/blob/dev/LICENSE

If you redistribute this archive you must keep this file, keep sing-box
unmodified, and offer the corresponding source of both components:

  sing-box   : https://github.com/SagerNet/sing-box
  launcher   : https://github.com/yoncfall-tech/VPN-LAUNCHER

You may obtain a copy of the GPL-3.0 from
<https://www.gnu.org/licenses/gpl-3.0.txt> or
<https://github.com/yoncfall-tech/VPN-LAUNCHER/blob/main/LICENSE>.
"@
[System.IO.File]::WriteAllText((Join-Path $stage 'SING-BOX-LICENSE.txt'), ($notice -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))

# ---------- упаковка ----------

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal

# ---------- отчёт ----------

$fi = Get-Item $zip
Write-Host ''
Write-Host ('архив      : {0}' -f $fi.FullName)
Write-Host ('размер     : {0:N0} байт ({1:N1} MB)' -f $fi.Length, ($fi.Length / 1MB))
Write-Host ('sing-box   : {0}  sha256 {1}' -f $sbVer, $sbSha.Substring(0, 32))
if ($Launcher) {
    $exSha = (Get-FileHash (Join-Path $stage 'bin\VPNLauncher.exe') -Algorithm SHA256).Hash.ToLower()
    Write-Host ('launcher   : {0:N0} байт  sha256 {1}' -f (Get-Item (Join-Path $stage 'bin\VPNLauncher.exe')).Length, $exSha.Substring(0, 32))
} else {
    Write-Host 'launcher   : НЕТ (в архиве только MyVPN.cmd)' -ForegroundColor Yellow
}
Write-Host ''
Write-Host 'проверка кодировок и переводов строк:'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::OpenRead($zip)
$entries = @($z.Entries)
foreach ($e in ($entries | Sort-Object FullName)) {
    $ext = [System.IO.Path]::GetExtension($e.FullName).ToLower()
    if (@('.bat', '.cmd', '.ps1') -notcontains $ext) { continue }
    $s = $e.Open()
    $ms = New-Object System.IO.MemoryStream
    $s.CopyTo($ms); $s.Close()
    $b = $ms.ToArray(); $ms.Dispose()
    $bom = ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)
    $lf = 0; $crlf = 0
    for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -eq 10) { $lf++; if ($i -gt 0 -and $b[$i - 1] -eq 13) { $crlf++ } } }
    $eol = if ($lf -eq $crlf) { 'CRLF' } else { "LF=$lf CRLF=$crlf БИТЫЙ" }
    $enc = if ($bom) { 'UTF-8 BOM' } else { 'UTF-8' }
    $flag = if ($lf -ne $crlf) { ' <-- ПРОБЛЕМА' } else { '' }
    Write-Host ('  {0,-22} {1,-11} {2}{3}' -f $e.FullName, $enc, $eol, $flag)
}
$z.Dispose()
Remove-Item $stage -Recurse -Force
