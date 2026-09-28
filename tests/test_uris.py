# -*- coding: utf-8 -*-
"""Тесты URI-хелперов (порта core.ps1:53-103)."""
from vpn_launcher.core.uris import (
    get_bool_val,
    get_query_val,
    parse_query,
    split_host_port,
    split_uri,
)


class TestSplitUri:
    def test_full(self):
        r = split_uri("  VLESS://user@host:443?security=tls&type=ws#My%20Tag  ")
        assert r["Scheme"] == "vless"
        assert r["Body"] == "user@host:443"
        assert r["Query"] == "security=tls&type=ws"
        assert r["Fragment"] == "My Tag"

    def test_no_scheme(self):
        r = split_uri("nonsense")
        assert r == {"Scheme": "", "Body": "", "Query": "", "Fragment": ""}

    def test_fragment_parsed_before_query(self):
        # '#' срезается первым, поэтому '?' внутри фрагмента остаётся в нём
        r = split_uri("x://h:443#frag?notq")
        assert r["Fragment"] == "frag?notq"
        assert r["Query"] == ""

    def test_no_query(self):
        r = split_uri("trojan://pw@srv:443#n")
        assert r["Body"] == "pw@srv:443"
        assert r["Query"] == ""
        assert r["Fragment"] == "n"


class TestParseQuery:
    def test_basic(self):
        assert parse_query("a=1&b=two") == {"a": "1", "b": "two"}

    def test_percent_decoding(self):
        assert parse_query("path=%2Fws%3Fx") == {"path": "/ws?x"}

    def test_empty_value(self):
        assert parse_query("a=&=x&b") == {"a": "", "b": ""}

    def test_empty_string(self):
        assert parse_query("") == {}

    def test_duplicate_key_last_wins(self):
        assert parse_query("a=1&a=2") == {"a": "2"}


class TestSplitHostPort:
    def test_host_port(self):
        assert split_host_port("example.com:8443") == ("example.com", 8443)

    def test_ipv6_brackets(self):
        assert split_host_port("[2001:db8::1]:443") == ("2001:db8::1", 443)

    def test_bare_host_defaults_443(self):
        assert split_host_port("example.com") == ("example.com", 443)

    def test_non_numeric_port_keeps_whole_string(self):
        assert split_host_port("host:abc") == ("host:abc", 443)

    def test_greedy_last_port_wins(self):
        assert split_host_port("a:1:443") == ("a:1", 443)


class TestQueryVal:
    Q = {"sni": "", "peer": "p.example", "type": "ws"}

    def test_skips_empty_and_takes_first_nonempty(self):
        assert get_query_val(self.Q, ["sni", "peer", "host"]) == "p.example"

    def test_default_when_absent(self):
        assert get_query_val(self.Q, ["nope"], "fallback") == "fallback"

    def test_bool_truthy(self):
        for v in ("1", "true", "YES", "On"):
            assert get_bool_val({"x": v}, ["x"]) is True

    def test_bool_falsy_and_default(self):
        for v in ("0", "no", "off", "abc"):
            assert get_bool_val({"x": v}, ["x"]) is False
        assert get_bool_val({}, ["x"], True) is True
