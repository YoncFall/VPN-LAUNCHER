# -*- coding: utf-8 -*-
"""Защищённый DNS Windows (DoH) для режима обхода DPI.

24.11.2026: у провайдера отравлен UDP-DNS - `youtube.com` отвечает
NXDOMAIN даже через 1.1.1.1, хотя DoH возвращает нормальные адреса.
Обход DPI в этом случае бесполезен: браузер не может получить IP.
Windows 11 умеет DoH сама, если включить AutoUpgrade для DNS-сервера.

Функция идемпотентна и меняет только известные публичные резолверы
(1.1.1.1/8.8.8.8/9.9.9.9 и их вторые адреса). Чужие/локальные DNS не
трогаем: для них неизвестен DoH-шаблон. UDP остаётся запасным путём
(AllowFallbackToUdp), поэтому при блокировке DoH интернет не пропадёт.
"""
from __future__ import annotations

import ctypes
import subprocess

from vpn_launcher.core.log import write_log

_CREATE_NO_WINDOW = 0x08000000

# известные публичные резолверы и их DoH-шаблоны
KNOWN_DOH = {
    "1.1.1.1": "https://cloudflare-dns.com/dns-query",
    "1.0.0.1": "https://cloudflare-dns.com/dns-query",
    "8.8.8.8": "https://dns.google/dns-query",
    "8.8.4.4": "https://dns.google/dns-query",
    "9.9.9.9": "https://dns.quad9.net/dns-query",
    "149.112.112.112": "https://dns.quad9.net/dns-query",
}

_enabled = False


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _ps(script: str, timeout: float = 30) -> str:
    """Выполнить PowerShell без окна; вернуть stdout (ошибки - пусто)."""
    try:
        res = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception as exc:
        write_log(f"dns: powershell error: {exc}")
        return ""
    if res.returncode != 0:
        err = (res.stderr or "").strip().splitlines()
        if err:
            write_log(f"dns: powershell: {err[-1][:200]}")
        return ""
    return (res.stdout or "").strip()


def dns_servers() -> list[str]:
    """IPv4-адреса DNS текущих адаптеров (без дублей)."""
    out = _ps(
        "(Get-DnsClientServerAddress -AddressFamily IPv4 | "
        "Where-Object { $_.ServerAddresses } | "
        "ForEach-Object { $_.ServerAddresses }) -join ','"
    )
    servers: list[str] = []
    for item in out.split(","):
        ip = item.strip()
        if ip and ip not in servers:
            servers.append(ip)
    return servers


def _enable_script(targets: dict[str, str]) -> str:
    """Один вызов PowerShell: настроить DoH и вернуть «ok=<сколько>».

    Ошибка на отдельном сервере не срывает остальные; если не удалось
    ничего - «ok=0» (например, Windows 10 без DoH-командлета).
    """
    pairs = "; ".join(
        "@{ ip = '%s'; tpl = '%s' }" % (ip, tpl) for ip, tpl in targets.items()
    )
    return (
        "$ErrorActionPreference = 'Stop'; "
        f"$targets = @({pairs}); "
        "$ok = 0; "
        "foreach ($t in $targets) { "
        "try { "
        "Set-DnsClientDohServerAddress -ServerAddress $t.ip -AutoUpgrade $true "
        "-AllowFallbackToUdp $true -DohTemplate $t.tpl -ErrorAction Stop; "
        "$ok++ "
        "} catch { "
        "try { "
        "Add-DnsClientDohServerAddress -ServerAddress $t.ip "
        "-AutoUpgrade $true -AllowFallbackToUdp $true "
        "-DohTemplate $t.tpl -ErrorAction Stop; "
        "$ok++ "
        "} catch { } "
        "} "
        "} "
        "if ($ok -gt 0) { "
        "try { "
        "New-Item -Path "
        "'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Dnscache\\Parameters' "
        "-Force | Out-Null; "
        "Set-ItemProperty -Path "
        "'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Dnscache\\Parameters' "
        "-Name EnableAutoDoh -Value 2 -Type DWord -ErrorAction Stop; "
        "Clear-DnsClientCache "
        "} catch { } "
        "} "
        "'ok=' + $ok"
    )


def ensure_windows_doh() -> bool:
    """Включить AutoUpgrade DoH для известных DNS-серверов.

    Возвращает True, если хотя бы один сервер настроен (или уже был).
    Требует прав администратора; без них тихо возвращает False.
    """
    global _enabled
    if _enabled:
        return True
    if not is_admin():
        write_log("dns: DoH не включён - нет прав администратора")
        return False
    servers = dns_servers()
    targets = {ip: KNOWN_DOH[ip] for ip in servers if ip in KNOWN_DOH}
    if not targets:
        write_log(f"dns: DoH пропущен - DNS {servers or 'не найден'} не из известных")
        return False
    out = _ps(_enable_script(targets))
    configured = 0
    marker = out.rfind("ok=")
    if marker >= 0:
        digits = out[marker + 3:].strip().split()[0] if out[marker + 3:].strip() else ""
        try:
            configured = int(digits)
        except ValueError:
            configured = 0
    _enabled = configured > 0
    if _enabled:
        write_log(
            f"dns: Windows DoH включён ({configured}) для "
            + ", ".join(targets)
        )
    else:
        write_log("dns: Windows DoH недоступен (нужна Windows 11)")
    return _enabled
