# -*- coding: utf-8 -*-
"""Kill switch (TUN): управление прямым выходом по режиму списка.

Принцип (02.10.2026): пока подключены, в WFP вешаются свои фильтры на слой
авторизации исходящих соединений (ALE_AUTH_CONNECT V4/V6). Состав зависит
от app_mode и списка процессов (core.config.routed_app_processes - тот же
список, что в правилах маршрутизации sing-box):

    exclude (классика):
        РАЗРЕШИТЬ  - трафик с адресов нашего TUN-адаптера (ушёл в туннель);
        РАЗРЕШИТЬ  - сам sing-box.exe (его соединения с нодами);
        РАЗРЕШИТЬ  - LAN/петля/мультикаст (роутер и сеть живы при сбое);
        РАЗРЕШИТЬ  - образы «мимо VPN» (игры + выбор пользователя);
        БЛОКИРОВАТЬ - всё остальное.
      Если движок умер - не-разрешённые соединения блокируются вместо
      утечки «в обход VPN» (fail-closed), а игры/исключения живут.

    include (инверсия):
        РАЗРЕШИТЬ  - те же TUN / движок / LAN;
        БЛОКИРОВАТЬ - ТОЛЬКО выбранные образы (V4 и V6);
        глобального блока НЕТ.
      Если движок умер - выбранные приложения не утекают на прямую
      (fail-closed для них), а все остальные продолжают работать
      напрямую без ограничений - ровно обещание режима include.

Веса permit > block (WEIGHT_PERMIT > WEIGHT_BLOCK) и максимальный
саблэйл гарантируют: разрешение туннеля/LAN/движка всегда сильнее
блока конкретного образа, а permit образа (exclude) сильнее
безусловного блока.

Почему не Windows Firewall (netsh / New-NetFirewallRule): эмпирически
01.10.2026 на этой машине (а) netsh вообще не добавляет block-правила
(«Неустранимая ошибка ... (0x2)»), (б) блок-правило снапшота побеждает
даже allow-ALL (U1-тест), то есть «block + allow engine/LAN» невозможен,
(в) при GPO-режиме локальные правила могут не применяться вовсе. Свои
фильтры WFP с явными весами (permit > block) и ВЫСШИМ собственным
sublayer'ом работают детерминированно при любой комбинации семантик.

Сессия WFP открывается с флагом FWPM_SESSION_FLAG_DYNAMIC: её объекты
удаляются системой в момент закрытия сессии (штатный выход, kill, авария) -
навсегда «залочить» интернет физически невозможно. Эмпирически (01.10.2026)
сессия БЕЗ флага оставляла фильтры после FwpmEngineClose0 (накопилось 112
«сирот», блокировавших чужой трафик), поэтому снятие дополнительно удаляет
фильтры ЯВНО по ключу (FwpmFilterDeleteByKey0), а установка начинается с
очистки остатков прошлых запусков (оба шага - те же ключи, только наши).

API:
    install_kill_switch(tun_addrs, engine_exe=None, *, app_mode="exclude",
                        app_names=()) -> bool       (False + лог)
    remove_kill_switch()                                     (идемпотентно)
    is_active() -> bool
    build_specs(engine_exe, tun_addrs, *, app_mode="exclude",
                app_paths=()) -> list[dict]        (чистая, для тестов)
    resolve_image_paths(names) -> list[str]        (имена -> образы WFP)

Самопроверка (нужны права администратора):
    python -m vpn_launcher.win.wfp --selftest
"""
from __future__ import annotations

import ctypes
import ipaddress
import os
import shutil
import socket
import sys
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any, Sequence

from vpn_launcher.core.config import APP_MODE_EXCLUDE, APP_MODE_INCLUDE
from vpn_launcher.core.log import write_log
from vpn_launcher.paths import SING_BOX

# ---- GUIDы слоёв/условий (fwpmu.h) -----------------------------------------
GUID_LAYER_V4 = "c38d57d1-05a7-4c33-904f-7fbceee60e82"   # ALE_AUTH_CONNECT_V4
GUID_LAYER_V6 = "4a72393b-319f-44bc-84c3-ba54dcb3b6b4"   # ALE_AUTH_CONNECT_V6
GUID_COND_APP_ID = "d78e1e87-8644-4ea5-9437-d809ecefc971"
GUID_COND_LOCAL = "d9ee00de-c1ef-4617-bfe3-ffd8f5a08957"
GUID_COND_REMOTE = "b235ae9a-1d64-49b8-a44c-5ff3d9095045"
SUBLAYER_GUID = "5a1e0f42-9c3d-4b8e-a7f6-2d4c8e91b035"

