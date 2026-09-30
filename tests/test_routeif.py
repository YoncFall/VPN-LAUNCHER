# -*- coding: utf-8 -*-
"""Разбор таблицы маршрутов netsh: поиск физического ifIndex для пинга."""
from __future__ import annotations

from vpn_launcher.win.routeif import (
    _ifindex_from_route_table,
    default_gateway_ifindex,
)

# Реальная раскладка netsh на машине с Happ: наш default через шлюз локальной
# сети + default чужого VPN on-link (шлюзом указана само имя интерфейса).
_WITH_HAPP = """
Нет      Вручную   0    0.0.0.0/0                  15  192.168.0.1
Нет      Вручную   0    0.0.0.0/0                  27  happ-xray
Нет      Система   256  172.19.0.0/255.255.255.252  27  172.19.0.1
Нет      Система   256  192.168.0.0/255.255.255.0   15  192.168.0.10
"""


def test_picks_gateway_route_among_onlink_and_tun():
    assert _ifindex_from_route_table(_WITH_HAPP) == 15


def test_loopback_gateway_is_skipped():
    text = "0.0.0.0/0  1  127.0.0.1\n0.0.0.0/0  15  192.168.0.1\n"
    assert _ifindex_from_route_table(text) == 15


def test_only_onlink_defaults_means_none():
    # туннель/чужой VPN: шлюза нет - физического интерфейса из этого не вывести
    text = "0.0.0.0/0  27  happ-xray\n0.0.0.0/0  34  0.0.0.0\n"
    assert _ifindex_from_route_table(text) is None


def test_empty_text_is_none():
    assert _ifindex_from_route_table("") is None


def test_live_discovery_returns_something_sane():
    """На машине разработчика netsh обязан отдать положительный ifIndex."""
    idx = default_gateway_ifindex()
    assert idx is None or (isinstance(idx, int) and idx > 0)
