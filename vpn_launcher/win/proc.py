# -*- coding: utf-8 -*-
"""Процессы: список запущенных .exe, запуск/останов sing-box.

Порт Get-RunningExeList (VPN.ps1:233-243): уникальные имена процессов со
стороны .exe, отсортированные (PS Sort-Object). Источник вместо Get-Process -
Toolhelp32-снапшот (kernel32), чтобы не тянуть psutil.

Отличия от PS (только для комбобокса исключений, на VPN не влияет):
  - PS берёт ProcessName и дописывает '.exe'; Toolhelp сразу отдаёт имя
    файла, у системных записей расширение может отсутствовать - дописываем;
  - уникальность PS `-notin` регистронезависима - повторяем через casefold;
  - Sort-Object - культурная сортировка, здесь casefold-эквивалент.

Статус: get_running_exe_list - Этап 2; start/stop_sing_box - Этап 5.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_NO_MORE_FILES = 18

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


_KERNEL32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_KERNEL32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_KERNEL32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_KERNEL32.Process32FirstW.restype = wintypes.BOOL
_KERNEL32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_KERNEL32.Process32NextW.restype = wintypes.BOOL
_KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)


def get_running_exe_list() -> list[str]:
    """Уникальные имена запущенных .exe, отсортированы (как Get-RunningExeList)."""
    snap = _KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return []
    seen: set[str] = set()
    out: list[str] = []
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = _KERNEL32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile
            if entry.th32ProcessID == 0:
                # PS здесь 'Idle' (.NET ProcessName PID 0) -> 'idle.exe';
                # Toolhelp отдаёт '[System Process]' - приводим к виду 1.0.6
                name = "idle.exe"
            elif name and not name.lower().endswith(".exe"):
                name += ".exe"  # PS дописывал '.exe' к ProcessName
            key = name.casefold()  # PS `-notin` регистронезависим
            if name and key not in seen:
                seen.add(key)
                out.append(name)
            ok = _KERNEL32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _KERNEL32.CloseHandle(snap)
    return sorted(out, key=str.casefold)  # PS Sort-Object (регистр не важен)


def start_sing_box(config_path: str) -> int:
    raise NotImplementedError("Этап 5: subprocess sing-box run -c <config>")


def stop_sing_box() -> None:
    raise NotImplementedError("Этап 5")
