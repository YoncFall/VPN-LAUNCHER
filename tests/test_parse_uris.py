# -*- coding: utf-8 -*-
"""Тесты парсеров протоколов (порта core.ps1:35-388)."""
import base64
import json

from vpn_launcher.core.uris import (
    b64_utf8_decode,
    b64_utf8_encode,
    new_tls_block,
    new_transport_block,
    parse_proxy_uri,
)

_NOLOG = lambda m: None  # noqa: E731 - тесты не пишут в журнал


def _parse(uri: str, index: int = 1, logger=_NOLOG):
    return parse_proxy_uri(uri, index, logger=logger)


def _vmess_uri(**over) -> str:
    j = {"v": "2", "ps": "n", "add": "h.example", "port": "443", "id": "uuid-1", "aid": "0"}
    j.update(over)
    return "vmess://" + b64_utf8_encode(json.dumps(j))


class TestB64:
    def test_encode_known(self):
        assert b64_utf8_encode("abc") == "YWJj"

    def test_roundtrip_cyrillic(self):
        assert b64_utf8_decode(b64_utf8_encode("Сервер 1")) == "Сервер 1"

    def test_unpadded_rem2_and_rem3(self):
        assert b64_utf8_decode("YQ") == "a"        # 'YQ==' без паддинга
        assert b64_utf8_decode("YWI") == "ab"      # 'YWI=' без паддинга

    def test_rem1_returns_empty(self):
        assert b64_utf8_decode("Y") == ""

    def test_url_safe_chars(self):
        enc = base64.urlsafe_b64encode("Привет".encode()).decode()
        assert b64_utf8_decode(enc) == "Привет"

    def test_whitespace_stripped(self):
        assert b64_utf8_decode("Y\r\nWJ j") == "abc"

    def test_invalid_base64_returns_empty(self):
        assert b64_utf8_decode("не-base64!") == ""
        assert b64_utf8_decode("") == ""

    def test_invalid_utf8_becomes_replacement(self):
        # как Encoding.UTF8.GetString в .NET - битые байты не роняют парсер
        assert b64_utf8_decode(base64.b64encode(b"\xff").decode()) == "�"


class TestTlsBlock:
    def test_disabled_without_security(self):
        assert new_tls_block({}, "s.example", False) is None
        assert new_tls_block({"security": "none"}, "s.example", False) is None

    def test_tls_by_default(self):
        assert new_tls_block({}, "s.example", True) == {
            "enabled": True, "server_name": "s.example",
        }

    def test_tls_with_all_options(self):
        q = {
            "security": "tls", "sni": "sni.example", "fp": "chrome",
            "alpn": "h2,h3", "allowInsecure": "1",
        }
        assert new_tls_block(q, "def", False) == {
            "enabled": True,
            "server_name": "sni.example",
            "insecure": True,
            "utls": {"enabled": True, "fingerprint": "chrome"},
            "alpn": ["h2", "h3"],
        }

    def test_sni_fallback_chain(self):
        # sni -> peer -> host -> defaultSni
        assert new_tls_block({"security": "tls", "peer": "p.example"}, "d", False)["server_name"] == "p.example"
        assert new_tls_block({"security": "tls", "host": "h.example"}, "d", False)["server_name"] == "h.example"
        assert new_tls_block({"security": "tls"}, "d", False)["server_name"] == "d"

    def test_reality_block(self):
        q = {"security": "REALITY", "pbk": "PBK", "sid": "SID", "sni": "r.example"}
        assert new_tls_block(q, "d", False)["reality"] == {
            "enabled": True, "public_key": "PBK", "short_id": "SID",
        }

    def test_reality_without_sni_assigns_host_lookup_unconditionally(self):
        # PS: sni/peer/host и default пусты -> server_name перезаписывается
        # пустой строкой (присваивание в ветке reality безусловное)
        assert new_tls_block({"security": "reality"}, "", False)["server_name"] == ""


