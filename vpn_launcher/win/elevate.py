# -*- coding: utf-8 -*-
"""Повышение прав. Порт --autoconnect-ветки VPN.ps1:474-523 (ShellExecuteW 'runas').

Как в 1.0.6:
  - is_elevated: членство в Administrators (там WindowsPrincipal.IsInRole,
    здесь IsUserAnAdmin - одна и та же проверка);
  - relaunch_elevated: запуск СЕБЯ с аргументами через 'runas'
    (собранный exe - аналог $hostExe; dev-запуск - аналог powershell-fallback);
  - лог-строки повторяют VPN.ps1 ('elevating own executable: ...',
    'elevation ERROR: ...').

Отклонение: при отказе/отмене UAC функция возбуждает OSError - обработчик
статуса (этап 5) покажет 'Не удалось получить права администратора',
как в PS-catch (VPN.ps1:512-517).
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from vpn_launcher.core.log import write_log

SW_SHOWNORMAL = 1
_ERROR_CANCELLED = 1223  # пользователь нажал «Нет» в диалоге UAC


def is_elevated() -> bool:
    """True - процесс уже запущен от имени администратора."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _shell_execute(exe: str, params: str) -> int:
    """ShellExecuteW(NULL, 'runas', exe, params, NULL, SW_SHOWNORMAL) -> код >32 = ок."""
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, SW_SHOWNORMAL)


def _quote(arg: str) -> str:
    return f'"{arg}"'


def _build_command(args: list[str]) -> tuple[str, str, bool]:
    """-> (exe, params, own_exe): own_exe=True - запускаем собранную программу."""
    joined = " ".join(_quote(a) for a in args)
    if getattr(sys, "frozen", False):
        return sys.executable, joined, True
    # dev-раскладка: python.exe <скрипт> <args> - аналог powershell-fallback
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else Path.cwd()
    params = " ".join(filter(None, (_quote(str(script)), joined)))
    return sys.executable, params, False


def relaunch_elevated(args: list[str]) -> None:
    """Перезапустить приложение с повышенными правами (UAC-диалог).

    args - аргументы новому процессу (в 1.0.6 это ['--autoconnect']).
    Успех = процесс порождён (UAC подтверждён); отказ/отмена -> OSError.
    """
    exe, params, own_exe = _build_command(list(args))
    if own_exe:
        write_log(f"elevating own executable: {exe}")
    else:
        write_log(f"own exe not found (dev run), falling back to python host: {exe}")
    rc = _shell_execute(exe, params)
    # Docs: >32 = успех; 1223 (ERROR_CANCELLED) может вернуться при отмене UAC.
    if rc <= 32 or rc == _ERROR_CANCELLED:
        msg = f"elevation failed: ShellExecuteW rc={rc}" + (
            " (UAC cancelled)" if rc == _ERROR_CANCELLED else ""
        )
        write_log(f"elevation ERROR: {msg}")
        raise OSError(msg)
