# -*- coding: utf-8 -*-
"""TCP-пинг нод. Порт Measure-NodeLatency (core.ps1:587-618).

Алгоритм дословно: TCP connect, до `attempts` попыток, берём лучший результат,
прерываемся сразу, если результат < 60 мс. Возвращает миллисекунды или -1.

Отклонения от 1.0.6 (30.09.2026, диагностика «пинг врёт 0-2 мс»):
  - DNS-разрешение вынесено ЗА пределы замера времени: пинг должен мерить
    RTT до нода, а не скорость локального резолвера (create_connection
    включал getaddrinfo в замер);
  - не-loopback адреса привязываются к физическому интерфейсу через
    IP_UNICAST_IF (win/routeif): с поднятым туннелем обычный connect
    принимается локально смешанным стеком sing-box (0-2 мс на любой
    адрес), а чужой VPN (Happ) ловит соединения локальным accept'ом.
    Привязка уводит сокет на шлюзовый интерфейс - замер идёт по настоящему
    пути. Если ifIndex добыть не удалось, работает старый путь без привязки.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from typing import Mapping

from vpn_launcher.win.routeif import (
    IP_UNICAST_IF,
    default_gateway_ifindex,
    unicast_if_bytes,
)

FAST_MS = 60  # порог раннего выхода, как в PS


def _resolve(host: str, port: int) -> tuple[int, str] | None:
    """getaddrinfo -> (family, адрес); None при ошибке (-> -1, как OSError в PS)."""
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except OSError:
        return None
    v4 = [i for i in infos if i[0] == socket.AF_INET]
    pick = (v4 or infos)[0]
    return pick[0], pick[4][0]


def _is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def _connect(
    family: int,
    addr: str,
    port: int,
    timeout: float,
    ifindex: int | None,
) -> socket.socket | None:
    """connect с опциональной привязкой к физическому интерфейсу.

    Привязка не принимается - пингуем честно невозможное, возвращаем None
    вместо локально-ложных миллисекунд.
    """
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    if ifindex is not None:
        level = socket.IPPROTO_IPV6 if family == socket.AF_INET6 else socket.IPPROTO_IP
        try:
            sock.setsockopt(level, IP_UNICAST_IF, unicast_if_bytes(ifindex))
        except OSError:
            sock.close()
            return None
    try:
        sock.connect((addr, port))
    except OSError:
        sock.close()
        return None
    return sock


def measure_node_latency(
    node: Mapping,
    timeout_ms: int = 2500,
    attempts: int = 2,
) -> int:
    """`node` — dict с ключами 'server' и 'server_port' (как у PS-нод)."""
    host = str(node["server"])
    port = int(node["server_port"])
    target = _resolve(host, port)
    if target is None:
        return -1
    family, addr = target
    # loopback (тесты, локальные ноды) физический интерфейс не касается
    ifindex = None if _is_loopback(addr) else default_gateway_ifindex()
    best = -1
    for _ in range(attempts):
        started = time.perf_counter()
        sock = _connect(family, addr, port, timeout_ms / 1000.0, ifindex)
        if sock is None:
            break
        try:
            ms = int((time.perf_counter() - started) * 1000)
        finally:
            sock.close()
        if best < 0 or ms < best:
            best = ms
        if best < FAST_MS:
            break
    return best