class TestTransportBlock:
    def test_ws_with_path_and_host(self):
        q = {"type": "ws", "path": "/p", "host": "h.example"}
        assert new_transport_block(q, "def") == {
            "type": "ws", "path": "/p", "headers": {"Host": "h.example"},
        }

    def test_websocket_alias(self):
        assert new_transport_block({"net": "websocket"}, "d")["type"] == "ws"

    def test_ws_without_host_uses_default_and_skips_headers(self):
        assert new_transport_block({"type": "ws"}, "") == {"type": "ws"}

    def test_grpc(self):
        assert new_transport_block({"type": "grpc", "serviceName": "s"}, "d") == {
            "type": "grpc", "service_name": "s",
        }
        assert new_transport_block({"type": "grpc"}, "d") == {"type": "grpc"}

    def test_h2(self):
        assert new_transport_block({"type": "h2", "host": "a,b", "path": "/x"}, "d") == {
            "type": "http", "host": ["a", "b"], "path": "/x",
        }

    def test_http_needs_header_type(self):
        q = {"type": "http", "headerType": "http", "path": "/1,/2", "host": "a"}
        assert new_transport_block(q, "d") == {
            "type": "http", "path": ["/1", "/2"], "host": ["a"],
        }
        assert new_transport_block({"type": "http"}, "d") is None

    def test_httpupgrade_keeps_host_key_always(self):
        assert new_transport_block({"type": "httpupgrade", "path": "/u"}, "d.example") == {
            "type": "httpupgrade", "host": "d.example", "path": "/u",
        }

    def test_quic(self):
        assert new_transport_block({"type": "quic"}, "d") == {"type": "quic"}

    def test_tcp_and_unknown_give_none(self):
        assert new_transport_block({}, "d") is None
        assert new_transport_block({"type": "kcp"}, "d") is None


class TestParseVless:
    def test_minimal(self):
        assert _parse("vless://uuid-1@h.example:8443#n") == {
            "type": "vless", "tag": "node-1",
            "server": "h.example", "server_port": 8443, "uuid": "uuid-1",
        }

    def test_index_sets_tag(self):
        assert _parse("vless://uuid-1@h.example:443", 5)["tag"] == "node-5"

    def test_flow_tls_transport(self):
        uri = (
            "vless://uuid-1@h.example:443?security=tls&sni=s.example&fp=chrome"
            "&type=ws&path=%2Fws&host=cdn.example#n"
        )
        ob = _parse(uri)
        assert "flow" not in ob  # пустой/отсутствующий flow не добавляется
        assert ob["tls"] == {
            "enabled": True, "server_name": "s.example",
            "utls": {"enabled": True, "fingerprint": "chrome"},
        }
        assert ob["transport"] == {
            "type": "ws", "path": "/ws", "headers": {"Host": "cdn.example"},
        }

    def test_flow_present(self):
        ob = _parse("vless://u@h:443?flow=xtls-rprx-vision#n")
        assert ob["flow"] == "xtls-rprx-vision"

    def test_no_at_sign_returns_none(self):
        assert _parse("vless://missing-at-sign#n") is None


class TestParseVmess:
    def test_ws_transport_without_tls(self):
        ob = _parse(_vmess_uri(net="ws", path="/w", host="cdn.example"))
        assert ob["server"] == "h.example"
        assert ob["server_port"] == 443
        assert ob["alter_id"] == 0
        assert ob["transport"] == {
            "type": "ws", "path": "/w", "headers": {"Host": "cdn.example"},
        }
        assert "tls" not in ob

    def test_type_header_field_beats_net_transport_lost(self):
        # баг 1.0.6: 'type' из JSON (заголовок) идёт в Get-QueryVal раньше 'net'
        ob = _parse(_vmess_uri(net="ws", type="none", path="/w"))
        assert "transport" not in ob

    def test_tls_field_drops_transport(self):
        # баг 1.0.6: при tls $q пересобирается без net/type/host/path
        ob = _parse(_vmess_uri(net="ws", tls="tls", sni="sni.example", path="/w"))
        assert ob["tls"] == {"enabled": True, "server_name": "sni.example"}
        assert "transport" not in ob

    def test_tls_without_sni_defaults_to_server(self):
        ob = _parse(_vmess_uri(tls="tls"))
        assert ob["tls"]["server_name"] == "h.example"

    def test_alter_id_positive(self):
        assert _parse(_vmess_uri(aid="4"))["alter_id"] == 4
        assert _parse(_vmess_uri(aid="0"))["alter_id"] == 0

    def test_address_fallback(self):
        ob = _parse(_vmess_uri(add="", address="addr.example"))
        assert ob["server"] == "addr.example"

    def test_missing_server_returns_none(self):
        assert _parse(_vmess_uri(add="", address="")) is None

    def test_not_json_returns_none_without_log(self):
        logs = []
        assert _parse("vmess://" + b64_utf8_encode("plain text"), logger=logs.append) is None
        assert logs == []

    def test_broken_json_logs_parse_error(self):
        logs = []
        uri = "vmess://" + b64_utf8_encode('{"a":')
        assert _parse(uri, logger=logs.append) is None
        assert len(logs) == 1
        assert logs[0].startswith("parse error [vmess]")


class TestParseTrojan:
    def test_tls_on_by_default(self):
        assert _parse("trojan://pw@t.example:443#n") == {
            "type": "trojan", "tag": "node-1",
            "server": "t.example", "server_port": 443, "password": "pw",
            "tls": {"enabled": True, "server_name": "t.example"},
        }

    def test_transport_with_tls(self):
        ob = _parse("trojan://pw@t.example:443?security=tls&type=ws&path=%2Ft#n")
        assert ob["tls"]["enabled"] is True
        assert ob["transport"] == {
            "type": "ws", "path": "/t", "headers": {"Host": "t.example"},
        }

    def test_no_at_sign_returns_none(self):
        assert _parse("trojan://no-at-sign") is None


