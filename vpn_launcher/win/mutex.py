# -*- coding: utf-8 -*-
"""Single instance. Порт Host.cs:17-90, 187-259 (мьютекс + поднятие окна).

Имена мьютексов - дословно из Host.cs:17-18. РАЗНЫЕ имена для обычного и
повышенного экземпляров обязательны (комментарий Host.cs:59-61): иначе
TUN-перезапуск через UAC упрётся в занятый мьютекс и новый процесс молча
закроется.

app.pid: создаётся владельцем мьютекста (Host.cs MarkPid), удаляется при
выходе (ClearPid); FocusExisting читает его для поиска окна первого
экземпляра.

Отклонение: acquire_instance() идемпотентен в рамках одного процесса
(повторный вызов -> True). Host.cs - одноразовый процесс, такой case у
него не возникает; нам это нужно для тестируемости и защиты от двойного
вызова в app.py.
"""
from __future__ import annotations

import atexit
import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from vpn_launcher.core.log import write_log
from vpn_launcher.paths import install_root
from vpn_launcher.win import elevate

MUTEX_NAME = r"Local\MyVPNLauncher_YoncFALL_9E1F4C"                 # Host.cs:17
MUTEX_NAME_ELEVATED = r"Local\MyVPNLauncher_YoncFALL_9E1F4C_Elevated"  # Host.cs:18

PID_FILE_NAME = "app.pid"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9

# LooksLikeApp (Host.cs:243): класс окна старой (WinForms) или новой (Qt) версии
_APP_CLASS_MARKERS = ("WindowsForms", "Qt")

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)

_k32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)
_k32.CloseHandle.restype = wintypes.BOOL

_u32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_u32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_u32.GetForegroundWindow.restype = wintypes.HWND
_u32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_u32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_u32.GetWindowThreadProcessId.restype = wintypes.DWORD
_u32.EnumWindows.argtypes = (
    ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
    wintypes.LPARAM,
)
_u32.IsWindowVisible.argtypes = (wintypes.HWND,)
_u32.IsWindow.argtypes = (wintypes.HWND,)
_u32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_u32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)

_kernel32_tid = _k32.GetCurrentThreadId
_kernel32_tid.restype = wintypes.DWORD

_HANDLE: int | None = None  # мьютекс нашего экземпляра (живёт до выхода процесса)


def _mutex_name() -> str:
    """Имя по правам процесса (Host.cs:62): повышенный экземпляр - отдельное имя."""
    return MUTEX_NAME_ELEVATED if elevate.is_elevated() else MUTEX_NAME


def _pid_file() -> Path:
    return install_root() / PID_FILE_NAME


def _mark_pid() -> None:
    try:
        _pid_file().write_text(str(os.getpid()), encoding="utf-8")
    except OSError as exc:
        write_log(f"pid-файл: {exc}")


def _clear_pid() -> None:
    try:
        _pid_file().unlink()
    except OSError:
        pass  # как Host.cs ClearPid: не мешаем выходу


def acquire_instance() -> bool:
    """True - это первый экземпляр (мьютекс наш); False - уже запущен (поднять окно).

    Владелец создаёт app.pid; хэндл держится до выхода процесса.
    """
    global _HANDLE
    if _HANDLE is not None:
        return True  # повторный вызов в этом же процессе (см. докстринг)
    handle = _k32.CreateMutexW(None, False, _mutex_name())
    if not handle:
        raise OSError(f"CreateMutexW failed: err={ctypes.get_last_error()}")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _k32.CloseHandle(handle)  # как `using` в Host.cs:65
        return False
    _HANDLE = handle
    _mark_pid()
    atexit.register(_clear_pid)
    return True


# ---------------- поднятие окна первого экземпляра (Host.cs FocusExisting) ----------------


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _looks_like_app(hwnd: int) -> bool:
    """Host.cs LooksLikeApp: видимое окно со «своим» классом и непустым заголовком."""
    if not _u32.IsWindowVisible(hwnd):
        return False
    buf = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, buf, 256)
    cls = buf.value
    if not any(marker in cls for marker in _APP_CLASS_MARKERS):
        return False
    title = ctypes.create_unicode_buffer(256)
    _u32.GetWindowTextW(hwnd, title, 256)
    return len(title.value) > 0


def _enum_toplevel() -> list[int]:
    out: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam) -> bool:
        if _u32.IsWindow(hwnd):
            out.append(hwnd)
        return True

    _u32.EnumWindows(cb, 0)
    return out


def _find_app_window(pid: int = 0) -> int:
    """Host.cs FocusExisting-поиск: окно с pid -> иначе любое окно приложения."""
    if pid:
        for w in _enum_toplevel():
            if _window_pid(w) == pid and _looks_like_app(w):
                return w
    for w in _enum_toplevel():
        if _looks_like_app(w):
            return w
    return 0


def focus_window(hwnd: int) -> None:
    """Host.cs:234-240: SW_RESTORE + AttachThreadInput -> SetForegroundWindow."""
    if not hwnd:
        return
    _u32.ShowWindow(hwnd, SW_RESTORE)
    fg = _u32.GetForegroundWindow()
    dummy = wintypes.DWORD(0)
    fg_thread = _u32.GetWindowThreadProcessId(fg, ctypes.byref(dummy)) if fg else 0
    me = _kernel32_tid()
    if fg_thread:
        _u32.AttachThreadInput(me, fg_thread, True)
    _u32.SetForegroundWindow(hwnd)
    if fg_thread:
        _u32.AttachThreadInput(me, fg_thread, False)


def focus_existing_window() -> bool:
    """Повторный запуск: поднять уже открытое окно. True - окно найдено и поднято."""
    try:
        pid = int(_pid_file().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    hwnd = _find_app_window(pid)
    if not hwnd:
        return False
    focus_window(hwnd)
    return True
