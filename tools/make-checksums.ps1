# make-checksums.ps1 - SHA-256 дистрибутивов для публикации с релизом.
#
# Стандартная строка выпуска (публикуется в описании релиза рядом с файлами):
#     5e3c...  VPN-LAUNCHER-2.0.1.zip
#     9a41...  VPN-LAUNCHER-2.0.1-Setup.exe
# Пользователь сверяет скачанное: certutil -hashfile <файл> SHA256
#
# Зачем: exe/zip не подписаны (SmartScreen), чек-суммы в описании релиза -
# единственный способ убедиться, что файл не подменён при скачивании.
#
# Запуск:  powershell -ExecutionPolicy Bypass -File .\tools\make-checksums.ps1
#          [-Path dist] [-Out <файл>]
param(
    [string]$Path = "dist",
    [string]$Out = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dir = if ([System.IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $root $Path }
if (-not (Test-Path $dir)) { Write-Host "нет папки: $dir"; exit 1 }

# только верхний уровень dist: zip и Setup.exe с нашим именем
$files = Get-ChildItem -Path $dir -File |
    Where-Object { $_.Name -like "VPN-LAUNCHER*" -and $_.Extension -in @(".zip", ".exe") } |
    Sort-Object Name
if (-not $files) {
    Write-Host "нет дистрибутивов в $dir - сначала build-app.ps1 / build-installer.ps1"
    exit 1
}

$lines = foreach ($f in $files) {
    $hash = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash.ToLower()
    "{0}  {1}" -f $hash, $f.Name
}
$outFile = if ($Out) { $Out } else { Join-Path $dir "SHA256SUMS.txt" }
# ASCII: стандартный формат coreutils (hash + два пробела + имя файла)
$lines | Set-Content -Path $outFile -Encoding ascii
Write-Host "==> $outFile"
$lines | ForEach-Object { Write-Host $_ }
