# -*- coding: utf-8 -*-
"""Тесты TCP-пинга на живых локальных сокетах."""
import socket
import threading

from vpn_launcher.core.latency import measure_node_latency


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
