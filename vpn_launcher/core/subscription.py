# -*- coding: utf-8 -*-
"""Подписки и разбор нод. Порт src/core.ps1, строки 392-450.

Источник:
    Get-SubscriptionNodes (core.ps1:392) -> fetch_nodes
    Parse-NodeList        (core.ps1:424) -> parse_node_list

Отклонения от 1.0.6 (сознательные, поведение VPN не затрагивают):
  - 1.0.6 (WebClient .NET Framework) декодирует тело подписки в ANSI
    (Encoding.Default, cp1251 на RU-системе) независимо от charset в ответе;
    здесь сначала пробуем UTF-8, иначе системная кодировка. B64- и
    ASCII-подписки (большинство) декодируются одинаково в обеих версиях;
    отличие видно только в display-именах с «сырой» кириллицей из UTF-8
    подписки (1.0.6 показывает mojibake, здесь - корректный текст).
  - сообщения исключений текстом совпадают с PS throw; тип - SubscriptionError.
  - транспорт: 1.0.6 (WebClient) качал что угодно, включая http:// с токеном
    подписки в открытом виде; здесь https обязателен для внешних адресов,
    http допустим только в локальной сети (свой IP-литерал или имя,
    резолвящееся в локальный адрес), а редирект на небезопасный адрес
    отклоняется вместе с телом ответа.
"""
from __future__ import annotations

import ipaddress
import locale
import re
import socket
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from vpn_launcher.core.log import write_log
from vpn_launcher.core.uris import b64_utf8_decode, parse_proxy_uri, split_uri

# Как в core.ps1:416 - сервер подписки должен видеть этот User-Agent
USER_AGENT = "sing-box/1.14.2"

# Как WebClient.Timeout в .NET (по умолчанию 100000 мс)
HTTP_TIMEOUT_S = 100

# Parse-NodeList:429 - узнаваемые схемы в начале строки
# PS `-notmatch` регистронезависим - флаг нужен и здесь
_SCHEME_RE = re.compile(r"^(vless|vmess|trojan|ss|hysteria2|hy2|tuic)://", re.IGNORECASE)
_LINE_RE = re.compile(r"\r?\n")

# PS `-match` регистронезависим, поэтому флаг IGNORECASE
_LOCAL_URL_RE = re.compile(r"^(https?|file)://", re.IGNORECASE)
_FILE_URL_RE = re.compile(r"^file://", re.IGNORECASE)


class SubscriptionError(RuntimeError):
    """PS `throw` из Get-SubscriptionNodes / Parse-NodeList."""


def _host_is_private(host: str) -> bool:
    """True - хост ведёт на локальную сеть (http допустим только там)."""
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        # имя, а не адрес: резолвим - для одного fetch этого достаточно
        try:
            addrs = [
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(host, None)
            ]
        except (OSError, ValueError):
            return False
    return any(a.is_private or a.is_loopback or a.is_link_local for a in addrs)


def _remote_url_allowed(url: str) -> bool:
    """https - всегда; http - только локальная сеть; прочее - нет.

    Отклонение от 1.0.6 (см. докстринг модуля): токен подписки не должен
    ехать по сети в открытом виде.
    """
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        host = parts.hostname
    except ValueError:
        return False
    if scheme == "https":
        return True
    if scheme != "http":
        return False
    return bool(host) and _host_is_private(host)


def _decode_body(raw: bytes) -> str:
    """Тело ответа -> строка (UTF-8, иначе ANSI; см. докстринг модуля)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


def _read_local(path: Path) -> str:
    """[IO.File]::ReadAllText($p, UTF8): строго UTF-8, битые байты -> замены."""
    return path.read_text(encoding="utf-8", errors="replace")


def fetch_nodes(url: str, *, logger: Callable[[str], None] = write_log) -> list[dict]:
    """Get-SubscriptionNodes: http(s)/file-URL или путь к файлу -> список нод."""
    if not url:
        raise SubscriptionError("Пустая ссылка на подписку")

    # локальный файл с подпиской (например подписка-зеркало .txt)
    if not _LOCAL_URL_RE.match(url):
        p = Path(url.strip('"'))
        if p.is_file():
            body = _read_local(p)
            logger("fetching subscription from local file: " + str(p))
            return parse_node_list(body, logger=logger)
        raise SubscriptionError("Нужна http(s)-ссылка либо путь к локальному файлу подписки")

    if _FILE_URL_RE.match(url):
        p = Path(unquote(url[7:]))
        body = _read_local(p)
        logger("fetching subscription from local file: " + str(p))
        return parse_node_list(body, logger=logger)

    try:
        host = urlsplit(url).hostname or "?"
    except ValueError:
        host = "?"
    if not _remote_url_allowed(url):
        raise SubscriptionError(
            "Подписка по http:// извне запрещена: токен пойдёт по сети "
            "в открытом виде. Нужен https://; для локального зеркала - "
            "путь к файлу либо адрес локальной сети."
        )
    logger("fetching subscription from host: " + host)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        raw = resp.read()
        final_url = resp.geturl() if hasattr(resp, "geturl") else None
    if final_url and not _remote_url_allowed(final_url):
        # сервер перевёл запрос (редирект) на http - тело не принимаем:
        # по открытому каналу его мог подменить кто угодно
        raise SubscriptionError(
            "Сервер подписки перевёл запрос на небезопасный адрес: " + final_url
        )
    if not raw:
        raise SubscriptionError("Пустой ответ сервера подписки")
    return parse_node_list(_decode_body(raw), logger=logger)


def parse_node_list(body: str, *, logger: Callable[[str], None] = write_log) -> list[dict]:
    """Parse-NodeList: текст подписки (или b64) -> список нод с display/proto."""
    if not body:
        raise SubscriptionError("Пустой текст подписки")

    # если это base64 - декодируем
    t = re.sub(r"\s", "", body)
    if not _SCHEME_RE.match(t):
        dec = b64_utf8_decode(t)
        body = dec if "://" in dec else t

    lines = [ln for ln in (x.strip() for x in _LINE_RE.split(body)) if "://" in ln]
    nodes: list[dict] = []
    for i, line in enumerate(lines, 1):
        o = parse_proxy_uri(line, i, logger=logger)
        if o:
            frag = split_uri(line)["Fragment"]
            o["display"] = frag if frag else f"{o['server']}:{o['server_port']}"
            o["proto"] = o["type"]
            nodes.append(o)
    logger(f"  parsed {len(nodes)} of {len(lines)} lines")
    if not nodes:
        raise SubscriptionError("Не удалось распознать ни одного сервера в подписке")
    return nodes
