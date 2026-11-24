# -*- coding: utf-8 -*-
"""DoH-фикс для отравленного DNS (2.4.10, 24.11.2026).

PowerShell не запускаем: _ps/is_admin/dns_servers подменяются заглушками.
"""
from __future__ import annotations

import pytest

from vpn_launcher.core import dnsfix as d


@pytest.fixture(autouse=True)
def _reset():
    d._enabled = False
    yield
    d._enabled = False


def test_without_admin_does_nothing(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(d, "is_admin", lambda: False)
    monkeypatch.setattr(d, "_ps", lambda script, timeout=0: calls.append(script) or "")
    assert d.ensure_windows_doh() is False
    assert calls == []


def test_unknown_dns_is_not_touched(monkeypatch):
    calls: list[str] = []

    def fake_ps(script, timeout=0):
        calls.append(script)
        return "192.168.1.1,10.0.0.1"

    monkeypatch.setattr(d, "is_admin", lambda: True)
    monkeypatch.setattr(d, "_ps", fake_ps)
    assert d.ensure_windows_doh() is False
    assert len(calls) == 1  # только опрос адаптеров, настройки не было


def test_known_dns_gets_doh(monkeypatch):
    calls: list[str] = []

    def fake_ps(script, timeout=0):
        calls.append(script)
        if "Get-DnsClientServerAddress" in script:
            return "1.1.1.1,192.168.1.1,1.0.0.1"
        return "ok=2"

    monkeypatch.setattr(d, "is_admin", lambda: True)
    monkeypatch.setattr(d, "_ps", fake_ps)
    assert d.ensure_windows_doh() is True
    assert len(calls) == 2
    enable = calls[1]
    assert "1.1.1.1" in enable and "1.0.0.1" in enable
    assert "192.168.1.1" not in enable  # локальный DNS не трогаем
    assert "https://cloudflare-dns.com/dns-query" in enable
    assert "EnableAutoDoh" in enable
    # повторный вызов - из кэша, PowerShell больше не дёргаем
    assert d.ensure_windows_doh() is True
    assert len(calls) == 2


def test_old_windows_reports_false_and_retries(monkeypatch):
    calls: list[str] = []

    def fake_ps(script, timeout=0):
        calls.append(script)
        if "Get-DnsClientServerAddress" in script:
            return "8.8.8.8"
        return "ok=0"

    monkeypatch.setattr(d, "is_admin", lambda: True)
    monkeypatch.setattr(d, "_ps", fake_ps)
    assert d.ensure_windows_doh() is False
    # неудача не кэшируется: следующий запуск попробует снова
    assert d.ensure_windows_doh() is False
    assert len(calls) == 4


def test_enable_script_targets_each_server():
    script = d._enable_script({
        "1.1.1.1": "https://cloudflare-dns.com/dns-query",
        "8.8.8.8": "https://dns.google/dns-query",
    })
    assert "@{ ip = '1.1.1.1'; tpl = 'https://cloudflare-dns.com/dns-query' }" in script
    assert "@{ ip = '8.8.8.8'; tpl = 'https://dns.google/dns-query' }" in script
    assert "Set-DnsClientDohServerAddress" in script
    # если записи о резолвере нет (например, её удалили), создаём её
    assert "Add-DnsClientDohServerAddress" in script
    assert "-AllowFallbackToUdp $true" in script
