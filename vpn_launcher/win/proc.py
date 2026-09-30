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

start_sing_box/stop_sing_box - порт запуска движка (VPN.ps1:541-575):
`run -c <config> -D <root>`, stdout -> singbox.log, stderr -> singbox.log.err
(ротация >2MB), скрытое окно (-WindowStyle Minimized), стоп - kill
(Stop-Process -Force).
"""
from __future__ import annotations

import ctypes
import hashlib
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from vpn_launcher.core.log import write_log
from vpn_launcher.paths import SING_BOX, install_root

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


_LOG_MAX = 2 * 1024 * 1024  # PS: если singbox.log > 2MB - удалить (VPN.ps1:547)

# Безопасность (01.10.2026): SHA256 поставляемого движка. Подмена
# sing-box.exe (логин/пароли нод и весь трафик в его руках) должна быть
# замечена, а не выполнена. При обновлении движка константу меняют
# сознательно - тест test_engine_hash_pinned не даст забыть.
ENGINE_SHA256 = "7BBEF1DEA9189EE12799AE834EA4B4658355DA25C47A21AD8804904C0CCD9410"


def engine_hash(path: Path | str | None = None) -> str:
    """SHA256 файла движка (верхний регистр hex)."""
    p = Path(path) if path is not None else SING_BOX
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def verify_engine(path: Path | str | None = None) -> None:
    """Целостность движка перед запуском: подменённый/битый = стоп.

    FileNotFoundError - файла нет (как FileNotFoundError у Start-Process в PS),
    OSError - хэш не совпал (строка 'engine hash MISMATCH' пишется в лог).
    """
    p = Path(path) if path is not None else SING_BOX
    try:
        got = engine_hash(p)
    except FileNotFoundError:
        raise FileNotFoundError(f"sing-box.exe не найден: {p}") from None
    except OSError as ex:
        raise OSError(f"sing-box.exe не читается: {p} ({ex})") from None
    if got != ENGINE_SHA256:
        write_log(
            f"engine hash MISMATCH: ожидалось {ENGINE_SHA256[:12]}..., "
            f"получено {got[:12]}..."
        )
        raise OSError("sing-box.exe повреждён или подменён (проверка целостности)")


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > _LOG_MAX:
            path.unlink()
    except OSError:
        pass  # как try/catch в PS - не мешаем запуску


def start_sing_box(
    config_path: str | Path, root: str | Path | None = None
) -> subprocess.Popen:
    """Запуск движка: sing-box run -c <cfg> -D <root> (VPN.ps1:552-555).

    stdout -> <root>/singbox.log, stderr -> <root>/singbox.log.err (файлы
    обрезаются при старте, как -RedirectStandardOutput у Start-Process), cwd =
    корень установки, окно не создаётся. FileNotFoundError, если движок не
    найден (Start-Process в PS тоже бросает). Перед запуском - контроль
    целостности (verify_engine): подменённый движок не выполняется.
    """
    verify_engine()
    base = Path(root) if root is not None else install_root()
    out = base / "singbox.log"
    err = base / "singbox.log.err"
    _rotate(out)
    _rotate(err)
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW (-WindowStyle Minimized)
    with open(out, "wb") as fo, open(err, "wb") as fe:
        return subprocess.Popen(
            [str(SING_BOX), "run", "-c", str(config_path), "-D", str(base)],
            cwd=str(base),
            stdout=fo,
            stderr=fe,
            **kwargs,
        )


def stop_sing_box(proc: subprocess.Popen | None) -> None:
    """Stop-Process -Force (VPN.ps1:579): kill, если процесс ещё жив."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass  # как try/catch в PS
