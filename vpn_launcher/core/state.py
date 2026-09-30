# -*- coding: utf-8 -*-
"""Состояние приложения. Порт Get-VpnState/Save-VpnState (core.ps1:630-641).

Файл: <install root>/state.json. Поля (точно как в PS):
    subUrl, mode ('tun'), selected, appList, lastNodes, autoUrlTest.

Безопасность (01.10.2026, «фулл-защита»): subUrl (ссылка подписки - это
доступ к нодам) шифруется DPAPI Windows, CurrentUser: на диске значение
выглядит как 'dpapi1:<base64>' и расшифровывается только той же учёткой
Windows на том же компьютере. Старый plaintext-файл читается как раньше:
миграция автоматическая, при следующем сохранении subUrl станет
шифрованным. Файл, уехавший на другой ПК или под другой учёткой, даёт
пустую подписку и строку в логе (ссылку нужно ввести заново). Остальные
поля остаются открытым JSON - секретов там нет.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

from vpn_launcher.core.log import write_log
from vpn_launcher.paths import STATE_FILE

# формат шифрованного значения + флаг DPAPI (без UI-промптов)
SUB_URL_PREFIX = "dpapi1:"
_UI_FORBIDDEN = 0x1

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    # CryptProtectData / CryptUnprotectData: сигнатуры совпадают по форме
    # (7 аргументов, второй - указатель), поэтому один argtypes.
    _CRYPT_ARGS = (
        ctypes.POINTER(_BLOB),  # pIn
        ctypes.c_void_p,        # szDataDescr / ppszDataDescr
        ctypes.POINTER(_BLOB),  # pOptionalEntropy
        ctypes.c_void_p,        # pvReserved
        ctypes.c_void_p,        # pPromptStruct
        wintypes.DWORD,         # dwFlags
        ctypes.POINTER(_BLOB),  # pOut
    )
    _crypt32.CryptProtectData.argtypes = _CRYPT_ARGS
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = _CRYPT_ARGS
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    _kernel32.LocalFree.restype = ctypes.c_void_p


def _dpapi(fn_name: str, data: bytes) -> bytes | None:
    """CryptProtect/CryptUnprotectData; None - нет Windows или ошибка."""
    if sys.platform != "win32" or not data:
        return None
    src = (ctypes.c_char * len(data)).from_buffer_copy(data)
    inp = _BLOB(len(data), ctypes.cast(src, ctypes.POINTER(ctypes.c_char)))
    out = _BLOB()
    fn = getattr(_crypt32, fn_name)
    if not fn(
        ctypes.byref(inp), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(out)
    ):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(out.pbData)


def _decode_sub_url(value: str) -> str:
    if not value.startswith(SUB_URL_PREFIX):
        return value  # старый plaintext (миграция при следующем save)
    try:
        raw: bytes | None = base64.b64decode(value[len(SUB_URL_PREFIX):])
    except (ValueError, TypeError):
        raw = None
    dec = _dpapi("CryptUnprotectData", raw) if raw else None
    if dec is None:
        write_log(
            "state.json: подписка не расшифровалась "
            "(файл с другого ПК/учётки Windows) - введи её заново"
        )
        return ""
    return dec.decode("utf-8", errors="replace")


def _encode_sub_url(value: str) -> str:
    if not value or value.startswith(SUB_URL_PREFIX):
        return value  # пусто или уже зашифровано - не трогаем
    enc = _dpapi("CryptProtectData", value.encode("utf-8"))
    if enc is None:
        write_log("state.json: DPAPI недоступен - подписка сохранена без шифрования")
        return value
    return SUB_URL_PREFIX + base64.b64encode(enc).decode("ascii")


def _default_state() -> dict[str, Any]:
    return {
        "subUrl": "",
        "mode": "tun",
        "selected": "",
        "appList": [],
        "lastNodes": [],
        "autoUrlTest": True,
    }


DEFAULT_STATE = _default_state()


def load_state(path: Path | None = None) -> dict[str, Any]:
    """Файл отсутствует или битый -> дефолт (как catch в PS)."""
    p = path or STATE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if isinstance(data.get("subUrl"), str):
                data["subUrl"] = _decode_sub_url(data["subUrl"])
            return data
    except (OSError, ValueError):
        pass
    return _default_state()


def save_state(st: dict[str, Any], path: Path | None = None) -> None:
    p = path or STATE_FILE
    out = dict(st)
    if isinstance(out.get("subUrl"), str):
        out["subUrl"] = _encode_sub_url(out["subUrl"])
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
