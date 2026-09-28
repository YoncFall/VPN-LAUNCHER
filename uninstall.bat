@echo off
setlocal
title Uninstall - VPN LAUNCHER BY @YoncFALL

set "DEST=%LOCALAPPDATA%\VPN-LAUNCHER"
set "LNK=%USERPROFILE%\Desktop\VPN LAUNCHER BY @YoncFALL.lnk"
set "SM=%APPDATA%\Microsoft\Windows\Start Menu\Programs\VPN LAUNCHER BY @YoncFALL.lnk"

echo.
echo   Uninstall VPN LAUNCHER BY @YoncFALL?
echo   Settings, logs and cache will be deleted.
echo.
choice /C YN /N /M "   Continue? [Y/N] "
if errorlevel 2 (
  echo   Cancelled.
  pause
  exit /b 0
)

if exist "%LNK%" del /f /q "%LNK%" >nul 2>&1
if exist "%SM%" del /f /q "%SM%" >nul 2>&1

taskkill /F /IM sing-box.exe >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /f >nul 2>&1

if exist "%DEST%" rd /s /q "%DEST%" >nul 2>&1

echo.
echo   Removed.
pause
endlocal
