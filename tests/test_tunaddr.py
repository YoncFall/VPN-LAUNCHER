# -*- coding: utf-8 -*-
"""Подбор свободного адреса TUN-инбаунда (win/tunaddr).

Главная причина появления модуля: зашитый 172.19.0.1/30 бывает занят чужим
VPN (Happ на машине разработчика), и sing-box падает с
'set ipv4 address: The object already exists'.
"""
from __future__ import annotations

import ipaddress

from vpn_launcher.core import config as cfg
from vpn_launcher.win.tunaddr import (
    TUN_V4_CANDIDATES,
    TUN_V6_CANDIDATES,
    assigned_addresses,
    choose_tun_addresses,
    happ_installed,
    reserved_addresses,
)

DEFAULT = ["172.19.0.1/30", "fdfe:dcba:9876::1/126"]


def _nodes(n: int = 3) -> list[dict]:
    return [
        {"type": "vless", "tag": f"node-{i}", "server": f"h{i}.example",
         "server_port": 443, "uuid": "uuid-1"}
        for i in range(1, n + 1)
    ]


class TestAssignedAddresses:
    def test_returns_parseable_addresses(self):
        addrs = assigned_addresses()
        assert isinstance(addrs, set)
        for a in addrs:
            ipaddress.ip_address(a)  # битый адрес = распарсился бы с ошибкой
        assert "127.0.0.1" in addrs  # петля есть у любой машины


class TestChoose:
    def test_default_when_nothing_taken(self):
        assert choose_tun_addresses(assigned=[]) == DEFAULT

    def test_foreign_tun_subnet_is_avoided(self):
        # как на машине с Happ: 172.19.0.1/30 занят чужим адаптером
        assert choose_tun_addresses(assigned=["172.19.0.1"]) == [
            "172.19.0.5/30", "fdfe:dcba:9876::1/126",
        ]

    def test_any_address_inside_subnet_is_a_conflict(self):
        # 172.19.0.2 лежит в нашей /30, хотя первым хостом не является
        assert choose_tun_addresses(assigned=["172.19.0.2"])[0] == "172.19.0.5/30"

    def test_addresses_outside_pool_are_ignored(self):
        assert choose_tun_addresses(
            assigned=["192.168.0.10", "10.1.2.3", "::1", "fe80::1"]
        ) == DEFAULT

    def test_taken_ipv6_falls_through_to_next(self):
        assert choose_tun_addresses(assigned=["fdfe:dcba:9876::1"]) == [
            "172.19.0.1/30", "fdfe:dcba:9876::5/126",
        ]

    def test_no_free_ipv6_keeps_ipv4_only(self):
        taken = [f"fdfe:dcba:9876::{i}" for i in range(1, 254, 4)]
        assert choose_tun_addresses(assigned=taken) == ["172.19.0.1/30"]

    def test_no_free_v4_falls_back_to_first_candidate(self):
        # ничего не нашли -> поведение 1.0.6, но не ошибка
        taken = [f"172.19.0.{i}" for i in range(1, 254, 4)] + ["198.18.0.1"]
        assert choose_tun_addresses(assigned=taken)[0] == "172.19.0.1/30"

    def test_pools_have_no_overlapping_subnets(self):
        v4 = [ipaddress.ip_network(c, strict=False) for c in TUN_V4_CANDIDATES]
        v6 = [ipaddress.ip_network(c, strict=False) for c in TUN_V6_CANDIDATES]
        assert len(set(v4)) == len(v4)
        assert len(set(v6)) == len(v6)

    def test_first_candidates_keep_parity_with_1_0_6(self):
        # без конфликтов вывод должен совпадать с PS-версией (golden-файлы)
        assert TUN_V4_CANDIDATES[0] == "172.19.0.1/30"
        assert TUN_V6_CANDIDATES[0] == "fdfe:dcba:9876::1/126"


class TestHappReservation:
    """Happ пересоздаёт адаптер при переподключении - окно, когда его адрес
    выглядит свободным (30.09.2026: 01:04:36 мы на .5, 01:05:12 - уже на ЕГО .1).
    Подсеть чужого VPN должна быть табу, пока Happ УСТАНОВЛЕН, а не запущен.
    """

    def test_reserved_is_empty_without_happ(self, monkeypatch):
        monkeypatch.setattr("vpn_launcher.win.tunaddr.happ_installed", lambda: False)
        assert reserved_addresses() == set()

    def test_reserved_covers_happ_subnet(self, monkeypatch):
        monkeypatch.setattr("vpn_launcher.win.tunaddr.happ_installed", lambda: True)
        assert {"172.19.0.1", "172.19.0.2"} <= reserved_addresses()

    def test_adapter_gone_but_happ_installed_still_avoids_subnet(self, monkeypatch):
        # assigned=None (системный проба в тестах пустой, conftest), но резерв
        # обязан сработать:172.19.0.1/30 не выбирается, даже когда занятости
        # у Happ сейчас не видно
        monkeypatch.setattr("vpn_launcher.win.tunaddr.happ_installed", lambda: True)
        assert choose_tun_addresses() == [
            "172.19.0.5/30", "fdfe:dcba:9876::1/126",
        ]

    def test_explicit_assigned_ignores_reservation(self, monkeypatch):
        # явный список = детерминированный режим golden: резерв не применяется
        monkeypatch.setattr("vpn_launcher.win.tunaddr.happ_installed", lambda: True)
        assert choose_tun_addresses(assigned=[]) == DEFAULT

    def test_happ_detector_returns_bool(self):
        # машинозависимо: здесь важен только тип (True на машине с Happ)
        assert isinstance(happ_installed(), bool)

    def test_config_takes_reserved_subnet_into_account(self, monkeypatch):
        monkeypatch.setattr("vpn_launcher.win.tunaddr.happ_installed", lambda: True)
        c = cfg.build_sing_box_config(_nodes(), mode="tun")
        assert c["inbounds"][0]["address"] == [
            "172.19.0.5/30", "fdfe:dcba:9876::1/126",
        ]


class TestWiringIntoConfig:
    def test_config_takes_address_from_probe(self, monkeypatch):
        monkeypatch.setattr(
            "vpn_launcher.win.tunaddr.assigned_addresses", lambda: {"172.19.0.1"}
        )
        c = cfg.build_sing_box_config(_nodes(), mode="tun")
        assert c["inbounds"][0]["address"] == [
            "172.19.0.5/30", "fdfe:dcba:9876::1/126",
        ]

    def test_config_uses_default_when_probe_finds_conflict_free_machine(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "vpn_launcher.win.tunaddr.assigned_addresses", lambda: set()
        )
        c = cfg.build_sing_box_config(_nodes(), mode="tun")
        assert c["inbounds"][0]["address"] == DEFAULT
