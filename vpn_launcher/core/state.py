# -*- coding: utf-8 -*-
"""Состояние приложения. Порт Get-VpnState/Save-VpnState (core.ps1:630-641).

Файл: <install root>/state.json. Поля (точно как в PS):
    subUrl, mode ('tun'), selected, appList, lastNodes, autoUrlTest.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vpn_launcher.paths import STATE_FILE


def _default_state() -> dict[str, Any]:
    return {
        "subUrl": "",
        "mode": "tun",
        "selected": "",
        "appList": [],
        "lastNodes": [],
        "autoUrlTest": True,
    }


DEFAULT_STATE = _default_state()


def load_state(path: Path | None = None) -> dict[str, Any]:
    """Файл отсутствует или битый -> дефолт (как catch в PS)."""
    p = path or STATE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return _default_state()


def save_state(st: dict[str, Any], path: Path | None = None) -> None:
    p = path or STATE_FILE
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
