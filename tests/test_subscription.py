# -*- coding: utf-8 -*-
"""Тесты подписок: Parse-NodeList + Get-SubscriptionNodes (core.ps1:392-450)."""
from __future__ import annotations

from pathlib import Path

import pytest

from vpn_launcher.core import subscription
from vpn_launcher.core.subscription import (
    USER_AGENT,
    SubscriptionError,
    fetch_nodes,
    parse_node_list,
)

FIXTURES = Path(__file__).parent / "fixtures"
PLAIN = FIXTURES / "subscription.txt"
B64 = FIXTURES / "subscription-b64.txt"

_NOLOG = lambda m: None  # noqa: E731 - тесты не пишут в журнал


def _plain() -> str:
    return PLAIN.read_text(encoding="utf-8")


class _FakeResp:
    def __init__(self, data: bytes, final_url: str | None = None):
        self._data = data
        self._final_url = final_url

    def read(self) -> bytes:
        return self._data

    def geturl(self) -> str | None:
        """Финальный URL после редиректов (как у urllib.request.HTTPResponse)."""
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class TestParseNodeList:
    def test_plain_fixture_counts_and_tags(self):
        logs: list[str] = []
        nodes = parse_node_list(_plain(), logger=logs.append)
        assert len(nodes) == 16
        assert [n["tag"] for n in nodes] == [f"node-{i}" for i in range(1, 17)]
        assert "  parsed 16 of 20 lines" in logs  # 4 строки с '://' дают None

    def test_b64_fixture_equals_plain(self):
        b64_nodes = parse_node_list(B64.read_text(encoding="utf-8"), logger=_NOLOG)
        assert b64_nodes == parse_node_list(_plain(), logger=_NOLOG)

    def test_display_fragment_and_fallback(self):
        nodes = parse_node_list(_plain(), logger=_NOLOG)
        by_tag = {n["tag"]: n for n in nodes}
        # фрагмент percent-decode'ится (core.ps1 Split-Uri)
        assert by_tag["node-3"]["display"] == "Сервер VLESS"
        # у vmess фрагмента нет -> server:port
        assert by_tag["node-5"]["display"] == "vmess-ws.example.com:443"
        # у валидных нод proto == type (Parse-NodeList:443)
        assert all(n["proto"] == n["type"] for n in nodes)

    def test_vmess_quirks_preserved_from_106(self):
        nodes = parse_node_list(_plain(), logger=_NOLOG)
        by_tag = {n["tag"]: n for n in nodes}
        # type=none из JSON перебивает net -> transport потерян
        assert "transport" not in by_tag["node-5"]
        # vmess+tls: tls есть, transport потерян ($q пересобирается в PS)
        assert by_tag["node-6"]["tls"]["enabled"] is True
        assert "transport" not in by_tag["node-6"]
        # только vmess без поля type реально получает ws-transport
        assert by_tag["node-7"]["transport"]["type"] == "ws"

    def test_empty_body_raises(self):
        with pytest.raises(SubscriptionError, match="Пустой текст подписки"):
            parse_node_list("", logger=_NOLOG)

    def test_no_recognizable_nodes_raises(self):
        for body in ("просто текст без схем", "vless://missing-at-sign", "://only-separator"):
            with pytest.raises(SubscriptionError, match="Не удалось распознать"):
                parse_node_list(body, logger=_NOLOG)


class TestFetchLocal:
    def test_plain_path(self):
        logs: list[str] = []
        nodes = fetch_nodes(str(PLAIN), logger=logs.append)
        assert len(nodes) == 16
        assert logs[0].startswith("fetching subscription from local file: ")

    def test_path_in_quotes(self):
        assert len(fetch_nodes(f'"{PLAIN}"', logger=_NOLOG)) == 16

    def test_file_url(self):
        url = "file://" + str(PLAIN)
        assert len(fetch_nodes(url, logger=_NOLOG)) == 16

    def test_missing_path_raises(self):
        with pytest.raises(SubscriptionError, match="http\\(s\\)-ссылка"):
            fetch_nodes(r"C:\no\such\subscription.txt", logger=_NOLOG)

    def test_empty_url_raises(self):
        with pytest.raises(SubscriptionError, match="Пустая ссылка"):
            fetch_nodes("", logger=_NOLOG)