# ---- константы FWP (fwptypes.h) --------------------------------------------
FWP_ACTION_BLOCK = 0x1001   # 0x1 | FWP_ACTION_FLAG_TERMINATING(0x1000)
FWP_ACTION_PERMIT = 0x1002  # 0x2 | FWP_ACTION_FLAG_TERMINATING
FWP_MATCH_EQUAL = 0
FWP_EMPTY = 0
FWP_UINT64 = 4
FWP_BYTE_BLOB_TYPE = 12
FWPM_SESSION_FLAG_DYNAMIC = 0x00000001  # fwpmtypes.h: объекты живут до закрытия сессии
FWP_V4_ADDR_MASK = 0x100
FWP_V6_ADDR_MASK = 0x101
ERROR_ALREADY_EXISTS = 183
# FWP_E_ALREADY_EXISTS: саблэйл (в отличие от фильтров) переживает закрытие
# сессии - повторная установка не должна падать (проба 30.09.2026)
FWP_E_ALREADY_EXISTS = 0x80320009

# Веса: permit > block с запасом больше любого auto-weight системы
# (FWPM_AUTO_WEIGHT_MAX = MAX_UINT64 >> 4) - порядок фильтров детерминирован
# и при «вес важнее sublayer», и при «sublayer важнее веса».
WEIGHT_PERMIT = 0xFFFFFFFFFFFFFF00
WEIGHT_BLOCK = 0xFFFFFFFFFFFFF000
SUBLAYER_WEIGHT = 0xFFFF  # максимальный: наш sublayer оценивается первым

# LAN/петля/мультикаст: даже «kill» не должен отрезать роутер и локалку
_LAN_V4 = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "127.0.0.0/8",
    "224.0.0.0/4",
    "255.255.255.255/32",
)
_LAN_V6 = ("::1/128", "fe80::/10", "fc00::/7", "ff00::/8")


# ---- ctypes: структуры WFP (fwptypes.h / fwpmtypes.h, ABI MSVC x64) --------
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _BLOB(ctypes.Structure):  # FWP_BYTE_BLOB
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class _V4AM(ctypes.Structure):  # FWP_V4_ADDR_AND_MASK
    _fields_ = [("addr", ctypes.c_uint32), ("mask", ctypes.c_uint32)]


class _V6AM(ctypes.Structure):  # FWP_V6_ADDR_AND_MASK
    _fields_ = [("addr", ctypes.c_ubyte * 16), ("prefixLength", ctypes.c_ubyte)]


class _VAL_UNION(ctypes.Union):  # общее ядро FWP_VALUE0 / FWP_CONDITION_VALUE0
    _fields_ = [
        ("uint32", ctypes.c_uint32),
        ("uint64", ctypes.POINTER(ctypes.c_uint64)),
        ("byteBlob", ctypes.POINTER(_BLOB)),
        ("v4AddrMask", ctypes.POINTER(_V4AM)),
        ("v6AddrMask", ctypes.POINTER(_V6AM)),
    ]


class _COND_VALUE(ctypes.Structure):  # FWP_CONDITION_VALUE0
    _fields_ = [("type", ctypes.c_uint32), ("u", _VAL_UNION)]


class _VALUE(ctypes.Structure):  # FWP_VALUE0
    _fields_ = [("type", ctypes.c_uint32), ("u", _VAL_UNION)]


class _DISPLAY(ctypes.Structure):  # FWPM_DISPLAY_DATA0
    _fields_ = [("name", ctypes.c_wchar_p), ("description", ctypes.c_wchar_p)]


class _ACTION(ctypes.Structure):  # FWPM_ACTION0 {type; union{GUID}}
    _fields_ = [("type", ctypes.c_uint32), ("calloutKey", _GUID)]


class _COND(ctypes.Structure):  # FWPM_FILTER_CONDITION0
    _fields_ = [
        ("fieldKey", _GUID),
        ("matchType", ctypes.c_int32),
        ("value", _COND_VALUE),
    ]


class _CTX_UNION(ctypes.Union):  # {UINT64 rawContext; GUID providerContextKey}
    _fields_ = [("rawContext", ctypes.c_uint64), ("providerContextKey", _GUID)]


class _FILTER(ctypes.Structure):  # FWPM_FILTER0 (порядок полей как в SDK!)
    _fields_ = [
        ("filterKey", _GUID),
        ("displayData", _DISPLAY),
        ("flags", ctypes.c_uint32),
        ("providerKey", ctypes.POINTER(_GUID)),
        ("providerData", _BLOB),
        ("layerKey", _GUID),
        ("subLayerKey", _GUID),
        ("weight", _VALUE),
        ("numFilterConditions", ctypes.c_uint32),
        ("filterCondition", ctypes.POINTER(_COND)),
        ("action", _ACTION),
        ("rawContext", _CTX_UNION),
        ("reserved", ctypes.POINTER(_GUID)),
        ("filterId", ctypes.c_uint64),
        ("effectiveWeight", _VALUE),
    ]


