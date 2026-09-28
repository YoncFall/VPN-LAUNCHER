# Сборка VPNLauncher.exe - нативной оболочки VPN ЛАУНЧЕР.
# Нужна один раз, если в архиве релиза нет готового bin\VPNLauncher.exe.
# Требуется только .NET Framework, установленный в Windows.
# Движок PowerShell берётся из системной сборки, отдельно ничего ставить не нужно.

[CmdletBinding()]
param(
    [string]$OutDir = '',
    [switch]$SkipSelfTest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'bin' }

$src = Join-Path $PSScriptRoot 'src'
$cs = Join-Path $src 'Host.cs'
$ico = Join-Path $src 'app.ico'
$exe = Join-Path $OutDir 'VPNLauncher.exe'

foreach ($f in @($cs, $ico)) {
    if (-not (Test-Path $f)) { throw "Нет файла: $f" }
}

# Системная сборка движка PowerShell. Путь одинаковый на Windows 10/11.
$sma = Join-Path $env:WINDIR 'Microsoft.NET\assembly\GAC_MSIL\System.Management.Automation\v4.0_3.0.0.0__31bf3856ad364e35\System.Management.Automation.dll'
if (-not (Test-Path $sma)) {
    $sma = Get-ChildItem (Join-Path $env:WINDIR 'Microsoft.NET\assembly') -Filter 'System.Management.Automation.dll' -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
}
if (-not $sma -or -not (Test-Path $sma)) {
    throw 'Не найдена сборка System.Management.Automation (движок PowerShell).'
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
    "/reference:$sma"
    '/reference:System.Core.dll'
    "/win32icon:$ico"
    "/out:$exe"
    $cs
)

Write-Host 'csc        :' $csc
Write-Host 'исходник   :' $cs
Write-Host 'движок PS  :' $sma
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

# иконка должна быть встроена в сам exe, иначе в панели задач будет значок PowerShell
Add-Type -Namespace WinIcon -Name Extract -MemberDefinition @'
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern uint ExtractIconEx(string file, int index, IntPtr[] large, IntPtr[] small, uint count);
'@
$large = New-Object IntPtr[] 1
$small = New-Object IntPtr[] 1
$ic = [WinIcon.Extract]::ExtractIconEx($exe, 0, $large, $small, 1)
if ($ic -lt 1) { throw 'Иконка не найдена внутри собранного exe.' }
Write-Host ('иконок в exe: {0}' -f $ic) -ForegroundColor Green

if (-not $SkipSelfTest) {
    # прогон встроенного движка: окно должно быть в нашем процессе, без консоли
    $probe = Join-Path $OutDir '_selftest'
    if (Test-Path $probe) { Remove-Item $probe -Recurse -Force }
    New-Item -ItemType Directory -Path $probe | Out-Null
    Copy-Item $exe $probe
    Copy-Item $ico $probe
    $p = Start-Process (Join-Path $probe 'VPNLauncher.exe') -ArgumentList '--selftest' -PassThru -WindowStyle Hidden
    $p.WaitForExit(30000) | Out-Null
    $res = Join-Path $probe 'selftest.txt'
    if ($p.ExitCode -ne 0 -or -not (Test-Path $res)) {
        throw "Проверка встроенного движка не прошла (код $($p.ExitCode))"
    }
    $probeText = (Get-Content $res -Raw).Trim()
    if ($probeText -notmatch '\|True$') {
        throw "Скрипт не видит свою папку через `$PSScriptRoot: $probeText"
    }
    Write-Host ('движок     : {0}' -f $probeText) -ForegroundColor Green
    Remove-Item $probe -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'Сборка завершена.' -ForegroundColor Green
