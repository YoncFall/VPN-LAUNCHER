# -*- coding: utf-8 -*-
"""Автозапуск с Windows (реестр Run).

ВАЖНО: в 1.0.6 этой функции НЕТ — это новая возможность по PLAN-PYTHON.md
(этап 2, «autostart.py реестр автозапуска»). Поведение VPN не меняется;
отмечено и в README (раздел отклонений).

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run,
значение RUN_VALUE_NAME = команда запуска:
  - собранная версия: "C:\\...\\VPNLauncher.exe"
  - dev-запуск:       "C:\\...\\python.exe" "C:\\...\\app.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

import winreg

from vpn_launcher.core.log import write_log

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "VPN Launcher"


def _launch_command() -> str:
    """Команда для значения Run (кавычки обязательны: пути со спецсимволами)."""
    if getattr(sys, "frozen", False):  # PyInstaller: сам VPNLauncher.exe
        return f'"{sys.executable}"'
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else Path.cwd()
    return f'"{sys.executable}" "{script}"'


def is_autostart_enabled() -> bool:
    """True, если в HKCU\\...\\Run есть непустая команда запуска."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
    except OSError:
        return False
    return bool(value)


def set_autostart(enabled: bool) -> None:
    """Включить/выключить автозапуск (отсутствующее значение при off - не ошибка)."""
    if enabled:
        command = _launch_command()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
        write_log(f"autostart ON: {command}")
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            return  # и так выключено - как Delete-Value с отсутствующим ключом не падаем
        write_log("autostart OFF")
