# Сборка VPNLauncher.exe - обёртки запуска без окна консоли.
# Нужна один раз, если в архиве релиза нет готового bin\VPNLauncher.exe.
# Требуется только .NET Framework, установленный в Windows.

[CmdletBinding()]
param(
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'bin' }

$src = Join-Path $PSScriptRoot 'src'
$cs = Join-Path $src 'Launcher.cs'
$ico = Join-Path $src 'app.ico'
$exe = Join-Path $OutDir 'VPNLauncher.exe'

foreach ($f in @($cs, $ico)) {
    if (-not (Test-Path $f)) { throw "Нет файла: $f" }
}

$csc = $null
foreach ($root in @(($env:WINDIR + '\Microsoft.NET\Framework64'), ($env:WINDIR + '\Microsoft.NET\Framework'))) {
    $cand = Join-Path $root 'v4.0.30319\csc.exe'
    if (Test-Path $cand) { $csc = $cand; break }
}
if (-not $csc) { throw 'Не найден csc.exe. Нужен .NET Framework 4.x.' }

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

$args = @(
    '/nologo'
    '/target:winexe'
    '/optimize+'
    '/platform:anycpu'
    '/warnaserror-'
    "/win32icon:$ico"
    "/out:$exe"
    $cs
)

Write-Host 'csc        :' $csc
Write-Host 'исходник   :' $cs
Write-Host 'иконка     :' $ico
Write-Host 'результат  :' $exe

$log = & $csc @args 2>&1
if ($LASTEXITCODE -ne 0) {
    $log | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "csc вернул код $LASTEXITCODE"
}
$log | Where-Object { $_ } | ForEach-Object { Write-Host $_ }

$fi = Get-Item $exe

# читаем PE-заголовок, чтобы убедиться, что подсистема GUI (2), а не консоль (3)
$bytes = [System.IO.File]::ReadAllBytes($exe)
$peOff = [System.BitConverter]::ToInt32($bytes, 0x3C)
$subsys = [System.BitConverter]::ToUInt16($bytes, $peOff + 0x5C)
$subsysName = switch ($subsys) { 2 { 'GUI' } 3 { 'Console' } default { "?$subsys" } }

Write-Host ''
Write-Host ('готово: {0}  {1:N0} байт' -f $fi.FullName, $fi.Length) -ForegroundColor Green
Write-Host ('подсистема PE: {0} ({1})' -f $subsys, $subsysName)
if ($subsys -ne 2) { throw "Подсистема должна быть GUI (2), получилось $subsys" }