class TestHttpOnly:
    """Отклонение от 1.0.6: внешний http:// больше не качаем.

    Токен подписки в query/path при http едет по сети в открытом виде;
    http остаётся только для локальной сети и file-путей.
    """

    def _patch_dns(self, monkeypatch, ip: str) -> None:
        monkeypatch.setattr(
            subscription.socket,
            "getaddrinfo",
            lambda host, port=None: [(2, 1, 6, "", (ip, 0))],
        )

    def test_url_policy(self):
        assert subscription._remote_url_allowed("https://any.host/x")
        assert subscription._remote_url_allowed("http://127.0.0.1/x")
        assert subscription._remote_url_allowed("http://10.0.0.1/x")
        assert subscription._remote_url_allowed("http://[::1]/x")
        assert not subscription._remote_url_allowed("http://any.host/x")
        assert not subscription._remote_url_allowed("ftp://any.host/x")
        assert not subscription._remote_url_allowed("")

    def test_http_public_hostname_rejected(self, monkeypatch):
        self._patch_dns(monkeypatch, "93.184.216.34")
        with pytest.raises(SubscriptionError, match="открытом виде"):
            fetch_nodes("http://sub.example/list", logger=_NOLOG)

    def test_http_public_ip_literal_rejected(self):
        # литерал IP - DNS вообще не нужен
        with pytest.raises(SubscriptionError, match="открытом виде"):
            fetch_nodes("http://93.184.216.34/list", logger=_NOLOG)

    def test_http_private_literal_allowed(self, monkeypatch):
        seen: dict = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            return _FakeResp(_plain().encode("utf-8"))

        monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)
        nodes = fetch_nodes("http://10.1.2.3/list", logger=_NOLOG)
        assert len(nodes) == 16
        assert seen["url"] == "http://10.1.2.3/list"

    def test_http_name_resolving_to_private_allowed(self, monkeypatch):
        self._patch_dns(monkeypatch, "10.1.2.3")
        monkeypatch.setattr(
            subscription.urllib.request,
            "urlopen",
            lambda req, timeout=None: _FakeResp(_plain().encode("utf-8")),
        )
        assert len(fetch_nodes("http://nas.local/list", logger=_NOLOG)) == 16

    def test_redirect_to_http_rejected_with_body_discarded(self, monkeypatch):
        seen: dict = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            # сервер 302 на http - тело подделать уже могли, не принимаем
            return _FakeResp(_plain().encode("utf-8"), final_url="http://evil.example/x")

        monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(SubscriptionError, match="небезопасный адрес"):
            fetch_nodes("https://sub.example/list", logger=_NOLOG)
        assert seen["url"] == "https://sub.example/list"


class TestFetchHttp:
    def _patch(self, monkeypatch, data: bytes, seen: dict):
        def fake_urlopen(req, timeout=None):
            # ключи заголовков в Request хранятся с неизвестным регистром -
            # ищем case-insensitively
            seen["ua"] = next(
                (v for k, v in req.headers.items() if k.lower() == "user-agent"), None
            )
            seen["timeout"] = timeout
            return _FakeResp(data)

        monkeypatch.setattr(subscription.urllib.request, "urlopen", fake_urlopen)

    def test_user_agent_timeout_and_parse(self, monkeypatch):
        seen: dict = {}
        self._patch(monkeypatch, _plain().encode("utf-8"), seen)
        logs: list[str] = []
        nodes = fetch_nodes("https://sub.example/list", logger=logs.append)
        assert seen["ua"] == USER_AGENT == "sing-box/1.14.2"
        assert seen["timeout"] == subscription.HTTP_TIMEOUT_S
        assert len(nodes) == 16
        assert "fetching subscription from host: sub.example" in logs

    def test_empty_response_raises(self, monkeypatch):
        seen: dict = {}
        self._patch(monkeypatch, b"", seen)
        with pytest.raises(SubscriptionError, match="Пустой ответ сервера"):
            fetch_nodes("https://sub.example/list", logger=_NOLOG)

    def test_utf8_preferred_over_ansi(self, monkeypatch):
        # осознанное отклонение от 1.0.6 (см. докстринг): сначала UTF-8
        seen: dict = {}
        body = "vless://uuid@h.example:443#Сервер".encode("utf-8")
        self._patch(monkeypatch, body, seen)
        nodes = fetch_nodes("https://sub.example/list", logger=_NOLOG)
        assert nodes[0]["display"] == "Сервер"

    def test_ansi_fallback_for_legacy_encoding(self, monkeypatch):
        # то, что 1.0.6 делало всегда: тело в ANSI (cp1251 на RU-системе)
        seen: dict = {}
        monkeypatch.setattr(
            subscription.locale, "getpreferredencoding", lambda eff=False: "cp1251"
        )
        body = "vless://uuid@h.example:443#Сервер".encode("cp1251")
        self._patch(monkeypatch, body, seen)
        nodes = fetch_nodes("https://sub.example/list", logger=_NOLOG)
        assert nodes[0]["display"] == "Сервер"