class TestParseShadowsocks:
    def test_userinfo_base64(self):
        uri = "ss://" + b64_utf8_encode("aes-256-gcm:pw") + "@h.example:8388#n"
        assert _parse(uri) == {
            "type": "shadowsocks", "tag": "node-1",
            "server": "h.example", "server_port": 8388,
            "method": "aes-256-gcm", "password": "pw",
        }

    def test_whole_body_base64(self):
        uri = "ss://" + b64_utf8_encode("aes-128-gcm:pw@sh.example:8389") + "#n"
        ob = _parse(uri)
        assert ob["server"] == "sh.example"
        assert ob["method"] == "aes-128-gcm"

    def test_raw_userinfo_fallback(self):
        uri = "ss://aes-128-gcm:pw@raw.example:8390#n"
        assert _parse(uri)["password"] == "pw"

    def test_no_colon_returns_none(self):
        assert _parse("ss://" + b64_utf8_encode("nocolon")) is None
        # тело без '@' (декодируется, но адреса нет)
        assert _parse("ss://" + b64_utf8_encode("aes-128-gcm:pw")) is None

    def test_plugin_obfs_local(self):
        uri = "ss://" + b64_utf8_encode("aes-256-gcm:pw") + \
            "@h:8388?plugin=obfs-local&plugin-opts=example.com#n"
        ob = _parse(uri)
        assert ob["plugin"] == "obfs-local"
        assert ob["plugin_opts"] == "obfs=http;obfs-host=example.com"

    def test_plugin_v2ray(self):
        uri = "ss://" + b64_utf8_encode("aes-256-gcm:pw") + \
            "@h:8388?plugin=v2ray-plugin;mode=websocket#n"
        ob = _parse(uri)
        assert ob["plugin"] == "v2ray-plugin"
        assert ob["plugin_opts"] == "mode=websocket"

    def test_password_may_contain_colon(self):
        uri = "ss://" + b64_utf8_encode("aes-256-gcm:pa:ss") + "@h:8388#n"
        assert _parse(uri)["password"] == "pa:ss"


class TestParseHysteria2:
    def test_full(self):
        uri = (
            "hysteria2://pw@h.example:8443?sni=sni.example&insecure=yes"
            "&alpn=h3&obfs=salamander&obfs-password=ob1#n"
        )
        assert _parse(uri) == {
            "type": "hysteria2", "tag": "node-1",
            "server": "h.example", "server_port": 8443, "password": "pw",
            "tls": {"enabled": True, "server_name": "sni.example",
                    "insecure": True, "alpn": ["h3"]},
            "obfs": {"type": "salamander", "password": "ob1"},
        }

    def test_alias_without_password(self):
        ob = _parse("hy2://h.example:443#n")
        assert ob["password"] == ""
        assert ob["tls"] == {"enabled": True, "server_name": "h.example"}
        assert "obfs" not in ob

    def test_obfs_needs_password(self):
        ob = _parse("hy2://h.example:443?obfs=salamander#n")
        assert "obfs" not in ob

    def test_obfs_param_fallback(self):
        ob = _parse("hy2://h.example:443?obfs=salamander&obfsParam=old#n")
        assert ob["obfs"] == {"type": "salamander", "password": "old"}


class TestParseTuic:
    def test_full(self):
        uri = (
            "tuic://uuid-1:secret@t.example:443?sni=s.example&insecure=true"
            "&alpn=h3&congestion_control=cubic#n"
        )
        assert _parse(uri) == {
            "type": "tuic", "tag": "node-1",
            "server": "t.example", "server_port": 443,
            "uuid": "uuid-1", "password": "secret",
            "congestion_control": "cubic",
            "tls": {"enabled": True, "server_name": "s.example",
                    "insecure": True, "alpn": ["h3"]},
        }

    def test_defaults(self):
        ob = _parse("tuic://uuid-only@t.example:443#n")
        assert ob["password"] == ""
        assert ob["congestion_control"] == "bbr"
        assert ob["tls"] == {"enabled": True, "server_name": "t.example"}

    def test_no_at_sign_returns_none(self):
        assert _parse("tuic://no-at-sign") is None


class TestUnsupportedSchemes:
    def test_http_socks_unknown_and_garbage(self):
        assert _parse("http://example.com:8080") is None
        assert _parse("socks://user:pass@h:1080") is None
        assert _parse("wireguard://wg.example") is None
        assert _parse("no-scheme-at-all") is None
