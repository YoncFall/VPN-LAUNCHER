# -*- coding: utf-8 -*-
"""Паритет с PowerShell 1.0.6: golden-файлы + прогон sing-box check (этап 1).

Golden снимаются скриптом tools/make_golden.ps1 (оригинальный core.ps1,
PowerShell 5.1) на фикстурах tests/fixtures/. Тесты сверяют вывод
Python-порта с выводом PS-версии на тех же данных + гоняют конфиги
через `sing-box check`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vpn_launcher.core import config as cfg  # модуль, чтобы pytest не собрал test_sing_box_config
from vpn_launcher.core.subscription import parse_node_list

GOLDEN = Path(__file__).parent / "golden"
FIXTURES = Path(__file__).parent / "fixtures"

_NOLOG = lambda m: None  # noqa: E731 - тесты не пишут в журнал


def _golden(name: str):
    p = GOLDEN / name
    assert p.is_file(), (
        f"нет golden {name}; снимите: powershell -ExecutionPolicy Bypass "
        f"-File tools\\make_golden.ps1 -Core <путь>\\VPN-LAUNCHER-src\\src\\core.ps1"
    )
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _nodes(b64: bool = False) -> list[dict]:
    name = "subscription-b64.txt" if b64 else "subscription.txt"
    return parse_node_list((FIXTURES / name).read_text(encoding="utf-8"), logger=_NOLOG)


CONFIG_CASES = [
    ("config-tun.json", dict(mode="tun", app_list=("mygame.exe", "steam.exe"))),
    ("config-proxy-selected.json",
     dict(mode="proxy", selected=("node-1", "node-8", "node-16"), only_selected=True)),
    ("config-single.json", dict(mode="tun", selected=("node-7",), only_selected=True)),
]


def _ps_parity_view(built: dict) -> dict:
    """Конфиг в том виде, какой дал бы оригинальный core.ps1 1.0.6.

    Golden сняты PowerShell-версией; с 30.09.2026 Python-версия намеренно
    уходит от неё в tun-инбаунде (сознательные отклонения, см. core/config.py
    и README): strict_route=true убивал DNS на время туннеля (WFP режет
    порт 53 вне туннеля), а авто-default 0.0.0.0/0 проигрывал по метрике
    default чужого VPN (Happ). Для сравнения с эталоном поля приводятся к
    PS-виду; фактические значения проверяет tests/test_config.py.
    """
    import copy

    out = copy.deepcopy(built)
    for inbound in out.get("inbounds", []):
        if inbound.get("type") == "tun":
            inbound["strict_route"] = True
            inbound.pop("route_address", None)
    return out


def test_parse_plain_matches_golden():
    assert _nodes() == _golden("parse-nodes.json")


def test_parse_b64_matches_golden():
    assert _nodes(b64=True) == _golden("parse-nodes-b64.json")


def test_b64_and_plain_subscriptions_parse_identically():
    assert _nodes(b64=True) == _nodes()


@pytest.mark.parametrize("name,kwargs", CONFIG_CASES)
def test_config_matches_golden(name: str, kwargs: dict):
    built = cfg.build_sing_box_config(_nodes(), install_root="vpn-golden-root", **kwargs)
    assert _ps_parity_view(built) == _golden(name)


@pytest.mark.parametrize("name,kwargs", CONFIG_CASES)
def test_generated_config_passes_sing_box_check(name: str, kwargs: dict, tmp_path, sing_box_exe):
    built = cfg.build_sing_box_config(_nodes(), install_root="vpn-golden-root", **kwargs)
    p = cfg.write_config(built, tmp_path / name)
    ok, err = cfg.test_sing_box_config(p, sing_box=sing_box_exe)
    assert ok, f"sing-box check failed for {name}: {err}"
