# -*- coding: utf-8 -*-
"""Адрес приёмника отчётов диагностики.

Приёмник живёт на ПК владельца сборки (Tailscale Funnel или свой VPS).
Адрес НЕ секрет: в приложении лежит только публичный ключ шифрования.
Адрес можно поменять без выпуска новой версии - он читается из apps.json
(поле `diagnosticsUrl` у приложения vpn-launcher) и кэшируется на время
работы; если сайт недоступен, используется значение ниже.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from vpn_launcher.core.update import APPS_JSON_URL, SLUG, pick_app

# Заполняется при настройке приёмника. Пусто -> отправка выключена,
# отчёт всё равно сохраняется локально и открывается кнопкой.
DEFAULT_DIAG_ENDPOINT = ""

_CACHE_TTL = 600.0
_cache: dict[str, object] = {"at": 0.0, "url": ""}


def _valid(url: str) -> bool:
    if not url or len(url) > 300 or any(ch.isspace() for ch in url):
        return False
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and bool(parts.netloc)


def resolve_endpoint(timeout: float = 8.0) -> str:
    """apps.json diagnosticsUrl -> DEFAULT_DIAG_ENDPOINT (или "")."""
    now = time.monotonic()
    cached_at = float(_cache.get("at") or 0.0)
    if cached_at and now - cached_at < _CACHE_TTL:
        return str(_cache.get("url") or "")

    url = ""
    try:
        req = urllib.request.Request(
            APPS_JSON_URL, headers={"User-Agent": "VPN-LAUNCHER/diagnostics"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8", "replace").lstrip("\ufeff"))
        app = pick_app(payload, SLUG) or {}
        candidate = str(app.get("diagnosticsUrl") or "")
        if _valid(candidate):
            url = candidate
    except (OSError, ValueError, TypeError):
        url = ""

    if not url:
        url = DEFAULT_DIAG_ENDPOINT
    _cache["at"] = now
    _cache["url"] = url
    return url
