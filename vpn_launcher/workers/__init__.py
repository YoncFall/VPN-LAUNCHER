# -*- coding: utf-8 -*-
"""Фоновые задачи Qt (QThread). Этап 5.

Соответствие модели 1.0.6 (VPN.ps1): UI не должен замерзать, пока идёт сеть.
  - SubscriptionWorker - btnLoad.Add_Click (VPN.ps1:120): Get-SubscriptionNodes
    в фоне, результат сигналами в главный поток (в PS - синхронный вызов с
    DoEvents; здесь - поток, состояние «Загрузка...»/статусы те же);
  - PingWorker - runspace-джоб пинга (VPN.ps1:379-438): обход нод TCP-пингом,
    поштучные результаты (в PS - очередь + таймер 200мс, текст статуса тот же);
  - EgressWorker - опрос внешнего IP в тике (VPN.ps1:630-640): 8с таймаут,
    ошибка -> 'Внешний IP недоступен' (в PS запрос синхронно блокировал UI;
    здесь фон - отклонение, визуальный результат идентичен).
"""
from __future__ import annotations

import json
import urllib.request

from PySide6.QtCore import QThread, Signal

from vpn_launcher.core.latency import measure_node_latency
from vpn_launcher.core.subscription import fetch_nodes

EGRESS_URL = "https://api.ipify.org?format=json"  # VPN.ps1:632


class SubscriptionWorker(QThread):
    """Загрузка и разбор подписки; loaded(nodes) | failed(текст)."""

    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            self.loaded.emit(fetch_nodes(self._url))
        except Exception as exc:  # как catch в btnLoad
            self.failed.emit(str(exc))


class PingWorker(QThread):
    """Последовательный TCP-пинг всех нод; result(tag, ms) | failed(текст).

    Между нодами проверяется прерывание (порт BeginStop из FormClosing,
    VPN.ps1:645): closeEvent дергает cancel() и ждёт завершения.
    """

    result = Signal(str, int)
    failed = Signal(str)

    def __init__(self, nodes: list[dict]) -> None:
        super().__init__()
        self._nodes = list(nodes)

    def cancel(self) -> None:
        self.requestInterruption()

    def run(self) -> None:
        try:
            for node in self._nodes:
                if self.isInterruptionRequested():
                    return
                ms = measure_node_latency(node)
                self.result.emit(str(node.get("tag") or ""), ms)
        except Exception as exc:
            self.failed.emit(str(exc))


class EgressWorker(QThread):
    """Один запрос внешнего IP; got(ip) | failed(текст)."""

    got = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                EGRESS_URL, headers={"User-Agent": "vpn-launcher"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                ip = json.loads(resp.read().decode("utf-8", "replace")).get("ip")
            if not ip:
                raise ValueError("no ip in response")
            self.got.emit(str(ip))
        except Exception as exc:
            self.failed.emit(str(exc))
