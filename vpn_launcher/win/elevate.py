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

Передача окна (30.09.2026, по просьбе «окно не должно исчезать при
подключении»): именованное событие 'окно показано'
(create_window_shown_event / wait_window_shown /
release_window_shown_event / signal_window_shown). Старый экземпляр
создаёт событие ДО спавна повышенного (иначе гонка: новое может успеть
сигналить раньше, чем событие появится), после спавна ждёт сигнала с
прокруткой Qt-событий (окно живое, не замёрзшее) и закрывается только
потом; новый экземпляр зовёт signal_window_shown() сразу после win.show().
Разные имена мьютексов (mutex.py) позволяют экземплярам существовать
одновременно, а окна центрируются одинаково/позиция передаётся аргументом
--window-pos, - новое окно встаёт ровно поверх старого, переход не виден.
"""
from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable
from ctypes import wintypes
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


# ---------------- передача окна при TUN-повышении прав ----------------

WINDOW_SHOWN_EVENT = r"Local\MyVPNLauncher_YoncFALL_9E1F4C_WindowShown"
_WAIT_OBJECT_0 = 0
_SLICE_MS = 50  # кусок ожидания между прокрутками Qt-событий

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateEventW.argtypes = (
    wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
)
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.SetEvent.argtypes = (wintypes.HANDLE,)
_k32.SetEvent.restype = wintypes.BOOL
_k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)
_k32.CloseHandle.restype = wintypes.BOOL


def create_window_shown_event() -> int | None:
    """Сторона передачи (старое окно): создать событие ДО спавна нового.

    manual-reset, изначально не-сигналированное. None - CreateEventW
    провалился (тогда передачи нет: старое окно закроется сразу, как раньше).
    """
    handle = _k32.CreateEventW(None, True, False, WINDOW_SHOWN_EVENT)
    return int(handle) if handle else None


def wait_window_shown(
    handle: int | None,
    timeout_ms: int = 15000,
    pump: Callable[[], None] | None = None,
) -> bool:
    """Ждать сигнал новой стороны. pump() (Qt processEvents) держит старое окно живым."""
    if not handle:
        return False
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if _k32.WaitForSingleObject(handle, _SLICE_MS) == _WAIT_OBJECT_0:
            return True
        if pump is not None:
            pump()
    return False


def release_window_shown_event(handle: int | None) -> None:
    """Закрыть хэндл события (безопасно для None; объект живёт, пока есть хэндлы)."""
    if handle:
        _k32.CloseHandle(handle)


def signal_window_shown() -> None:
    """Сторона-наследник (новое окно): вызывать сразу после win.show()."""
    handle = _k32.CreateEventW(None, True, False, WINDOW_SHOWN_EVENT)
    if handle:
        _k32.SetEvent(handle)
        _k32.CloseHandle(handle)  # у ожидающего свой хэндл - объект переживёт