class _SUBLAYER(ctypes.Structure):  # FWPM_SUBLAYER0
    _fields_ = [
        ("subLayerKey", _GUID),
        ("displayData", _DISPLAY),
        ("flags", ctypes.c_uint16),
        ("providerKey", ctypes.POINTER(_GUID)),
        ("providerData", _BLOB),
        ("weight", ctypes.c_uint16),
    ]


class _SESSION(ctypes.Structure):  # FWPM_SESSION0 (fwpmtypes.h, x64: 72 байта)
    _fields_ = [
        ("sessionKey", _GUID),
        ("displayData", _DISPLAY),
        ("flags", ctypes.c_uint32),
        ("txnWaitTimeoutInMSec", ctypes.c_uint32),
        ("processId", wintypes.DWORD),
        ("sid", ctypes.c_void_p),
        ("username", ctypes.c_void_p),
        ("kernelMode", ctypes.c_int),
    ]


_fwp = ctypes.WinDLL("fwpuclnt")
_fwp.FwpmEngineOpen0.argtypes = (
    wintypes.LPCWSTR,          # serverName (NULL = локальный)
    ctypes.c_uint32,           # authnService
    ctypes.c_void_p,           # authIdentity
    ctypes.c_void_p,           # session (NULL = сессия по умолчанию, НЕ persistent)
    ctypes.POINTER(wintypes.HANDLE),
)
_fwp.FwpmEngineOpen0.restype = ctypes.c_uint32
_fwp.FwpmEngineClose0.argtypes = (wintypes.HANDLE,)
_fwp.FwpmEngineClose0.restype = ctypes.c_uint32
_fwp.FwpmSubLayerAdd0.argtypes = (
    wintypes.HANDLE, ctypes.POINTER(_SUBLAYER), ctypes.c_void_p,
)
_fwp.FwpmSubLayerAdd0.restype = ctypes.c_uint32
_fwp.FwpmFilterAdd0.argtypes = (
    wintypes.HANDLE, ctypes.POINTER(_FILTER), ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_uint64),
)
_fwp.FwpmFilterAdd0.restype = ctypes.c_uint32
_fwp.FwpmGetAppIdFromFileName0.argtypes = (
    wintypes.LPCWSTR, ctypes.POINTER(ctypes.POINTER(_BLOB)),
)
_fwp.FwpmGetAppIdFromFileName0.restype = ctypes.c_uint32
_fwp.FwpmFreeMemory0.argtypes = (ctypes.c_void_p,)  # void**
_fwp.FwpmFreeMemory0.restype = None
_fwp.FwpmFilterCreateEnumHandle0.argtypes = (
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.HANDLE),
)
_fwp.FwpmFilterCreateEnumHandle0.restype = ctypes.c_uint32
_fwp.FwpmFilterEnum0.argtypes = (
    wintypes.HANDLE, wintypes.HANDLE, ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
)
_fwp.FwpmFilterEnum0.restype = ctypes.c_uint32
_fwp.FwpmFilterDestroyEnumHandle0.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
_fwp.FwpmFilterDestroyEnumHandle0.restype = ctypes.c_uint32
_fwp.FwpmFilterDeleteByKey0.argtypes = (wintypes.HANDLE, ctypes.POINTER(_GUID))
_fwp.FwpmFilterDeleteByKey0.restype = ctypes.c_uint32


