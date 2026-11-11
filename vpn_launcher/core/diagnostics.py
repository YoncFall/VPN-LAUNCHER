# -*- coding: utf-8 -*-
"""Диагностика Discord/YouTube и обезличенный отчёт для владельца сборки.

Зачем (просьба 11.11.2026): у друга зелёная лампа DPI, но Discord висит на
Starting. Обычный журнал приложения показывает только действия лаунчера, а
не состояние сети, поэтому по нему нельзя поставить диагноз. Здесь
собирается один самодостаточный отчёт: DNS/TCP/TLS/HTTP по каждому
эндпоинту Discord и YouTube, сетевые параметры, состояние winws/sing-box,
хвосты журналов и готовый вердикт «что делать».

Приватность:
  - из отчёта удаляются имя пользователя в путях, ссылки подписки,
    UUID/токены, e-mail, MAC, внешние IP в текстовых хвостах;
  - URL подписки в отчёт не попадает вообще (state читается выборочно);
  - отчёт шифруется публичным ключом владельца (X25519 + HKDF + AES-GCM),
    приватный ключ есть только на ПК владельца;
  - локальная копия всегда остаётся у пользователя.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from vpn_launcher import __version__
from vpn_launcher.core.diag_key import DIAG_PUBLIC_KEY
from vpn_launcher.core.log import write_log
from vpn_launcher.paths import LOG_FILE, install_root

# Эндпоинты Discord: по каждому отдельно DNS -> TCP -> TLS. gateway.discord.gg
# и updates.discord.com отдают 404 на обычный GET - это норма, важен сам
# факт ответа. cdn/media обязательны: без них страница Discord не грузится.
DISCORD_HOSTS: tuple[str, ...] = (
    "discord.com",
    "gateway.discord.gg",
    "cdn.discordapp.com",
    "media.discordapp.net",
    "updates.discord.com",
    "discordapp.com",
)
YOUTUBE_HOSTS: tuple[str, ...] = (
    "www.youtube.com",
    "i.ytimg.com",
    "redirector.googlevideo.com",
)
HTTP_PROBES: tuple[str, ...] = (
    "https://discord.com/api/v9/gateway",
    "https://gateway.discord.gg/api/gateway",
    "https://cdn.discordapp.com/",
    "https://media.discordapp.net/",
    "https://updates.discord.com/",
    "https://www.youtube.com/",
    "https://i.ytimg.com/",
    "https://redirector.googlevideo.com/",
)

DNS_TIMEOUT = 6.0
TCP_TIMEOUT = 5.0
TLS_TIMEOUT = 7.0
HTTP_TIMEOUT = 8.0
MAX_REPORT_BYTES = 256 * 1024
MAX_SEND_BYTES = 192 * 1024
LOG_TAIL_LINES = 80
LOG_TAIL_MAX = 12_000

DIAG_DIR = install_root() / "diagnostics"

_CREATE_NO_WINDOW = 0x08000000

# ---- редакция персональных данных ----------------------------------------

_HOME_WIN = re.compile(r"([A-Za-z]:\\Users\\)([^\\\s\"']+)", re.I)
_HOME_NIX = re.compile(r"(/home/)([^/\s\"']+)")
_PROXY_URI = re.compile(
    r"\b(?:vless|vmess|vless|ss|ssr|trojan|hysteria2?|hy2|tuic|wireguard|wg)://[^\s\"']+",
    re.I,
)
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
_DISCORD_TOKEN = re.compile(r"\b[\w-]{20,}\.[\w-]{6}\.[\w-]{25,}\b")
_QUERY_SECRET = re.compile(
    r"([?&](?:token|key|sub|uuid|password|passwd|secret|auth|sig|signature|"
    r"expires|user|username)=)[^&\s\"']+",
    re.I,
)
_AUTH_HEADER = re.compile(r"(?i)(authorization\s*[:=]\s*)(\S+)")
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{24,}(?![A-Za-z0-9_\-])")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")


def redact(text: str) -> str:
    """Убрать из строки всё, что может указать на человека или подписку."""
    s = str(text)
    s = _HOME_WIN.sub(r"\1<user>", s)
    s = _HOME_NIX.sub(r"\1<user>", s)
    s = _PROXY_URI.sub("<subscription-link>", s)
    s = _DISCORD_TOKEN.sub("<token>", s)
    s = _UUID.sub("<uuid>", s)
    s = _EMAIL.sub("<email>", s)
    s = _QUERY_SECRET.sub(r"\1<redacted>", s)
    s = _AUTH_HEADER.sub(r"\1<redacted>", s)
    s = _LONG_TOKEN.sub("<token>", s)
    # имя ПК и пользователя - если встречаются отдельными словами
    for secret in {socket.gethostname(), os.environ.get("USERNAME", "")}:
        if secret and len(secret) > 2:
            s = re.sub(rf"(?<![A-Za-z0-9_-]){re.escape(secret)}(?![A-Za-z0-9_-])", "<host>", s, flags=re.I)
    return s


def redact_log(text: str) -> str:
    """Хвосты журналов: дополнительно скрываем IP и MAC."""
    s = redact(text)
    s = _MAC.sub("<mac>", s)
    s = _IPV4.sub("<ip>", s)
    return s


def _redact_obj(value: Any, *, log: bool = False) -> Any:
    if isinstance(value, str):
        return redact_log(value) if log else redact(value)
    if isinstance(value, list):
        return [_redact_obj(v, log=log) for v in value]
    if isinstance(value, dict):
        return {
            str(k): _redact_obj(v, log=log or str(k) in {"logTail", "args"})
            for k, v in value.items()
        }
    return value


# ---- шифрование отчёта ----------------------------------------------------

MAGIC = b"VLDR1"
_HKDF_INFO = b"vpn-launcher-diag-v1"


def encrypt_report(data: bytes, public_key_b64: str = DIAG_PUBLIC_KEY) -> bytes:
    """ECIES: эфемерный X25519 -> HKDF-SHA256 -> AES-256-GCM.

    Формат: MAGIC(5) | ephemeral_pub(32) | nonce(12) | ciphertext+GCM tag.
    Приватного ключа здесь нет - приложение физически не может прочитать
    то, что отправило.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey,
        X25519PublicKey,
    )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    pub_raw = base64.b64decode(public_key_b64)
    if len(pub_raw) != 32:
        raise ValueError("public key must be 32 bytes")
    peer = X25519PublicKey.from_public_bytes(pub_raw)
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(peer)
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=MAGIC, info=_HKDF_INFO
    ).derive(shared)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, MAGIC)
    eph_pub = eph.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return MAGIC + eph_pub + nonce + ct


