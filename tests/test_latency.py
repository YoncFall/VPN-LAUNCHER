# -*- coding: utf-8 -*-
"""Тесты TCP-пинга на живых локальных сокетах + честный пинг (30.09.2026)."""
import socket
import struct
import threading

import pytest

from vpn_launcher.core import latency
from vpn_launcher.core.latency import measure_node_latency
from vpn_launcher.win.routeif import (
    _ifindex_from_route_table,
    default_gateway_ifindex,
    unicast_if_bytes,
)


def _local_server() -> tuple[socket.socket, int, threading.Thread]:
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]

    def accept_loop() -> None:
        try:
            while True:
                conn, _ = srv.accept()
                conn.close()
        except OSError:
            pass

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    return srv, port, t


def test_latency_to_open_port_is_small():
    srv, port, _ = _local_server()
    try:
        ms = measure_node_latency({"server": "127.0.0.1", "server_port": port})
    finally:
        srv.close()
    assert 0 <= ms < 60  # localhost: срабатывает ранний выход PS-алгоритма


def test_latency_refused_returns_minus_one():
    # закрываем сокет сразу после bind: порт гарантированно свободен и отказ мгновенный
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert measure_node_latency(
        {"server": "127.0.0.1", "server_port": port}, timeout_ms=500
    ) == -1


# ---- честный пинг: IP_UNICAST_IF на физический интерфейс (30.09.2026) ------


def test_unicast_if_bytes_is_network_byte_order():
    # host order даёт WinError 10049 - защита от «упрощения» при рефакторинге
    assert unicast_if_bytes(15) == struct.pack("=I", socket.htonl(15))
    assert unicast_if_bytes(15) != struct.pack("=I", 15)


def test_loopback_ping_does_not_touch_discovery(monkeypatch):
    """loopback-цель идёт напрямую: привязка к физическому ifIndex не нужна."""

    def _boom() -> int:
        raise AssertionError("для loopback discovery вызываться не должен")

    monkeypatch.setattr(latency, "default_gateway_ifindex", _boom)
    srv, port, _ = _local_server()
    try:
        ms = measure_node_latency({"server": "127.0.0.1", "server_port": port})
    finally:
        srv.close()
    assert 0 <= ms < 60


def test_dns_failure_returns_minus_one():
    assert measure_node_latency(
        {"server": "no-such-host-vpl.invalid", "server_port": 443}, timeout_ms=500
    ) == -1


def test_non_loopback_ping_binds_physical_interface():
    """Не-loopback цель через реальный IP_UNICAST_IF - боевой сценарий пинга.

    Цель 1.1.1.1:443 (anycast, без DNS). Если привязка к физическому
    ifIndex сломана (опция отвергнута или connect не проходит), замер
    вернёт -1 - тест упадёт. На машине разработчика шлюзовый маршрут
    обязан найтись, иначе пинг вообще не имеет к чему привязаться.
    """
    if default_gateway_ifindex() is None:
        pytest.skip("шлюзовый маршрут 0.0.0.0/0 не найден")
    ms = measure_node_latency({"server": "1.1.1.1", "server_port": 443})
    assert 0 <= ms < 900, f"привязка к физическому ifIndex сломана: {ms}"
