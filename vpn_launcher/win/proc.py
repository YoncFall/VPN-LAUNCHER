# -*- coding: utf-8 -*-
"""Процессы: список запущенных .exe, запуск/останов sing-box.

Порт Get-RunningExeList/Add-Excl (VPN.ps1) и работы с $script:SingBox (core.ps1).

Статус: Этап 2 (процессы) / Этап 5 (управление sing-box).
"""
from __future__ import annotations


def get_running_exe_list() -> list[str]:
    raise NotImplementedError("Этап 2: уникальные имена запущенных .exe")


def start_sing_box(config_path: str) -> int:
    raise NotImplementedError("Этап 5: subprocess sing-box run -c <config>")


def stop_sing_box() -> None:
    raise NotImplementedError("Этап 5")
