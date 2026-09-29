# -*- coding: utf-8 -*-
"""Тесты генерации конфига sing-box (без golden: паритет - в test_golden.py)."""
from __future__ import annotations

import json

import pytest

from vpn_launcher.core import config as cfg  # модуль, чтобы pytest не собрал test_sing_box_config
from vpn_launcher.core.config import (
    GAME_SAFE_PROCESSES,
    ConfigError,
    build_sing_box_config,
    write_config,
)


def _nodes(n: int = 3) -> list[dict]:
    return [
        {"type": "vless", "tag": f"node-{i}", "server": f"h{i}.example",
         "server_port": 443, "uuid": "uuid-1"}
        for i in range(1, n + 1)
    ]


def _outbounds(c: dict) -> dict[str, dict]:
    return {o["tag"]: o for o in c["outbounds"]}


class TestGameSafeProcesses:
    def test_list_is_complete_and_unique(self):
        assert len(GAME_SAFE_PROCESSES) == 25  # как в core.ps1:457-464
        assert len(set(GAME_SAFE_PROCESSES)) == 25
        assert "steam.exe" in GAME_SAFE_PROCESSES
        assert "cs2.exe" in GAME_SAFE_PROCESSES
        assert all(GAME_SAFE_PROCESSES)  # без пустых строк


class TestBuildBasics:
    def test_no_servers_raises(self):
        with pytest.raises(ConfigError, match="Нет ни одного сервера"):
            build_sing_box_config([])

    def test_bad_mode_raises(self):
        with pytest.raises(ConfigError, match="Неизвестный режим"):
            build_sing_box_config(_nodes(), mode="sysproxy")

    def test_top_level_shape(self):
        c = build_sing_box_config(_nodes())
        assert c["log"] == {"level": "info", "timestamp": True}
        assert c["dns"]["final"] == "dns-out"
        assert c["route"]["final"] == "proxy-group"
        assert c["route"]["auto_detect_interface"] is True
        assert c["route"]["default_domain_resolver"] == {"server": "dns-local"}
        assert [r.get("action") for r in c["route"]["rules"][:2]] == ["sniff", "hijack-dns"]

    def test_outbound_copy_keys_and_group(self):
        nodes = _nodes()
        c = build_sing_box_config(nodes)
        ob = _outbounds(c)["node-1"]
        assert ob == {"type": "vless", "tag": "node-1", "server": "h1.example",
                      "server_port": 443, "uuid": "uuid-1"}
        assert ob is not nodes[0]  # нода копируется, исходный список не трогается
        assert _outbounds(c)["direct"] == {"type": "direct", "tag": "direct"}
        group = _outbounds(c)["proxy-group"]
        assert group["type"] == "urltest"
        assert group["outbounds"] == ["node-1", "node-2", "node-3"]
        assert group["url"] == "https://www.gstatic.com/generate_204"
        assert group["interval"] == "10m"
        assert group["tolerance"] == 50
        assert group["interrupt_exist_connections"] is True

    def test_single_selected_node_becomes_selector(self):
        c = build_sing_box_config(_nodes(), selected=("node-2",), only_selected=True)
        assert [o["tag"] for o in c["outbounds"]] == ["node-2", "direct", "proxy-group"]
        assert _outbounds(c)["proxy-group"] == {
            "type": "selector", "tag": "proxy-group",
            "outbounds": ["node-2"], "default": "node-2",
            "interrupt_exist_connections": True,
        }

    def test_selected_without_only_selected_keeps_all_outbounds(self):
        # PS-поведение (core.ps1:498): пул нод не фильтруется, группа - только selected
        c = build_sing_box_config(_nodes(), selected=("node-3",))
        assert [o["tag"] for o in c["outbounds"]][:3] == ["node-1", "node-2", "node-3"]
        assert _outbounds(c)["proxy-group"]["outbounds"] == ["node-3"]

    def test_only_selected_is_case_insensitive_like_ps_contains(self):
        c = build_sing_box_config(_nodes(), selected=("NODE-2",), only_selected=True)
        assert [o["tag"] for o in c["outbounds"]][:1] == ["node-2"]