def decrypt_report(blob: bytes, private_key_b64: str) -> bytes:
    """Обратная операция (только приёмник владельца)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey,
        X25519PublicKey,
    )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 32 + 12:
        raise ValueError("bad envelope")
    off = len(MAGIC)
    eph_pub = blob[off : off + 32]
    nonce = blob[off + 32 : off + 44]
    ct = blob[off + 44 :]
    priv_raw = base64.b64decode(private_key_b64)
    priv = X25519PrivateKey.from_private_bytes(priv_raw)
    shared = priv.exchange(X25519PublicKey.from_public_bytes(eph_pub))
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=MAGIC, info=_HKDF_INFO
    ).derive(shared)
    return AESGCM(key).decrypt(nonce, ct, MAGIC)


# ---- сетевые пробы --------------------------------------------------------


def _bounded(fn: Callable[[], Any], timeout: float) -> Any:
    """Выполнить fn, но не ждать дольше timeout (getaddrinfo не умеет timeout)."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - вернуть как есть
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"timeout {timeout:.0f}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def dns_probe(host: str, timeout: float = DNS_TIMEOUT) -> dict[str, Any]:
    """A/AAAA-записи хоста; ms - сколько занял запрос."""
    started = time.monotonic()
    out: dict[str, Any] = {"host": host, "ms": None, "v4": [], "v6": [], "error": ""}
    try:
        infos = _bounded(
            lambda: socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout
        )
        for fam, _st, _pr, _cn, sa in infos:
            ip = str(sa[0])
            if fam == socket.AF_INET and ip not in out["v4"]:
                out["v4"].append(ip)
            elif fam == socket.AF_INET6 and ip not in out["v6"]:
                out["v6"].append(ip)
        if not out["v4"] and not out["v6"]:
            out["error"] = "no addresses"
    except BaseException as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["ms"] = int((time.monotonic() - started) * 1000)
    return out