def _guid(s: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


def _is_v6(cidr: str) -> bool:
    return ":" in cidr.split("/")[0]


def _cidr_v4(cidr: str) -> tuple[int, int]:
    """IPv4-CIDR -> (addr, mask) как UINT32 в host-order.

    Эмпирически (UAC-проба 30.09.2026): движок валидирует маску как битовый
    паттерн host-order - для /16 ожидается 0xFFFF0000; вариант с сырыми
    сетевыми байтами (0x0000FFFF) отклонён с FWP_E_INVALID_NET_MASK
    (0x8032001F, «Недопустимая маска сети»). int(network_address)/int(netmask)
    дают ровно host-order, и сравнение (адрес & маска) == адрес совместимо
    с внутренним представлением движка (проверено пробой трафика selftest).
    """
    net = ipaddress.IPv4Network(cidr, strict=False)
    return int(net.network_address), int(net.netmask)


# ---- чистый план фильтров (тестируется без админа) -------------------------
def build_specs(
    engine_exe: str,
    tun_addrs: Sequence[str],
    *,
    app_mode: str = APP_MODE_EXCLUDE,
    app_paths: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """План фильтров kill switch.

    dict: {layer: GUID-строка, action, weight, conds: [...]};
    cond: {"field": GUID, "kind": "appid"|"addr", "value": путь|CIDR}.

    app_mode + app_paths - семантика режима (докстринг модуля):
      exclude - глобальный блок + permit образов «мимо VPN» (app_paths);
      include - глобального блока нет, app_paths блокируются по appid;
      пустой app_paths в include - блокировать некого (внешний вид не
      меняется: остаются только разрешения, всё работает напрямую).
    """
    specs: list[dict[str, Any]] = []
    # 1. всё, что пришло с адресов TUN (идёт в туннель) - разрешаем
    for cidr in tun_addrs:
        specs.append(
            {
                "layer": GUID_LAYER_V6 if _is_v6(cidr) else GUID_LAYER_V4,
                "action": FWP_ACTION_PERMIT,
                "weight": WEIGHT_PERMIT,
                "conds": [{"field": GUID_COND_LOCAL, "kind": "addr", "value": cidr}],
            }
        )
    # 2. сам движок - ему нужен выход к нодам (оба семейства)
    for layer in (GUID_LAYER_V4, GUID_LAYER_V6):
        specs.append(
            {
                "layer": layer,
                "action": FWP_ACTION_PERMIT,
                "weight": WEIGHT_PERMIT,
                "conds": [{"field": GUID_COND_APP_ID, "kind": "appid", "value": engine_exe}],
            }
        )
    # 3. LAN/петля/мультикаст - доступны всегда (без них убьём и роутер)
    for cidr in _LAN_V4:
        specs.append(
            {
                "layer": GUID_LAYER_V4,
                "action": FWP_ACTION_PERMIT,
                "weight": WEIGHT_PERMIT,
                "conds": [{"field": GUID_COND_REMOTE, "kind": "addr", "value": cidr}],
            }
        )
    for cidr in _LAN_V6:
        specs.append(
            {
                "layer": GUID_LAYER_V6,
                "action": FWP_ACTION_PERMIT,
                "weight": WEIGHT_PERMIT,
                "conds": [{"field": GUID_COND_REMOTE, "kind": "addr", "value": cidr}],
            }
        )
    # 4. семантика режима (02.10.2026): управляем прямым выходом ТОЧЕЧНО
    if app_mode == APP_MODE_INCLUDE:
        # инверсия: глобального блока нет; блокируем только выбранные
        # образы - при смерти движка они не утекают на прямую, а весь
        # прочий трафик (не выбранные процессы) продолжает работать.
        # Разрешения TUN/LAN/движка (вес permit выше) спасают их соединения
        # с туннелем, пока движок жив.
        for path in app_paths:
            for layer in (GUID_LAYER_V4, GUID_LAYER_V6):
                specs.append(
                    {
                        "layer": layer,
                        "action": FWP_ACTION_BLOCK,
                        "weight": WEIGHT_BLOCK,
                        "conds": [
                            {"field": GUID_COND_APP_ID, "kind": "appid", "value": str(path)}
                        ],
                    }
                )
    else:
        # классика (exclude): permit образов «мимо VPN» перебивает
        # безусловный блок по весу - эти процессы живут и после смерти
        # движка, всё остальное остаётся fail-closed.
        for path in app_paths:
            for layer in (GUID_LAYER_V4, GUID_LAYER_V6):
                specs.append(
                    {
                        "layer": layer,
                        "action": FWP_ACTION_PERMIT,
                        "weight": WEIGHT_PERMIT,
                        "conds": [
                            {"field": GUID_COND_APP_ID, "kind": "appid", "value": str(path)}
                        ],
                    }
                )
        # 5. блок всего остального (без условий - матчится любое соединение)
        for layer in (GUID_LAYER_V4, GUID_LAYER_V6):
            specs.append(
                {"layer": layer, "action": FWP_ACTION_BLOCK, "weight": WEIGHT_BLOCK, "conds": []}
            )
    return specs


# ---- разрешение имён процессов в образы ------------------------------------
# WFP матчит только по полному пути образа (appid), а список пользователя -
# имена вида «Discord.exe». Кандидаты собираются из нескольких источников,
# отбор - только существующие файлы (resolve_image_paths).

def _app_paths_candidates(name: str) -> list[str]:
    """Реестр App Paths (HKCU/HKLM, 64/32-битный вид) -> путь образа."""
    out: list[str] = []
    try:
        import winreg
    except ImportError:  # не Windows - только в тестах
        return out
    key_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths\\" + name
    views = (
        (winreg.HKEY_CURRENT_USER, 0),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
    )
    for hive, view in views:
        try:
            with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as k:
                val = None
                for vname in (None, ""):  # значение по умолчанию = путь
                    try:
                        val, _ = winreg.QueryValueEx(k, vname)
                        break
                    except OSError:
                        continue
        except OSError:
            continue
        if isinstance(val, str) and val.strip():
            out.append(val)
    return out


def _running_images(names: Sequence[str]) -> list[str]:
    """Пути запущенных образов по именам (один вызов PowerShell на все)."""
    stems = sorted({Path(str(n)).stem for n in names if str(n).strip()})
    stems = [s for s in stems if s]
    if not stems:
        return []
    try:
        import subprocess

        q = ",".join("'" + s.replace("'", "") + "'" for s in stems)
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-Process -Name {q} -ErrorAction SilentlyContinue"
                " | Select-Object -ExpandProperty Path -ErrorAction SilentlyContinue",
            ],
            capture_output=True, timeout=15, creationflags=0x08000000,
        )
        return [
            ln.strip()
            for ln in out.stdout.decode("utf-8", "replace").splitlines()
            if ln.strip()
        ]
    except Exception:  # noqa: BLE001 - источник best-effort
        return []


