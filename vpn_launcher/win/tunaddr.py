# -*- coding: utf-8 -*-
"""Свободный адрес для TUN-инбаунда: адреса интерфейсов + подбор из пула.

Зачем это появилось (отклонение от 1.0.6):
    адрес TUN-инбаунда в PS-версии зашит в конфиг - 172.19.0.1/30. Если такой
    адрес уже назначен ДРУГОМОУ интерфейсу (на машине разработчика так делал
    Happ: адаптер happ-xray держит 172.19.0.1/30), Windows отказывается
    назначить его второму адаптеру:

        FATAL ... configure tun interface: set ipv4 address: The object already exists

    sing-box гибнет на старте -> TUN «не работает». В журнале приложения видно
    только саму попытку (config written: mode=tun), падение движка остаётся в
    singbox.log.err, а он обрезается при каждом старте (win/proc.py) - то есть
    диагностировать по логам такой сбой почти невозможно.

    Проверено на этой машине: тот же конфиг с тем же именем адаптера, но со
    свободным адресом (172.20.31.1/30) поднимается и живёт (inbound/tun
    started, sing-box started).

Решение: перед сборкой конфига читаем адреса всех интерфейсов и берём первый
незанятый кандидат. Первый кандидат - исторический 172.19.0.1/30 (паритет с
1.0.6 и golden-файлами): на машине без конфликтов меняется ничего.

Ограничения (сознательные):
    - проверяются только АДРЕСА, не маршруты: чужой маршрут, не имеющий своего
      адреса в нашем пуле, останется незамеченным;
    - любая ошибка WinAPI -> пустое множество -> выбирается первый кандидат
      (поведение 1.0.6). Диагностика не должна валить приложение.
"""
from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes
from ipaddress import ip_address, ip_network
from typing import Iterable

AF_INET = 2
AF_INET6 = 23
AF_UNSPEC = 0
GAA_FLAG_INCLUDE_PREFIX = 0x0010
ERROR_BUFFER_OVERFLOW = 111
_MAX_ADAPTERS = 512

# Пул адресов: /30 (2 рабочих хоста), шаг 4 - чтобы подсети не пересекались.
# Первый кандидат как в 1.0.6; 198.18.0.0/15 (RFC 2544) - запасной диапазон,
# в обычных домашних сетях не используется.
TUN_V4_CANDIDATES: tuple[str, ...] = (
    tuple(f"172.19.0.{i}/30" for i in range(1, 254, 4)) + ("198.18.0.1/30",)
)
TUN_V6_CANDIDATES: tuple[str, ...] = tuple(
    f"fdfe:dcba:9876::{i}/126" for i in range(1, 254, 4)
)

# --- WinAPI: GetAdaptersAddresses (iphlpapi) --------------------------------
# Раскладки x64: у обеих структур берём только нужные поля, отступы сверены с
# ipifcons.h - Length(0)/IfIndex(4)/Next(8)/AdapterName(16)/FirstUnicast(24) и
# Length(0)/Flags(4)/Next(8)/SocketAddress(16).

_iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)


class _SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", wintypes.INT)]


class _UNICAST_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("Flags", wintypes.DWORD),
        ("Next", ctypes.c_void_p),
        ("Address", _SOCKET_ADDRESS),
    ]


class _ADDRESSES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("IfIndex", wintypes.DWORD),
        ("Next", ctypes.c_void_p),
        ("AdapterName", ctypes.c_void_p),
        ("FirstUnicastAddress", ctypes.c_void_p),
    ]


_iphlpapi.GetAdaptersAddresses.argtypes = (
    wintypes.ULONG,
    wintypes.ULONG,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.ULONG),
)
_iphlpapi.GetAdaptersAddresses.restype = wintypes.DWORD


def _packed_address(sockaddr: int) -> str | None:
    """sockaddr* -> строка адреса ('172.19.0.1' / 'fdfe::1'), иначе None."""
    if not sockaddr:
        return None
    family = ctypes.c_ushort.from_address(sockaddr).value
    if family == AF_INET:
        raw = (ctypes.c_ubyte * 4).from_address(sockaddr + 4)
    elif family == AF_INET6:
        raw = (ctypes.c_ubyte * 16).from_address(sockaddr + 8)
    else:
        return None
    return socket.inet_ntop(family, bytes(raw))


def _assigned_addresses() -> set[str]:
    size = wintypes.ULONG(16 * 1024)
    buf = ctypes.create_string_buffer(size.value)
    rc = _iphlpapi.GetAdaptersAddresses(
        AF_UNSPEC, GAA_FLAG_INCLUDE_PREFIX, None, buf, ctypes.byref(size)
    )
    if rc == ERROR_BUFFER_OVERFLOW:
        buf = ctypes.create_string_buffer(size.value)
        rc = _iphlpapi.GetAdaptersAddresses(
            AF_UNSPEC, GAA_FLAG_INCLUDE_PREFIX, None, buf, ctypes.byref(size)
        )
    if rc != 0:  # NO_ERROR = 0
        return set()

    lo, hi = ctypes.addressof(buf), ctypes.addressof(buf) + len(buf)
    out: set[str] = set()
    cur = ctypes.cast(buf, ctypes.POINTER(_ADDRESSES))
    for _ in range(_MAX_ADAPTERS):
        if not cur or not cur.contents.FirstUnicastAddress:
            break
        ua = ctypes.cast(
            cur.contents.FirstUnicastAddress, ctypes.POINTER(_UNICAST_ADDRESS)
        )
        for _ in range(_MAX_ADAPTERS):  # адресов на адаптер немного
            if not ua:
                break
            addr = _packed_address(ua.contents.Address.lpSockaddr)
            if addr:
                out.add(addr)
            if not ua.contents.Next:
                break
            ua = ctypes.cast(ua.contents.Next, ctypes.POINTER(_UNICAST_ADDRESS))
        if not cur.contents.Next or not lo <= cur.contents.Next < hi:
            break  # ушли за пределы буфера - дальше не доверяем указателю
        cur = ctypes.cast(cur.contents.Next, ctypes.POINTER(_ADDRESSES))
    return out


def assigned_addresses() -> set[str]:
    """Все unicast-адреса всех интерфейсов этой машины (IPv4 и IPv6).

    best-effort: при любой ошибке -> пустое множество (см. докстринг модуля).
    """
    try:
        return _assigned_addresses()
    except Exception:
        return set()


# --- подбор -----------------------------------------------------------------


def _first_free(candidates: Iterable[str], used: set[str]) -> str | None:
    """Первый кандидат, чья подсеть не содержит ни одного занятого адреса."""
    for cand in candidates:
        net = ip_network(cand, strict=False)
        if not any(ip in net for ip in used):
            return cand
    return None


def choose_tun_addresses(assigned: Iterable[str] | None = None) -> list[str]:
    """Адреса [v4, v6] для TUN-инбаунда; v6 опускается, если свободных нет.

    assigned - занятые адреса (строки); None -> читаем у системы.
    """
    if assigned is None:
        assigned = assigned_addresses()
    used: set[str] = set()
    for a in assigned:
        try:
            used.add(ip_address(a))
        except ValueError:
            continue

    v4 = _first_free(TUN_V4_CANDIDATES, used) or TUN_V4_CANDIDATES[0]
    v6 = _first_free(TUN_V6_CANDIDATES, used)
    return [v4] + ([v6] if v6 else [])
