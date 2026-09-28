@echo off
setlocal
title VPN LAUNCHER BY @YoncFALL

rem Лаунчер запускает то, что лежит рядом с ним
set "MVPN=%~dp0"
if "%MVPN:~-1%"=="\" set "MVPN=%MVPN:~0,-1%"

if not exist "%MVPN%\src\VPN.ps1" (
    echo.
    echo   VPN LAUNCHER BY @YoncFALL - launcher files not found
    echo.
    echo   Looked for: "%MVPN%\src\VPN.ps1"
    echo   Run install.bat first.
    echo.
    pause
    exit /b 1
)

if not exist "%MVPN%\sing-box.exe" (
    echo.
    echo   VPN LAUNCHER BY @YoncFALL - sing-box.exe not found
    echo.
    echo   Looked for: "%MVPN%\sing-box.exe"
    echo   Re-run install.bat, it will fetch it.
    echo.
    pause
    exit /b 1
)

rem Свой exe: своя иконка, без окна консоли и без ExecutionPolicy Bypass,
rem на который antivirus реагирует предупреждением.
if exist "%MVPN%\bin\VPNLauncher.exe" (
    start "" "%MVPN%\bin\VPNLauncher.exe"
    endlocal
    exit /b 0
)

rem Запасной путь, если exe нет (запуск из исходников).
start "" powershell -NoProfile -STA -WindowStyle Minimized -File "%MVPN%\src\VPN.ps1"
endlocal
