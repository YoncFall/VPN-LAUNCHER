# -*- coding: utf-8 -*-
"""Диагностика Discord/YouTube (2.4.6): обезличивание, шифрование, вердикты.

Сеть и PowerShell в тестах не трогаем: collect_report идёт с
probe_network=False, send_report/resolve_endpoint кормятся заглушками.
"""
from __future__ import annotations

import base64
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vpn_launcher.core import diagnostics as d  # noqa: E402
from vpn_launcher.core.diag_key import DIAG_PUBLIC_KEY  # noqa: E402


# ---- обезличивание ---------------------------------------------------------
def test_redact_strips_subscription_and_tokens():
    s = d.redact(
        r"user C:\Users\oksana\sub vless://abc@1.2.3.4:443?token=SECRET "
        "uuid 550e8400-e29b-41d4-a716-446655440000 mail a@b.cc "
        "discord-token MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0.NjU0MzIx.z7x8y9..."
    )
    assert "oksana" not in s
    assert "<subscription-link>" in s
    assert "<uuid>" in s
    assert "<email>" in s
    assert "<token>" in s


def test_redact_log_hides_ip_and_mac():
    s = d.redact_log("ip 192.168.0.1 mac 00:11:22:33:44:55")
    assert "192.168.0.1" not in s
    assert "<ip>" in s
    assert "<mac>" in s


def test_redact_obj_walks_nested():
    obj = {"a": "vless://x@y", "b": ["z@q.ru"], "c": {"d": "550e8400-e29b-41d4-a716-446655440000"}}
    out = d._redact_obj(obj)
    assert "<subscription-link>" in out["a"]
    assert "<email>" in out["b"][0]
    assert "<uuid>" in out["c"]["d"]


# ---- шифрование ------------------------------------------------------------
def test_encrypt_decrypt_roundtrip():
    body = "секретный отчёт".encode("utf-8")
    priv, pub = _keypair()
    blob = d.encrypt_report(body, pub)
    assert blob.startswith(d.MAGIC)
    assert d.decrypt_report(blob, priv) == body


def test_decrypt_rejects_wrong_key():
    priv_a, pub_a = _keypair()
    _priv_b, _pub_b = _keypair()
    blob = d.encrypt_report(b"x" * 10, pub_a)
    try:
        d.decrypt_report(blob, _priv_b)
        assert False, "wrong key must fail"
    except Exception:
        pass


def test_decrypt_rejects_garbage():
    for bad in (b"", b"VLDR", b"VLDR1" + b"\x00" * 10):
        try:
            d.decrypt_report(bad, "AAAA")
            assert False, "garbage must fail"
        except Exception:
            pass


def test_encrypt_rejects_bad_public_key():
    try:
        d.encrypt_report(b"x", "not-base64!!")
        assert False
    except Exception:
        pass


def test_embedded_public_key_is_32_bytes():
    assert len(base64.b64decode(DIAG_PUBLIC_KEY)) == 32


