# -*- coding: utf-8 -*-
"""Автозапуск с Windows (реестр Run). Порт соответствующей ветки VPN.ps1.

Статус: Этап 2.
"""
from __future__ import annotations


def is_autostart_enabled() -> bool:
    raise NotImplementedError("Этап 2")


def set_autostart(enabled: bool) -> None:
    raise NotImplementedError("Этап 2")