def _root_candidates(name: str) -> list[str]:
    """Типовые корни установки (обновляемые приложения вроде Discord)."""
    out: list[str] = []
    p = Path(name)
    stem = p.stem
    if not stem or p.is_absolute():
        return out
    try:
        import os

        la = os.environ.get("LOCALAPPDATA") or ""
        pf = os.environ.get("ProgramFiles") or ""
        pf86 = os.environ.get("ProgramFiles(x86)") or ""
    except Exception:  # noqa: BLE001
        return out
    if la:
        base = Path(la) / stem
        if base.is_dir():
            # Discord: %LOCALAPPDATA%\Discord\app-*\Discord.exe (версии)
            out.extend(str(x) for x in sorted(base.glob(f"app-*/{name}")))
        cand = base / name
        if cand.is_file():
            out.append(str(cand))
    for root in (pf, pf86):
        if not root:
            continue
        for cand in (Path(root) / stem / name, Path(root) / name):
            if cand.is_file():
                out.append(str(cand))
    return out


def resolve_image_paths(names: Sequence[str]) -> list[str]:
    """Имена процессов -> существующие пути образов (условия appid WFP).

    Источники: абсолютный путь (пользователь вручную), запущенный процесс,
    реестр App Paths, PATH, типовые корни. Ненайденные имена логируются и
    пропускаются: пока движок жив, нужные процессы всё равно идут в TUN
    (маршруты /1), а без образа фильтр просто не создатся - честнее, чем
    условие на несуществующий путь.
    """
    cleaned = [str(n).strip() for n in names if str(n).strip()]
    if not cleaned:
        return []
    running = _running_images(cleaned)
    out: list[str] = []
    missing: list[str] = []
    for name in cleaned:
        cands: list[str] = []
        p = Path(name)
        if p.is_absolute():
            cands.append(name)  # путь руками - ищем только его
        else:
            key = name.casefold()
            cands += [r for r in running if Path(r).name.casefold() == key]
            cands += _app_paths_candidates(name)
            w = shutil.which(name)
            if w:
                cands.append(w)
            cands += _root_candidates(name)
        keep: list[str] = []
        for c in cands:
            try:
                c2 = os.path.expandvars(c).strip('"')
                if Path(c2).is_file() and c2 not in keep:
                    keep.append(c2)
            except (OSError, ValueError):
                continue
        if keep:
            out.extend(keep)
        else:
            missing.append(name)
    if missing:
        write_log("kill switch: образы не найдены: " + ", ".join(missing))
    final: list[str] = []
    for x in out:
        if x not in final:
            final.append(x)
    return final


# ---- применение -------------------------------------------------------------
_ENGINE: Any = None  # HANDLE сессии WFP, пока kill switch активен


def _open_engine() -> Any:
    handle = wintypes.HANDLE()
    sess = _SESSION()
    sess.flags = FWPM_SESSION_FLAG_DYNAMIC  # объекты живут ровно до close
    rc = 0
    for authn in (10, 0):  # RPC_C_AUTHN_WINNT, затем DEFAULT
        rc = _fwp.FwpmEngineOpen0(
            None, authn, None, ctypes.byref(sess), ctypes.byref(handle)
        )
        if rc == 0:
            return handle
    raise OSError(f"FwpmEngineOpen0 rc={rc} (нужны права администратора?)")


def _add_sublayer(handle: Any) -> None:
    sl = _SUBLAYER()
    sl.subLayerKey = _guid(SUBLAYER_GUID)
    sl.displayData.name = "VPN Launcher kill switch"
    sl.displayData.description = "Fail-closed: трафик только через туннель"
    sl.weight = SUBLAYER_WEIGHT
    rc = _fwp.FwpmSubLayerAdd0(handle, ctypes.byref(sl), None)
    if rc not in (0, ERROR_ALREADY_EXISTS, FWP_E_ALREADY_EXISTS):
        raise OSError(f"FwpmSubLayerAdd0 rc={rc}")


