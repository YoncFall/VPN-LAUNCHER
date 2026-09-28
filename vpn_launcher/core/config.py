# -*- coding: utf-8 -*-
"""Генерация и проверка конфига sing-box. Порт src/core.ps1.

Источник:
    New-SingBoxConfig  (core.ps1:466) -> new_sing_box_config
    Test-SingBoxConfig (core.ps1:620) -> test_sing_box_config

Правило этапа 1: вывод обязан быть эквивалентен PowerShell-версии
(golden-файлы в tools/golden/ + прогон `sing-box check`).
"""
from __future__ import annotations

from typing import Any


def new_sing_box_config(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError("Этап 1: генерация конфига + golden-тесты")


def test_sing_box_config(path: str) -> tuple[bool, str]:
    raise NotImplementedError("Этап 2: вызов sing-box check -c <path>")
