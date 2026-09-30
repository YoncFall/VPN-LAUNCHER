# -*- coding: utf-8 -*-
"""ifIndex провайдерского (шлюзового) маршрута 0.0.0.0/0 - для честного пинга.

Зачем (диагностика 30.09.2026):
    TCP-пинг нод в обход туннеля/чужого VPN должен идти по ФЗИЗИЧЕСКОМУ
    интерфейсу, иначе две ловушки:

      1. с поднятым туннелем connect() до ноды принимает локально сам
         sing-box (смешанный стек) -> 0-2 мс на любой адрес, пинг врёт;
      2. чужой VPN (Happ) ловит соединения локальным accept'ом -> тоже
         не честные миллисекунды.

    Решение: socket.setsockopt(IPPROTO_IP, IP_UNICAST_IF(31), htonl(ifIndex))
    принудительно уводит сокет на физический интерфейс - проверено вживую
    (без туннеля: 48-67 мс до ноды вместо локально-ложных). WFP-блоков при
    этом нет - strict_route выключен (см. core/config.py).

Как узнаём ifIndex:
    `netsh interface ipv4 show route` -> строка маршрута 0.0.0.0/0 с
    БЕГОВЫМ шлюзом (числовой IP). Маршруты туннеля и чужого VPN идут
    on-link (шлюз = имя интерфейса или 0.0.0.0) и отсекаются фильтром;
    loopback-шлюз 127.* тоже не годится. Это единственный маршрут, который
    указывает на реальный выход в интернет у большинства машин.
    netsh отрабатывает за ~80 мс, результат кэшируется на весь процесс.
"""
from __future__ import annotations

import re
import socket
import struct
import subprocess
import threading

# IP_UNICAST_IF: в Python 3.12 константы нет, опкод 31 работает как сырой.
# Значение обязано лежать в СЕТЕВОМ порядке байт (иначе WinError 10049),
# отсюда htonl(ifindex) внутри структуры.
IP_UNICAST_IF = 31

# netsh: "Нет Вручную 0 0.0.0.0/0 15 192.168.0.1" (заголовки локализованы,
# цифры и префикс - нет; имя шлюза может быть и строкой - не матчится).
_ROUTE_RE = re.compile(r"0\.0\.0\.0/0\s+(\d+)\s+(\d{1,3}(?:\.\d{1,3}){3})\s*$")

_cache: int | None | bool = False  # False = ещё не пробовали, None = не найден
_lock = threading.Lock()


def _ifindex_from_route_table(text: str) -> int | None:
    """Первый ifIndex маршрута 0.0.0.0/0 с настоящим шлюзом (чистая функция)."""
    for line in text.splitlines():
        m = _ROUTE_RE.search(line.strip())
        if not m:
            continue
        gateway = m.group(2)
        # loopback и 0.0.0.0 (on-link: туннель/чужой VPN) - не выход в интернет
        if gateway.startswith("127.") or gateway == "0.0.0.0":
            continue
        return int(m.group(1))
    return None


def default_gateway_ifindex(timeout: float = 3.0) -> int | None:
    """ifIndex физического интерфейса по умолчанию; None, если не найден.

    Результат (включая отрицательный) кэшируется: маршрут шлюза на машине
    не меняется на время работы приложения.
    """
    global _cache
    with _lock:
        if _cache is not False:
            return None if _cache is None else int(_cache)
        idx: int | None = None
        try:
            out = subprocess.run(
                ["netsh", "interface", "ipv4", "show", "route"],
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            # ASCII-цифры кодовой страницы (cp866/cp1251) не искажаются
            text = out.stdout.decode("utf-8", errors="replace")
            idx = _ifindex_from_route_table(text)
        except (OSError, subprocess.SubprocessError):
            idx = None
        _cache = idx if idx is not None else None
        return idx


def unicast_if_bytes(ifindex: int) -> bytes:
    """Значение опции IP_UNICAST_IF: network byte order (см. докстринг модуля)."""
    return struct.pack("=I", socket.htonl(ifindex))
