# -*- coding: utf-8 -*-
"""Single instance (аналог мьютекса Host.cs): второе окно только восстанавливает первое.

Статус: Этап 2 (CreateMutexW + обнаружение уже запущенного экземпляра).
"""
from __future__ import annotations

MUTEX_NAME = r"Local\VPNLauncher_SingleInstance"


def acquire_instance() -> bool:
    """True — это первый экземпляр; False — уже запущен (поднять окно)."""
    raise NotImplementedError("Этап 2")
