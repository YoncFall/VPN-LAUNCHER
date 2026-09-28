# -*- coding: utf-8 -*-
"""Повышение прав. Порт --autoconnect-ветки (VPN.ps1) через ShellExecuteW 'runas'.

Статус: Этап 2.
"""
from __future__ import annotations


def is_elevated() -> bool:
    raise NotImplementedError("Этап 2")


def relaunch_elevated(args: list[str]) -> None:
    raise NotImplementedError("Этап 2")
