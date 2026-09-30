# -*- coding: utf-8 -*-
"""Тесты состояния (порта Get-VpnState/Save-VpnState, core.ps1:630-641)."""
import json

from vpn_launcher.core.state import DEFAULT_STATE, load_state, save_state


def test_missing_file_returns_defaults(tmp_path):
    st = load_state(tmp_path / "state.json")
    assert st == DEFAULT_STATE
    # мутабельные поля не должны разделяться между вызовами
    st["appList"].append("x.exe")
    assert load_state(tmp_path / "state.json")["appList"] == []


def test_corrupt_file_returns_defaults(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{oops", encoding="utf-8")
    assert load_state(p) == DEFAULT_STATE


def test_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    st = dict(DEFAULT_STATE)
    st.update(subUrl="https://example.com/sub", selected="node-1", autoUrlTest=False)
    save_state(st, p)
    assert load_state(p) == st
    # файл читается как настоящий JSON (совместимость с форматом PS)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["mode"] == "tun"


def test_app_mode_defaults_to_exclude():
    """Режим списка процессов: дефолт - поведение PS 1.0.6 (исключения)."""
    assert DEFAULT_STATE["appMode"] == "exclude"


def test_state_without_app_mode_stays_without_it(tmp_path):
    """Старый файл (PS 1.0.6) не достраивается полями: молча читается как раньше.

    Значение подставляет UI (_restore_state): так совместимость видна явно,
    а load_state остаётся портом Get-VpnState без домысливания.
    """
    p = tmp_path / "state.json"
    st = dict(DEFAULT_STATE)
    st.pop("appMode")
    save_state(st, p)
    loaded = load_state(p)
    assert "appMode" not in loaded