def tcp_probe(host: str, ip: str, port: int = 443, timeout: float = TCP_TIMEOUT) -> dict[str, Any]:
    started = time.monotonic()
    out: dict[str, Any] = {
        "host": host, "ip": ip, "port": port, "ms": None, "ok": False, "error": ""
    }
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            out["ok"] = True
    except BaseException as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["ms"] = int((time.monotonic() - started) * 1000)
    return out


def tls_probe(host: str, ip: str, port: int = 443, timeout: float = TLS_TIMEOUT) -> dict[str, Any]:
    started = time.monotonic()
    out: dict[str, Any] = {
        "host": host, "ip": ip, "port": port, "ms": None, "ok": False,
        "version": "", "cipher": "", "alpn": "", "error": "",
    }
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((ip, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as s:
                out["ok"] = True
                out["version"] = s.version() or ""
                cipher = s.cipher()
                out["cipher"] = cipher[0] if cipher else ""
                out["alpn"] = s.selected_alpn_protocol() or ""
    except BaseException as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["ms"] = int((time.monotonic() - started) * 1000)
    return out


def http_probe(url: str, timeout: float = HTTP_TIMEOUT) -> dict[str, Any]:
    """GET без системного прокси: проверяем именно прямой транспорт.

    Любой HTTP-ответ (включая 4xx) означает, что трафик проходит; 5xx -
    сбой на стороне CDN/фильтра, считаем ошибкой.
    """
    started = time.monotonic()
    out: dict[str, Any] = {"url": url, "status": None, "ms": None, "error": ""}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            out["status"] = int(resp.status)
    except urllib.error.HTTPError as exc:
        out["status"] = int(exc.code)
        if int(exc.code) >= 500:
            out["error"] = f"HTTP {exc.code}"
    except BaseException as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    out["ms"] = int((time.monotonic() - started) * 1000)
    return out


# ---- система и окружение --------------------------------------------------


def _ps_json(script: str, timeout: float = 20.0) -> Any:
    """Выполнить PowerShell и разобрать JSON (пусто -> None)."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        text = proc.stdout.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        return json.loads(text.lstrip("\ufeff"))
    except BaseException:  # noqa: BLE001 - диагностика не должна падать
        return None


def collect_network() -> dict[str, Any]:
    """Адаптеры, шлюзы, DNS, прокси, IPv6. Без MAC и имён пользователя."""
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$adapters = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -or $_.IPv6DefaultGateway } | ForEach-Object {
  [PSCustomObject]@{
    alias = $_.InterfaceAlias
    desc  = $_.InterfaceDescription
    ipv4  = @($_.IPv4Address | ForEach-Object { $_.IPAddress })
    ipv6  = @($_.IPv6Address | ForEach-Object { $_.IPAddress })
    gateway4 = $_.IPv4DefaultGateway.NextHop
    gateway6 = $_.IPv6DefaultGateway.NextHop
  }
})
$dns = @(Get-DnsClientServerAddress | Where-Object { $_.ServerAddresses } | ForEach-Object {
  [PSCustomObject]@{ alias = $_.InterfaceAlias; family = $_.AddressFamily; servers = @($_.ServerAddresses) }
})
$proxy = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
[PSCustomObject]@{
  adapters = $adapters
  dns = $dns
  proxyEnable = $proxy.ProxyEnable
  proxyServer = $proxy.ProxyServer
  hostsFile = Test-Path "$env:SystemRoot\System32\drivers\etc\hosts"
} | ConvertTo-Json -Depth 5 -Compress
"""
    data = _ps_json(script)
    if not isinstance(data, dict):
        return {"error": "network info unavailable"}
    # имена адаптеров оставляем: они помогают понять, что за сеть (Wi-Fi/Ethernet)
    return data


def collect_discord() -> dict[str, Any]:
    """Процессы Discord и версия клиента (путь наружу не отдаём)."""
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$items = @(Get-CimInstance Win32_Process -Filter "Name='Discord.exe'" | ForEach-Object {
  $v = ''
  try { $v = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($_.ExecutablePath).FileVersion } catch {}
  [PSCustomObject]@{ pid = $_.ProcessId; version = $v; path = $_.ExecutablePath }
})
$items | ConvertTo-Json -Depth 3 -Compress
"""
    data = _ps_json(script, timeout=15.0)
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    procs = []
    for r in rows:
        path = str(r.get("path") or "")
        procs.append(
            {
                "pid": r.get("pid"),
                "version": str(r.get("version") or ""),
                # путь нужен только чтобы отличить Store/PWA-сборку; имя
                # пользователя из него вычищает redact()
                "path": path,
            }
        )
    return {
        "running": bool(procs),
        "count": len(procs),
        "processes": procs,
        "version": next((p["version"] for p in procs if p["version"]), ""),
    }


def _tail(path: Path, *, lines: int = LOG_TAIL_LINES, limit: int = LOG_TAIL_MAX) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = "\n".join(raw.splitlines()[-lines:])
    return tail[-limit:]


def collect_zapret(context: dict[str, Any]) -> dict[str, Any]:
    """Стратегия, аргументы winws и хвост winws.log."""
    from vpn_launcher.core.zapret import ZAPRET_DIR, build_args

    strategy = str(context.get("dpiStrategy") or "")
    args: list[str] = []
    if strategy:
        try:
            args = build_args(strategy)
        except KeyError:
            args = []
    return {
        "strategy": strategy,
        "running": bool(context.get("dpiRunning")),
        "args": args,
        "logTail": _tail(ZAPRET_DIR / "winws.log", lines=60),
    }


def collect_singbox(context: dict[str, Any]) -> dict[str, Any]:
    root = install_root()
    return {
        "running": bool(context.get("vpnRunning")),
        "logTail": _tail(root / "singbox.log", lines=50),
        "errorTail": _tail(root / "singbox.log.err", lines=50),
    }


def collect_system(context: dict[str, Any]) -> dict[str, Any]:
    elevated = bool(context.get("elevated"))
    return {
        "version": __version__,
        "os": platform.platform(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "elevated": elevated,
        "mode": str(context.get("mode") or ""),
        "appMode": str(context.get("appMode") or ""),
        "vpnRunning": bool(context.get("vpnRunning")),
        "dpiRunning": bool(context.get("dpiRunning")),
    }


# ---- вердикт --------------------------------------------------------------


def _first_error(items: Sequence[dict[str, Any]]) -> str:
    for it in items:
        if it.get("error"):
            return str(it["error"])
    return ""


def build_verdict(data: dict[str, Any]) -> dict[str, Any]:
    """По собранным данным -> {code, title, actions[], severity}.

    Правила намеренно простые и объяснимые: сеть проверяется по слоям
    (DNS -> TCP -> TLS -> HTTP), а жалоба «Discord висит на Starting» может
    быть и клиентской, поэтому последний вердикт - про сам клиент.
    """
    dns = [d for d in data.get("dns", []) if d.get("host") in DISCORD_HOSTS]
    tcp = data.get("tcp", [])
    tls = data.get("tls", [])
    http = data.get("http", [])
    discord = data.get("discord", {})
    zapret = data.get("zapret", {})

    dns_ok = [d for d in dns if d.get("v4") or d.get("v6")]
    tcp_ok = [t for t in tcp if t.get("ok")]
    tls_ok = [t for t in tls if t.get("ok")]
    http_ok = [h for h in http if h.get("status") and not h.get("error")]
    http_fail = [h for h in http if h.get("error")]

    def verdict(code: str, title: str, actions: list[str], severity: str = "warn") -> dict[str, Any]:
        return {"code": code, "title": title, "actions": actions, "severity": severity}

    if dns and not dns_ok:
        return verdict(
            "dns_fail",
            "DNS не возвращает адреса Discord",
            [
                "Включите VPN в лаунчере и повторите диагностику.",
                "Если VPN нет: поставьте DNS 1.1.1.1 и 8.8.8.8 в настройках адаптера.",
                "Выполните ipconfig /flushdns и перезапустите Discord.",
                "Проверьте файл hosts: C:\\Windows\\System32\\drivers\\etc\\hosts.",
            ],
            "err",
        )

    if tcp and not tcp_ok:
        return verdict(
            "ip_block",
            "Адреса Discord есть, но TCP-соединение не открывается: похоже на блокировку по IP",
            [
                "Обход DPI здесь не поможет: нужен VPN (включите его в лаунчере).",
                "Проверьте на мобильном интернете: если там работает - блокировка у провайдера.",
                "Смените DNS на 1.1.1.1/8.8.8.8 и повторите.",
            ],
            "err",
        )

    if tcp_ok and tls and not tls_ok:
        return verdict(
            "tls_block",
            "TCP открывается, но TLS-рукопожатие рвётся: фильтрация SNI/DPI",
            [
                "Включите обход DPI и нажмите ПКМ по ракете (полный автоподбор).",
                "Если не помогло - включите VPN: DPI не лечит блокировку по IP.",
                "Проверьте системные дату и время (неверное время рвёт TLS).",
            ],
            "err",
        )

    blocked_http = [h for h in http_fail if str(h.get("url", "")).startswith("https://discord")]
    if blocked_http and not http_ok:
        return verdict(
            "discord_http_block",
            "Ни один HTTPS-эндпоинт Discord не отвечает, хотя TCP/TLS проходят",
            [
                "Включите VPN: вероятна фильтрация по имени/SNI на уровне провайдера.",
                "Попробуйте другую стратегию обхода DPI (ПКМ по ракете).",
                "Перезапустите Discord после смены стратегии.",
            ],
            "err",
        )

    if not discord.get("running"):
        return verdict(
            "discord_not_running",
            "Сеть до Discord проходит, но клиент Discord не запущен",
            [
                "Запустите Discord и повторите диагностику.",
                "Если Discord не стартует - переустановите его (сборка могла повредиться).",
            ],
            "info",
        )

    if http_fail:
        hosts = ", ".join(str(h.get("url", "")) for h in http_fail[:4])
        return verdict(
            "partial_block",
            "Часть эндпоинтов не отвечает: " + hosts,
            [
                "Включите VPN или смените стратегию обхода DPI.",
                "Если не отвечает только updates.discord.com - клиент может висеть на обновлении: переустановите Discord.",
                "После смены стратегии полностью закройте Discord (включая трей) и запустите снова.",
            ],
            "warn",
        )

    if not zapret.get("running") and not data.get("system", {}).get("vpnRunning"):
        return verdict(
            "network_ok_no_bypass",
            "Сеть до Discord проходит без обхода; если Discord всё равно висит - проблема в клиенте",
            [
                "Полностью закройте Discord (правый клик по иконке в трее -> Выход) и запустите снова.",
                "Выполните ipconfig /flushdns.",
                "Проверьте, что системные дата/время верны.",
                "Если не помогло - переустановите Discord.",
            ],
            "info",
        )

    return verdict(
        "client_side",
        "Сеть до Discord проходит, но клиент не подключается: проблема в самом Discord",
        [
            "Полностью закройте Discord (включая трей) и запустите снова.",
            "Выполните ipconfig /flushdns и перезагрузите ПК.",
            "Проверьте системные дату и время.",
            "Отключите IPv6 на время проверки (иногда клиент зависает на недоступном IPv6).",
            "Если не помогло - переустановите Discord (повреждённый кэш/обновление).",
        ],
        "warn",
    )


# ---- сборка отчёта --------------------------------------------------------


def collect_report(
    context: dict[str, Any] | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    probe_network: bool = True,
) -> dict[str, Any]:
    """Собрать отчёт. Сеть опрашивается последовательно, прогресс - в UI."""
    ctx = dict(context or {})
    report_id = uuid.uuid4().hex[:12]
    created = datetime.now().astimezone().isoformat(timespec="seconds")

    def step(msg: str) -> None:
        if progress is not None:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001 - прогресс не должен ронять сбор
                pass

    step("Сбор сведений о системе...")
    data: dict[str, Any] = {
        "id": report_id,
        "created": created,
        "system": collect_system(ctx),
        "network": {},
        "dns": [],
        "tcp": [],
        "tls": [],
        "http": [],
        "zapret": collect_zapret(ctx),
        "singbox": collect_singbox(ctx),
        "discord": collect_discord() if probe_network else {"running": None, "processes": []},
        "logTail": redact_log(_tail(LOG_FILE)),
    }

    if probe_network:
        step("Сетевые параметры...")
        data["network"] = collect_network()

        hosts = DISCORD_HOSTS + YOUTUBE_HOSTS
        for i, host in enumerate(hosts, 1):
            step(f"DNS {i}/{len(hosts)}: {host}")
            entry = dns_probe(host)
            data["dns"].append(entry)
            for ip in entry.get("v4", [])[:3]:
                step(f"TCP/TLS {host} ({ip})")
                t = tcp_probe(host, ip)
                data["tcp"].append(t)
                if t.get("ok"):
                    data["tls"].append(tls_probe(host, ip))

        for url in HTTP_PROBES:
            step(f"HTTPS: {url}")
            data["http"].append(http_probe(url))

    data["verdict"] = build_verdict(data)
    return _redact_obj(data)


def render_text(data: dict[str, Any]) -> str:
    """Человекочитаемый отчёт: вердикт сверху, детали ниже."""
    v = data.get("verdict", {})
    sysd = data.get("system", {})
    lines: list[str] = [
        "VPN LAUNCHER — ДИАГНОСТИКА",
        "=" * 60,
        f"ID отчёта : {data.get('id', '')}",
        f"Время     : {data.get('created', '')}",
        f"Версия    : {sysd.get('version', '')}",
        "",
        "ВЕРДИКТ",
        "-" * 60,
        str(v.get("title") or "нет данных"),
        "",
        "ЧТО ДЕЛАТЬ:",
    ]
    for i, action in enumerate(v.get("actions") or [], 1):
        lines.append(f"{i}. {action}")
    if not v.get("actions"):
        lines.append("Действий не требуется.")

    lines += ["", "ПРИЛОЖЕНИЕ", "-" * 60]
    for key in (
        "version", "os", "arch", "python", "frozen", "elevated",
        "mode", "appMode", "vpnRunning", "dpiRunning",
    ):
        lines.append(f"{key}: {sysd.get(key)}")

    net = data.get("network") or {}
    if net:
        lines += ["", "СЕТЬ", "-" * 60]
        if net.get("proxyEnable"):
            lines.append(f"Системный прокси: включён ({net.get('proxyServer') or '?'})")
        else:
            lines.append("Системный прокси: выключен")
        for a in net.get("adapters") or []:
            if not isinstance(a, dict):
                continue
            lines.append(
                f"адаптер: {a.get('alias')} | ipv4={a.get('ipv4')} | ipv6={a.get('ipv6')} "
                f"| gw4={a.get('gateway4')} | gw6={a.get('gateway6')}"
            )
        for d in net.get("dns") or []:
            if isinstance(d, dict) and d.get("servers"):
                lines.append(f"DNS {d.get('alias')}: {', '.join(map(str, d['servers']))}")

    lines += ["", "DNS", "-" * 60]
    for d in data.get("dns") or []:
        res = ", ".join(d.get("v4") or []) or "-"
        v6 = ", ".join(d.get("v6") or []) or "-"
        lines.append(
            f"{d.get('host')}: A={res} AAAA={v6} ({d.get('ms')} ms)"
            + (f" ОШИБКА: {d.get('error')}" if d.get("error") else "")
        )

    lines += ["", "TCP 443", "-" * 60]
    for t in data.get("tcp") or []:
        state = "OK" if t.get("ok") else "FAIL"
        lines.append(
            f"{t.get('host')} [{t.get('ip')}]: {state} ({t.get('ms')} ms)"
            + (f" — {t.get('error')}" if t.get("error") else "")
        )

    lines += ["", "TLS", "-" * 60]
    for t in data.get("tls") or []:
        state = "OK" if t.get("ok") else "FAIL"
        lines.append(
            f"{t.get('host')} [{t.get('ip')}]: {state} "
            f"{t.get('version') or ''} {t.get('cipher') or ''} ({t.get('ms')} ms)"
            + (f" — {t.get('error')}" if t.get("error") else "")
        )

    lines += ["", "HTTPS-ПРОБЫ", "-" * 60]
    for h in data.get("http") or []:
        status = h.get("status")
        state = f"HTTP {status}" if status else "FAIL"
        lines.append(
            f"{h.get('url')}: {state} ({h.get('ms')} ms)"
            + (f" — {h.get('error')}" if h.get("error") else "")
        )

    z = data.get("zapret") or {}
    lines += ["", "ОБХОД DPI (winws)", "-" * 60]
    lines.append(f"стратегия: {z.get('strategy') or 'нет'}")
    lines.append(f"запущен: {z.get('running')}")
    if z.get("args"):
        lines.append("аргументы: " + " ".join(str(a) for a in z["args"]))
    if z.get("logTail"):
        lines += ["", "хвост winws.log:", str(z["logTail"])]

    sb = data.get("singbox") or {}
    lines += ["", "SING-BOX", "-" * 60, f"запущен: {sb.get('running')}"]
    if sb.get("logTail"):
        lines += ["", "хвост singbox.log:", str(sb["logTail"])]
    if sb.get("errorTail"):
        lines += ["", "хвост singbox.log.err:", str(sb["errorTail"])]

    dc = data.get("discord") or {}
    lines += ["", "DISCORD", "-" * 60]
    lines.append(f"запущен: {dc.get('running')} | процессов: {dc.get('count')}")
    if dc.get("version"):
        lines.append(f"версия клиента: {dc['version']}")
    for p in dc.get("processes") or []:
        if isinstance(p, dict):
            lines.append(f"pid {p.get('pid')}: {p.get('version') or '?'} ({p.get('path') or '?'})")

    if data.get("logTail"):
        lines += ["", "ХВОСТ ЖУРНАЛА ПРИЛОЖЕНИЯ (vpn-launcher.log)", "-" * 60, str(data["logTail"])]

    lines += [
        "",
        "=" * 60,
        "Отчёт обезличен: имя пользователя, ссылка подписки, токены и IP в",
        "текстовых хвостах заменены. Отправляется только владельцу сборки.",
    ]
    return "\n".join(lines)


# ---- сохранение и отправка ------------------------------------------------


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def save_report(data: dict[str, Any], text: str) -> tuple[Path, Path]:
    """Локальная копия (пользователь всегда может её открыть)."""
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    base = f"diag-{_stamp()}-{data.get('id') or uuid.uuid4().hex[:12]}"
    txt = DIAG_DIR / f"{base}.txt"
    js = DIAG_DIR / f"{base}.json"
    txt.write_text(text, encoding="utf-8", newline="\r\n")
    js.write_text(
        json.dumps({"report": data, "text": text}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return txt, js


def payload_bytes(data: dict[str, Any], text: str) -> bytes:
    """Тело для отправки. Если больше лимита - подрезаем хвосты журналов."""
    def blob() -> bytes:
        return json.dumps(
            {"report": data, "text": text}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    body = blob()
    if len(body) <= MAX_SEND_BYTES:
        return body
    for key in ("logTail",):
        data[key] = str(data.get(key) or "")[:2000]
    for part in ("zapret", "singbox"):
        section = data.get(part)
        if isinstance(section, dict):
            for key in ("logTail", "errorTail"):
                if key in section:
                    section[key] = str(section[key])[:2000]
    text = render_text(data)
    body = blob()
    if len(body) > MAX_SEND_BYTES:
        body = json.dumps(
            {"report": {"id": data.get("id"), "verdict": data.get("verdict")},
             "text": text[:2000]},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
    return body


def send_report(
    data: dict[str, Any],
    text: str,
    endpoint: str,
    *,
    timeout: float = 25.0,
) -> tuple[bool, str]:
    """POST зашифрованного отчёта. -> (успех, короткое пояснение)."""
    if not endpoint:
        return False, "адрес приёма не настроен"
    body = payload_bytes(data, text)
    if len(body) > MAX_SEND_BYTES:
        return False, "отчёт слишком большой"
    try:
        enc = encrypt_report(body)
        req = urllib.request.Request(
            endpoint,
            data=enc,
            method="POST",
            headers={
                "Content-Type": "application/octet-stream",
                "User-Agent": f"VPN-LAUNCHER/{__version__}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            code = int(resp.status)
            if 200 <= code < 300:
                return True, f"отправлен (HTTP {code})"
            return False, f"приёмник ответил HTTP {code}"
    except urllib.error.HTTPError as exc:
        return False, f"приёмник ответил HTTP {exc.code}"
    except BaseException as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def run_diagnostics(
    context: dict[str, Any] | None = None,
    *,
    send: bool = True,
    endpoint: str = "",
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Полный цикл: собрать -> сохранить -> (опционально) отправить.

    Возвращает {'data','text','txt','json','sent','message'} - UI и журнал
    показывают ровно то, что произошло, без «тихих» отправок.
    """
    data = collect_report(context, progress=progress)
    text = render_text(data)
    txt, js = save_report(data, text)
    sent, message = False, ""
    if send and endpoint:
        sent, message = send_report(data, text, endpoint)
    write_log(
        f"diagnostics: report {data.get('id')} saved ({txt.name}); "
        f"verdict={data.get('verdict', {}).get('code')}; send={sent} {message}".strip()
    )
    return {
        "data": data,
        "text": text,
        "txt": str(txt),
        "json": str(js),
        "sent": sent,
        "message": message,
    }
