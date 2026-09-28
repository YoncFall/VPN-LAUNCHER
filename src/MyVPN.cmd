@echo off
setlocal
title VPN LAUNCHER BY @YoncFALL
set "MVPN=%LOCALAPPDATA%\VPN-LAUNCHER"
if not exist "%MVPN%\src\VPN.ps1" (
  echo.
  echo   VPN LAUNCHER BY @YoncFALL - not installed
  echo.
  echo   Install script not found:  install.bat
  echo.
  pause
  exit /b 1
)
start "" powershell -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Minimized -File "%MVPN%\src\VPN.ps1"
endlocal
