# -*- coding: utf-8 -*-
"""Журнал. Порт Write-VpnLog (core.ps1:25-33).

Строка: 'yyyy-MM-dd HH:mm:ss  <message>' (два пробела), UTF-8.
Файл больше 2 МБ удаляется перед записью (ротация как в PS).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from vpn_launcher.paths import LOG_FILE

MAX_LOG_SIZE = 2 * 1024 * 1024


def write_log(msg: str, path: Path | None = None) -> None:
    p = path or LOG_FILE
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:
        if p.exists() and p.stat().st_size > MAX_LOG_SIZE:
            p.unlink()
        with p.open("a", encoding="utf-8", newline="") as f:
            f.write(line + "\r\n")
    except OSError:
        pass