def _make_condition(cond: dict[str, Any], backing: list) -> _COND:
    c = _COND()
    c.fieldKey = _guid(cond["field"])
    c.matchType = FWP_MATCH_EQUAL
    if cond["kind"] == "appid":
        blob = ctypes.POINTER(_BLOB)()
        rc = _fwp.FwpmGetAppIdFromFileName0(cond["value"], ctypes.byref(blob))
        if rc != 0 or not blob:
            raise OSError(f"FwpmGetAppIdFromFileName0 rc={rc}")
        backing.append(blob)  # освободится в _add_filters (engine скопирует при add)
        c.value.type = FWP_BYTE_BLOB_TYPE
        c.value.u.byteBlob = blob
    elif _is_v6(cond["value"]):
        net = ipaddress.IPv6Network(cond["value"], strict=False)
        raw = socket.inet_pton(socket.AF_INET6, str(net.network_address))
        v = _V6AM(addr=(ctypes.c_ubyte * 16).from_buffer_copy(raw), prefixLength=net.prefixlen)
        backing.append(v)
        c.value.type = FWP_V6_ADDR_MASK
        c.value.u.v6AddrMask = ctypes.pointer(v)
    else:
        addr, mask = _cidr_v4(cond["value"])
        v = _V4AM(addr, mask)
        backing.append(v)
        c.value.type = FWP_V4_ADDR_MASK
        c.value.u.v4AddrMask = ctypes.pointer(v)
    return c


def _add_filter(handle: Any, spec: dict[str, Any]) -> None:
    backing: list = []  # живые объекты, на которые ссылаются условия/вес
    try:
        conds = [_make_condition(c, backing) for c in spec["conds"]]
        cond_arr = (_COND * len(conds))(*conds) if conds else (_COND * 0)()
        w = ctypes.c_uint64(spec["weight"])
        backing.append(w)

        f = _FILTER()
        f.filterKey = _guid(str(uuid.uuid4()))
        f.displayData.name = "VPN Launcher kill switch"
        f.layerKey = _guid(spec["layer"])
        f.subLayerKey = _guid(SUBLAYER_GUID)
        f.weight.type = FWP_UINT64
        f.weight.u.uint64 = ctypes.pointer(w)
        f.numFilterConditions = len(conds)
        f.filterCondition = ctypes.cast(cond_arr, ctypes.POINTER(_COND))
        f.action.type = spec["action"]
        # effectiveWeight оставляем FWP_EMPTY - движок посчитает сам

        fid = ctypes.c_uint64(0)
        rc = _fwp.FwpmFilterAdd0(handle, ctypes.byref(f), None, ctypes.byref(fid))
        if rc != 0:
            raise OSError(f"FwpmFilterAdd0 rc={rc} (layer {spec['layer']})")
    finally:
        for b in backing:
            if isinstance(b, ctypes.POINTER(_BLOB)):
                _fwp.FwpmFreeMemory0(ctypes.byref(b))


def _add_filters(handle: Any, specs: Sequence[dict[str, Any]]) -> int:
    added = 0
    for spec in specs:
        _add_filter(handle, spec)
        added += 1
    return added


_FILT_NAME = "VPN Launcher kill switch"


def _is_ours(name: str | None, sublayer: uuid.UUID) -> bool:
    """Наш фильтр - по имени отображения или по ключу нашего саблэйла."""
    return bool(name and _FILT_NAME in name) or sublayer == uuid.UUID(SUBLAYER_GUID)


def _our_filter_keys(handle: Any) -> list[str]:
    """Ключи всех наших фильтров в БД (включая остатки прошлых запусков).

    Эмпирический эталон (01.10.2026): enum с CreateEnumHandle0 и выходом
    HANDLE (8 байт, не uint32!) после перебора 4000 записей находил 112
    сирот от чужих (нединамических) сессий - читаемые, удаляемые по ключу.
    """
    eh = wintypes.HANDLE()
    rc = _fwp.FwpmFilterCreateEnumHandle0(handle, None, ctypes.byref(eh))
    if rc != 0:
        raise OSError(f"FwpmFilterCreateEnumHandle0 rc={rc:#x}")
    keys: list[str] = []
    try:
        slot = ctypes.c_void_p()
        n = ctypes.c_uint32(0)
        rc = _fwp.FwpmFilterEnum0(
            handle, eh.value, 0x10000, ctypes.byref(slot), ctypes.byref(n)
        )
        if rc != 0:
            raise OSError(f"FwpmFilterEnum0 rc={rc:#x}")
        try:
            if slot.value:
                arr = ctypes.cast(slot.value, ctypes.POINTER(ctypes.POINTER(_FILTER)))
                for i in range(n.value):
                    f = arr[i].contents
                    name = f.displayData.name or ""
                    sub = uuid.UUID(
                        bytes_le=ctypes.string_at(ctypes.byref(f.subLayerKey), 16)
                    )
                    if _is_ours(name, sub):
                        keys.append(
                            str(uuid.UUID(bytes_le=ctypes.string_at(
                                ctypes.byref(f.filterKey), 16)))
                        )
        finally:
            _fwp.FwpmFreeMemory0(ctypes.byref(slot))
    finally:
        _fwp.FwpmFilterDestroyEnumHandle0(handle, eh.value)
    return keys


