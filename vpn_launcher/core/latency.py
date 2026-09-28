# -*- coding: utf-8 -*-
"""TCP-пинг нод. Порт Measure-NodeLatency (core.ps1:587-618).

Алгоритм дословно: TCP connect, до `attempts` попыток, берём лучший результат,
прерываемся сразу, если результат < 60 мс. Возвращает миллисекунды или -1.
"""
from __future__ import annotations

import socket
import time
from typing import Mapping

FAST_MS = 60  # порог раннего выхода, как в PS


def measure_node_latency(
    node: Mapping,
    timeout_ms: int = 2500,
    attempts: int = 2,
) -> int:
    """`node` — dict с ключами 'server' и 'server_port' (как у PS-нод)."""
    host = str(node["server"])
    port = int(node["server_port"])
    best = -1
    for _ in range(attempts):
        started = time.perf_counter()
        try:
            sock = socket.create_connection((host, port), timeout=timeout_ms / 1000.0)
        except OSError:
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
