@echo off
setlocal enabledelayedexpansion
title Install - VPN LAUNCHER BY @YoncFALL

set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\VPN-LAUNCHER"

echo.
echo   ==============================================
echo     VPN LAUNCHER BY @YoncFALL
echo     installer
echo   ==============================================
echo.

if not exist "%SRC%\src\VPN.ps1" (
  echo   ERROR: src\VPN.ps1 not found. Run from unpacked archive.
  pause
  exit /b 1
)

if not exist "%SRC%\bin\sing-box.exe" (
  echo   ERROR: bin\sing-box.exe not found.
  echo   See README - sing-box is a separate GPL-3.0 component.
  pause
  exit /b 1
)

echo   Target: %DEST%
echo.

if not exist "%DEST%" (
  mkdir "%DEST%" 2>nul
)

xcopy "%SRC%\src" "%DEST%\src\" /E /I /Y /Q >nul
if exist "%SRC%\bin\sing-box.exe" copy /Y "%SRC%\bin\sing-box.exe" "%DEST%\sing-box.exe" >nul
if exist "%SRC%\src\MyVPN.cmd" copy /Y "%SRC%\src\MyVPN.cmd" "%DEST%\MyVPN.cmd" >nul
if exist "%SRC%\README.md" copy /Y "%SRC%\README.md" "%DEST%\README.md" >nul
if exist "%SRC%\LICENSE" copy /Y "%SRC%\LICENSE" "%DEST%\LICENSE" >nul
if exist "%SRC%\NOTICE.md" copy /Y "%SRC%\NOTICE.md" "%DEST%\NOTICE.md" >nul
if exist "%SRC%\SING-BOX-LICENSE.txt" copy /Y "%SRC%\SING-BOX-LICENSE.txt" "%DEST%\SING-BOX-LICENSE.txt" >nul

if not exist "%DEST%\MyVPN.cmd" (
  echo   ERROR: launcher MyVPN.cmd was not installed.
  pause
  exit /b 1
)
if not exist "%DEST%\sing-box.exe" (
  echo   ERROR: sing-box.exe was not installed.
  pause
  exit /b 1
)

echo   Files copied.
echo.

rem --- desktop shortcut ---
set "LNK=%USERPROFILE%\Desktop\VPN LAUNCHER BY @YoncFALL.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$sh=New-Object -ComObject WScript.Shell; $l=$sh.CreateShortcut('%LNK%'); $l.TargetPath='%DEST%\MyVPN.cmd'; $l.WorkingDirectory='%DEST%'; $l.Description='VPN LAUNCHER BY @YoncFALL - sing-box client'; $l.Save()" 2>nul
if exist "%LNK%" (echo   Desktop shortcut created.) else (echo   WARNING: could not create desktop shortcut.)

rem --- start menu shortcut ---
set "SM=%APPDATA%\Microsoft\Windows\Start Menu\Programs\VPN LAUNCHER BY @YoncFALL.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$sh=New-Object -ComObject WScript.Shell; New-Item -ItemType Directory -Force -Path (Split-Path '%SM%') | Out-Null; $l=$sh.CreateShortcut('%SM%'); $l.TargetPath='%DEST%\MyVPN.cmd'; $l.WorkingDirectory='%DEST%'; $l.Description='VPN LAUNCHER BY @YoncFALL - sing-box client'; $l.Save()" 2>nul
if exist "%SM%" (echo   Start menu shortcut created.)

echo.
echo   ==============================================
echo     Installed. Launch from desktop shortcut.
echo.
echo     On first run paste your subscription link.
echo     Full traffic (TUN) needs Administrator.
echo   ==============================================
echo.
pause
endlocal