def _keypair():
    """Пара ключей для тестов (эфемерная, не зашитый ключ)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    priv = X25519PrivateKey.generate()
    priv_b64 = base64.b64encode(
        priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode()
    pub_b64 = base64.b64encode(
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode()
    return priv_b64, pub_b64


# ---- вердикты --------------------------------------------------------------
def _net(dns=(), tcp=(), tls=(), http=()):
    return {"dns": list(dns), "tcp": list(tcp), "tls": list(tls), "http": list(http)}


def test_verdict_dns_fail():
    v = d.build_verdict(_net(dns=[{"host": "discord.com", "v4": [], "v6": []}]))
    assert v["code"] == "dns_fail"
    assert v["severity"] == "err"


def test_verdict_ip_block():
    v = d.build_verdict(_net(
        dns=[{"host": "discord.com", "v4": ["1.2.3.4"]}],
        tcp=[{"host": "discord.com", "ok": False, "error": "timeout"}],
    ))
    assert v["code"] == "ip_block"


def test_verdict_tls_block():
    v = d.build_verdict(_net(
        dns=[{"host": "discord.com", "v4": ["1.2.3.4"]}],
        tcp=[{"host": "discord.com", "ok": True}],
        tls=[{"host": "discord.com", "ok": False, "error": "reset"}],
    ))
    assert v["code"] == "tls_block"


def test_verdict_discord_http_block():
    v = d.build_verdict(_net(
        dns=[{"host": "discord.com", "v4": ["1.2.3.4"]}],
        tcp=[{"host": "discord.com", "ok": True}],
        tls=[{"host": "discord.com", "ok": True}],
        http=[{"url": "https://discord.com/api/v9/gateway", "error": "timeout"}],
    ))
    assert v["code"] == "discord_http_block"


def test_verdict_discord_not_running_when_network_ok():
    v = d.build_verdict(_net(
        dns=[{"host": "discord.com", "v4": ["1.2.3.4"]}],
        tcp=[{"host": "discord.com", "ok": True}],
        tls=[{"host": "discord.com", "ok": True}],
        http=[{"url": "https://discord.com/api/v9/gateway", "status": 200}],
    ))
    assert v["code"] == "discord_not_running"


def test_verdict_network_ok_no_bypass_when_discord_runs():
    base = _net(
        dns=[{"host": "discord.com", "v4": ["1.2.3.4"]}],
        tcp=[{"host": "discord.com", "ok": True}],
        tls=[{"host": "discord.com", "ok": True}],
        http=[{"url": "https://discord.com/api/v9/gateway", "status": 200}],
    )
    base["discord"] = {"running": True, "processes": []}
    base["zapret"] = {"running": False}
    base["system"] = {"vpnRunning": False}
    v = d.build_verdict(base)
    assert v["code"] == "network_ok_no_bypass"


def test_verdict_client_side_when_bypass_on():
    base = _net(
        dns=[{"host": "discord.com", "v4": ["1.2.3.4"]}],
        tcp=[{"host": "discord.com", "ok": True}],
        tls=[{"host": "discord.com", "ok": True}],
        http=[{"url": "https://discord.com/api/v9/gateway", "status": 200}],
    )
    base["discord"] = {"running": True, "processes": []}
    base["zapret"] = {"running": True}
    base["system"] = {"vpnRunning": False}
    v = d.build_verdict(base)
    assert v["code"] == "client_side"


# ---- сборка отчёта (без сети и PowerShell) ---------------------------------
def test_collect_report_offline_shape():
    data = d.collect_report(
        {"mode": "tun", "appMode": "include", "dpiStrategy": "", "vpnRunning": False},
        probe_network=False,
    )
    assert set(("id", "created", "system", "zapret", "singbox", "discord", "verdict")) <= set(data)
    assert data["discord"] == {"running": None, "processes": []}
    assert "verdict" in data


def test_collect_report_never_leaks_subscription():
    data = d.collect_report(
        {"mode": "tun", "subUrl": "vless://SECRET@x", "appMode": "include"},
        probe_network=False,
    )
    text = d.render_text(data)
    assert "SECRET" not in text
    assert "vless://" not in text


# ---- отправка --------------------------------------------------------------
def test_send_report_no_endpoint():
    ok, msg = d.send_report({}, "", "")
    assert not ok
    assert "настроен" in msg


class _FakeResp:
    def __init__(self, code=204):
        self.status = code

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_send_report_posts_encrypted(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["body"] = req.data
        seen["ctype"] = req.headers.get("Content-type")
        return _FakeResp(204)

    monkeypatch.setattr(d.urllib.request, "urlopen", fake_urlopen)
    ok, msg = d.send_report({"id": "abc123", "verdict": {"code": "x"}}, "text", "https://e/report")
    assert ok
    assert seen["body"].startswith(d.MAGIC)  # тело уходит зашифрованным
    assert seen["ctype"] == "application/octet-stream"


# ---- endpoint ---------------------------------------------------------------
def test_resolve_endpoint_https_only(monkeypatch):
    from vpn_launcher.core import diag_endpoint as de

    class _Resp:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(req, timeout=0):
        return _Resp(json.dumps(
            {"categories": [{"apps": [{"slug": "vpn-launcher", "diagnosticsUrl": "http://insecure/x"}]}]}
        ).encode())

    monkeypatch.setattr(de.urllib.request, "urlopen", fake_urlopen)
    de._cache.clear()
    assert de.resolve_endpoint() == ""  # http-адрес отклонён


def test_resolve_endpoint_accepts_https(monkeypatch):
    from vpn_launcher.core import diag_endpoint as de

    class _Resp:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(req, timeout=0):
        return _Resp(json.dumps(
            {"categories": [{"apps": [{"slug": "vpn-launcher", "diagnosticsUrl": "https://m.ts.net/report"}]}]}
        ).encode())

    monkeypatch.setattr(de.urllib.request, "urlopen", fake_urlopen)
    de._cache.clear()
    assert de.resolve_endpoint() == "https://m.ts.net/report"