def _wipe_our_filters(handle: Any) -> int:
    """Явно удалить все наши фильтры по ключу. Возвращает число удалённых.

    Закрытие сессии само удаляет объекты динамической сессии, но явное
    удаление - надёжнее (и убирает остатки чужих нединамических сессий).
    Ошибка перебора (нет прав) - OSError; одиночные промахи удаления
    (фильтр уже исчез) не фатальны.
    """
    deleted = 0
    for key in _our_filter_keys(handle):
        g = _guid(key)
        if _fwp.FwpmFilterDeleteByKey0(handle, ctypes.byref(g)) == 0:
            deleted += 1
    return deleted


def install_kill_switch(
    tun_addrs: Sequence[str],
    engine_exe: str | None = None,
    *,
    app_mode: str = APP_MODE_EXCLUDE,
    app_names: Sequence[str] = (),
) -> bool:
    """Повесить фильтры (True) или сообщить False + строку в лог.

    Идемпотентно: уже активен -> True. Нет адресов TUN -> False (без
    разрешения на туннель kill switch сломал бы само подключение).

    app_mode/app_names - та же семантика, что в маршрутизации sing-box
    (core.config.routed_app_processes, см. докстринг модуля): exclude -
    глобальный блок + разрешение образов «мимо VPN»; include - глобального
    блока нет, блокируются только выбранные образы.
    """
    global _ENGINE
    if _ENGINE is not None:
        return True
    if not tun_addrs:
        write_log("kill switch: адреса TUN неизвестны - не устанавливается")
        return False
    exe = str(engine_exe) if engine_exe is not None else str(SING_BOX)
    try:
        handle = _open_engine()
    except OSError as ex:
        write_log(f"kill switch: WFP недоступен: {ex}")
        return False
    try:
        stale = _wipe_our_filters(handle)  # сироты прошлых запусков - до добавления
        if stale:
            write_log(f"kill switch: удалено старых фильтров: {stale}")
        _add_sublayer(handle)
        app_paths = resolve_image_paths(app_names)
        added = _add_filters(
            handle,
            build_specs(
                exe, list(tun_addrs), app_mode=app_mode, app_paths=app_paths
            ),
        )
    except OSError as ex:
        write_log(f"kill switch: ошибка установки: {ex}")
        _fwp.FwpmEngineClose0(handle)  # динамическая сессия: close = откат своих
        return False
    _ENGINE = handle
    extra = ""
    if app_mode == APP_MODE_INCLUDE:
        extra = f", include-block образов: {len(app_paths)}"
    elif app_paths:
        extra = f", мимо блока: {len(app_paths)} образ(ов)"
    write_log(f"kill switch ON: {added} фильтров ({', '.join(tun_addrs)}){extra}")
    return True


def remove_kill_switch() -> None:
    """Снять фильтры: явно по ключу, затем закрыть сессию. Идемпотентно."""
    global _ENGINE
    if _ENGINE is None:
        return
    try:
        wiped = _wipe_our_filters(_ENGINE)
    except OSError as ex:
        wiped = 0
        write_log(f"kill switch: явное удаление фильтров не удалось: {ex}")
    rc = _fwp.FwpmEngineClose0(_ENGINE)
    _ENGINE = None
    write_log(
        "kill switch OFF"
        + (f" (удалено {wiped})" if wiped else "")
        + ("" if rc == 0 else f" (close rc={rc})")
    )


def is_active() -> bool:
    return _ENGINE is not None


# ---- самопроверка (повышенные права) ---------------------------------------
def _probe(ip: str, port: int, timeout: float = 5.0) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return "OK"
    except Exception as exc:  # noqa: BLE001 - самопроверка печатает тип
        return f"FAIL({type(exc).__name__})"
    finally:
        s.close()


def _phys_ipv4() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 80))  # пакеты не шлём - только таблица маршрутов
        return s.getsockname()[0]
    finally:
        s.close()