class TestModesAndRules:
    def test_tun_inbound(self):
        c = build_sing_box_config(_nodes(), mode="tun")
        tun = c["inbounds"][0]
        assert tun == {
            "type": "tun", "tag": "tun-in", "interface_name": "vpn-launcher-tun",
            "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"], "mtu": 1500,
            "auto_route": True, "strict_route": True, "stack": "mixed",
        }
        assert len(c["inbounds"]) == 1

    def test_proxy_inbounds_and_socks_port(self):
        from vpn_launcher.paths import SOCKS_PORT
        c = build_sing_box_config(_nodes(), mode="proxy")
        assert c["inbounds"] == [
            {"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": SOCKS_PORT},
            {"type": "http", "tag": "http-in", "listen": "127.0.0.1", "listen_port": SOCKS_PORT + 1},
        ]
        # в proxy-режиме правила процессов нет
        assert not any("process_name" in r for r in c["route"]["rules"])

    def test_tun_has_process_and_local_rules(self):
        c = build_sing_box_config(_nodes(), mode="tun", app_list=("mygame.exe",))
        rules = c["route"]["rules"]
        proc_rule = next(r for r in rules if "process_name" in r)
        assert proc_rule["action"] == "route"
        assert proc_rule["outbound"] == "direct"
        assert proc_rule["process_name"][-1] == "mygame.exe"
        local_rule = rules[-1]
        assert local_rule["ip_cidr"][0] == "127.0.0.0/8"
        assert local_rule["outbound"] == "direct"

    def test_duplicate_app_dedup_keeps_first_position(self):
        c = build_sing_box_config(_nodes(), mode="tun", app_list=("steam.exe", "mygame.exe"))
        proc_rule = next(r for r in c["route"]["rules"] if "process_name" in r)
        names = proc_rule["process_name"]
        assert names.count("steam.exe") == 1
        assert names[-1] == "mygame.exe"

    def test_app_dedup_is_case_sensitive_like_select_object_unique(self):
        # проверено empirically на PS 5.1: Select-Object -Unique регистрозависим
        c = build_sing_box_config(_nodes(), mode="tun", app_list=("STEAM.EXE",))
        proc_rule = next(r for r in c["route"]["rules"] if "process_name" in r)
        assert "steam.exe" in proc_rule["process_name"]
        assert "STEAM.EXE" in proc_rule["process_name"]


class TestCachePath:
    def test_explicit_install_root(self):
        c = build_sing_box_config(_nodes(), install_root="vpn-golden-root")
        assert c["experimental"]["cache_file"] == {
            "enabled": True, "path": "vpn-golden-root\\cache.db",
        }

    def test_default_install_root_is_config_dir(self):
        from vpn_launcher.paths import install_root
        c = build_sing_box_config(_nodes())
        assert c["experimental"]["cache_file"]["path"] == str(install_root() / "cache.db")


class TestWriteAndNew:
    def test_write_config_roundtrip_utf8_no_bom(self, tmp_path):
        c = build_sing_box_config(_nodes())
        p = write_config(c, tmp_path / "config.json")
        raw = p.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert json.loads(raw.decode("utf-8")) == c

    def test_new_sing_box_config_writes_and_logs(self, tmp_path, monkeypatch):
        lines: list[str] = []
        monkeypatch.setattr(cfg, "write_log", lines.append)
        p = cfg.new_sing_box_config(
            _nodes(), mode="tun", app_list=("mygame.exe",), path=tmp_path / "config.json"
        )
        assert p.is_file()
        assert json.loads(p.read_text(encoding="utf-8")) == build_sing_box_config(
            _nodes(), mode="tun", app_list=("mygame.exe",)
        )
        # порядок и шаблоны строк - как в Write-VpnLog (core.ps1:530, 581)
        assert lines[0].startswith("  direct-exclude apps: ")
        assert "steam.exe" in lines[0] and "mygame.exe" in lines[0]
        assert lines[-1] == "config written: 5 outbounds, mode=tun, final=proxy-group"

    def test_new_sing_box_config_proxy_mode_skips_direct_apps_log(self, tmp_path, monkeypatch):
        lines: list[str] = []
        monkeypatch.setattr(cfg, "write_log", lines.append)
        cfg.new_sing_box_config(_nodes(), mode="proxy", path=tmp_path / "c.json")
        assert len(lines) == 1  # только "config written"

    def test_new_sing_box_config_logs_tun_address(self, tmp_path, monkeypatch):
        # адрес TUN-адаптера должен быть виден в журнале: конфликт с чужим VPN
        # иначе остаётся только в singbox.log.err, который обрезается при старте
        lines: list[str] = []
        monkeypatch.setattr(cfg, "write_log", lines.append)
        cfg.new_sing_box_config(_nodes(), mode="tun", path=tmp_path / "c.json")
        assert len(lines) == 3  # direct-exclude + адрес + итог
        assert lines[1] == "tun address: 172.19.0.1/30, fdfe:dcba:9876::1/126"
        assert lines[-1] == "config written: 5 outbounds, mode=tun, final=proxy-group"


class TestCheck:
    def test_missing_engine_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            cfg.test_sing_box_config(tmp_path / "x.json", sing_box=tmp_path / "nope.exe")
