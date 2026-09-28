# -*- coding: utf-8 -*-
"""Корень установки и ключевые пути. Порт core.ps1:7-21.

Раскладки (как в PowerShell-версии):
  - плоская (установщик): скрипты/движок в одной папке;
  - dev: пакет vpn_launcher/ лежит в корне проекта уровнем выше.
"""
from __future__ import annotations

import sys
from pathlib import Path

SOCKS_PORT = 20808


def install_root() -> Path:
    """Корень данных (там же state.json / config.json / vpn-launcher.log)."""
    if getattr(sys, "frozen", False):  # PyInstaller: рядом с VPNLauncher.exe
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent  # .../vpn_launcher
    if (here / "sing-box.exe").exists():  # плоская раскладка, как в PS
        return here
    return here.parent  # корень проекта (dev)


STATE_FILE = install_root() / "state.json"
CONFIG_FILE = install_root() / "config.json"
LOG_FILE = install_root() / "vpn-launcher.log"
SING_BOX = install_root() / "sing-box.exe"