def _default_gateway() -> str | None:
    try:
        import subprocess

        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue"
                " | Sort-Object RouteMetric | Select-Object -First 1).NextHop",
            ],
            capture_output=True, timeout=15, creationflags=0x08000000,
        )
        gw = out.stdout.decode("utf-8", errors="replace").strip()
        return gw or None
    except Exception:  # noqa: BLE001
        return None


def _self_exe() -> str:
    """Путь ОБРАЗА процесса, а не sys.executable.

    В окружении uv sys.executable ведёт на пере-экзекцию-заглушку, а образ
    процесса - другой файл; appid-матчинг WFP идёт по образу. UAC-проба
    30.09.2026: appid по sys.executable промахивался и процесс ловил свой же
    блок (TimeoutError/PermissionError в selftest).
    """
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetModuleFileNameW(None, buf, 32768)
    return buf.value if n else sys.executable


def _selftest() -> int:
    """Проверка вживую: appid / локальный адрес / блок / LAN / снятие."""
    results: list[tuple[str, str, str]] = []

    def check(name: str, expect: str, got: str) -> None:
        results.append((name, expect, got))
        print(f"  {name}: ожидалось {expect}, получено {got}", flush=True)

    me = _self_exe()
    phys = _phys_ipv4()
    gw = _default_gateway()
    print(f"phys ip: {phys}, gateway: {gw}", flush=True)

    # Цель проб наружу - TCP 8.8.8.8:53, а НЕ :443. Диагноз 02.10.2026:
    # порт 80/443 перехватывает WinDivert (zapret/winws), и после изменения
    # набора WFP-фильтров он кратковременно (~10 с) проваливал пробы :443 -
    # ложные таймауты искажали самопроверку. Порт 53 вне --wf-tcp winws,
    # на нём permit/block отрабатывают безупречно (wfp-diag2.out).
    PEXT = ("8.8.8.8", 53)

    # T1: разрешение по appid (движок = наш python; тун-адрес фиктивный)
    remove_kill_switch()
    ok = install_kill_switch(["203.0.113.1/32"], engine_exe=me)
    check("T1 install(appid=python)", "True", str(ok))
    check("T1 проба наружу", "OK", _probe(*PEXT))
    remove_kill_switch()

    # T2: разрешение по локальному адресу TUN (физ. IP подменён за адрес туннеля)
    ok = install_kill_switch([phys + "/32"], engine_exe=str(SING_BOX))
    check("T2 install(local=tun)", "True", str(ok))
    check("T2 проба наружу", "OK", _probe(*PEXT))
    remove_kill_switch()

    # T3+T4: блок без совпадений, затем LAN-разрешение в той же сессии
    ok = install_kill_switch(["172.19.0.1/32"], engine_exe=str(SING_BOX))
    check("T3 install(block)", "True", str(ok))
    check("T3 проба наружу (должен БЛОК)", "FAIL", _probe(*PEXT).split("(")[0])
    if gw:
        check("T4 проба LAN (gw:53)", "OK", _probe(gw, 53))
    else:
        print("  T4 пропущена: шлюз не найден", flush=True)
    remove_kill_switch()

    # T6: include - глобального блока нет, блокируется ТОЛЬКО выбранный
    # образ (свой процесс = me, движок = sing-box, чтобы permit не перекрыл)
    ok = install_kill_switch(
        ["172.19.0.1/32"], engine_exe=str(SING_BOX),
        app_mode="include", app_names=[me],
    )
    check("T6 install(include block me)", "True", str(ok))
    check("T6 проба наружу (должен БЛОК)", "FAIL", _probe(*PEXT).split("(")[0])
    if gw:
        check("T6 проба LAN (не должна блок)", "OK", _probe(gw, 53))
    remove_kill_switch()

    # T7: exclude - permit образа «мимо VPN» перебивает глобальный блок
    ok = install_kill_switch(
        ["172.19.0.1/32"], engine_exe=str(SING_BOX),
        app_mode="exclude", app_names=[me],
    )
    check("T7 install(exclude permit me)", "True", str(ok))
    check("T7 проба наружу (permit)", "OK", _probe(*PEXT))
    remove_kill_switch()

    # T5: снятие - сеть свободна
    check("T5 проба после снятия", "OK", _probe(*PEXT))

    failed = [r for r in results if r[1] != r[2]]
    print(("SELFTEST: " + ("FAIL" if failed else "PASS")) + f" ({len(results) - len(failed)}/{len(results)})", flush=True)
    write_log(f"kill switch selftest: {len(results) - len(failed)}/{len(results)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print("используй: python -m vpn_launcher.win.wfp --selftest (нужен админ)")
