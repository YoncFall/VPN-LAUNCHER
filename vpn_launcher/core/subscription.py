# -*- coding: utf-8 -*-
"""Подписки и разбор нод. Порт src/core.ps1.

Источник:
    Get-SubscriptionNodes (core.ps1:392) -> fetch_nodes
    Parse-NodeList        (core.ps1:424) -> parse_node_list
"""
from __future__ import annotations

# Как в core.ps1:416 — сервер подписки должен видеть этот User-Agent
USER_AGENT = "sing-box/1.14.2"


def fetch_nodes(url: str) -> list[dict]:
    raise NotImplementedError("Этап 1: HTTP-загрузка подписки + b64/UTF-8")


def parse_node_list(body: str) -> list[dict]:
    raise NotImplementedError("Этап 1: разбор строк подписки в ноды")
