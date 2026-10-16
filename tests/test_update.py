# -*- coding: utf-8 -*-
"""Проверка обновления (2.4.0): сравнение версий, разбор apps.json, мост.

Сеть не трогаем: fetch_latest/parse_latest кормятся фикстурами, воркеры
проверяются через подмену ядра.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vpn_launcher.core import update as upd  # noqa: E402


# ---- сравнение версий ------------------------------------------------------
def test_parse_version_ignores_noise():
    assert upd.parse_version("2.3.10") == (2, 3, 10)
    assert upd.parse_version("v2.0.4-beta") == (2, 0, 4)
    assert upd.parse_version("") == ()


def test_is_newer_numeric_not_lexical():
    assert upd.is_newer("2.3.10", "2.3.9")  # лексикографически 2.3.10 < 2.3.9!
    assert upd.is_newer("2.4.0", "2.3.3")
    assert not upd.is_newer("2.3.3", "2.3.3")
    assert not upd.is_newer("2.3.2", "2.3.3")
    assert upd.is_newer("2.4", "2.3.3")  # короткая версия дополняется нулями


# ---- разбор apps.json ------------------------------------------------------
_APPS_JSON = """
{
  "categories": [
    {"id": "vpn", "apps": [
      {"slug": "vpn-launcher", "version": "2.4.0",
       "download": "https://example.com/Setup.exe",
       "downloadZip": "https://example.com/app.zip",
       "releasePage": "https://example.com/releases"},
      {"slug": "other", "version": "9.9.9"}
    ]}
  ]
}
"""


def test_parse_latest_newer_version():
    info = upd.parse_latest(_APPS_JSON, "vpn-launcher", "2.3.3")
    assert info is not None
    assert info.version == "2.4.0"
    assert info.download.endswith("Setup.exe")
    assert info.download_zip.endswith("app.zip")
    assert info.release_page.endswith("releases")


def test_parse_latest_same_version_is_none():
    assert upd.parse_latest(_APPS_JSON, "vpn-launcher", "2.4.0") is None


def test_parse_latest_broken_json_is_none():
    assert upd.parse_latest("не json", "vpn-launcher", "1.0") is None
    assert upd.parse_latest("{}", "vpn-launcher", "1.0") is None
    assert upd.parse_latest(_APPS_JSON, "нет-такого", "1.0") is None


def test_fetch_latest_offline_is_none(monkeypatch):  # noqa: ANN001
    def boom(*_a, **_k):
        raise OSError("offline")

    monkeypatch.setattr(upd.urllib.request, "urlopen", boom)
    assert upd.fetch_latest(current="2.3.3") is None


def test_helper_script_waits_for_pid_then_installs_silently(tmp_path):  # noqa: ANN001
    script = upd.helper_script(tmp_path / "Setup.exe", tmp_path / "VPNLauncher.exe")
    assert "Wait-Process" in script
    # тихий режим: без окон установщика; сам запуск приложения после установки
    assert "'/S'" in script
    assert "Start-Process -FilePath $App" in script
    assert "vpnlauncher_setup.log" in script  # ошибка установки не остаётся незамеченной


# ---- мост (плашка в snapshot, слоты) --------------------------------------
@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bridge(qapp):  # noqa: ANN001, ANN201
    """Реальное окно (offscreen) + мост без страницы."""
    from vpn_launcher.ui.web.bridge import Bridge
    from vpn_launcher.ui.window import MainWindow

    win = MainWindow()
    br = Bridge(win)
    yield br
    win.btn_zapret.close()
    win.close()


def test_snapshot_update_field(bridge):  # noqa: ANN001
    assert bridge.snapshot()["update"] is None

    info = upd.UpdateInfo(
        version="2.4.0",
        download="https://example.com/Setup.exe",
        download_zip="https://example.com/app.zip",
        release_page="https://example.com/releases",
    )
    bridge._on_update_found(info)
    s = bridge.snapshot()["update"]
    assert s["version"] == "2.4.0"
    assert s["phase"] == "ready"

    bridge.dismissUpdate()
    assert bridge.snapshot()["update"] is None


def test_found_after_dismiss_is_ignored(bridge):  # noqa: ANN001
    bridge.dismissUpdate()
    bridge._on_update_found(upd.UpdateInfo("2.4.0", "u", "z", "p"))
    assert bridge.snapshot()["update"] is None


def test_do_update_portable_opens_page(bridge, monkeypatch):  # noqa: ANN001
    opened = []
    import vpn_launcher.ui.web.bridge as br  # noqa: PLC0415

    monkeypatch.setattr(br, "is_installed_copy", lambda: False)
    monkeypatch.setattr(br.webbrowser, "open", lambda url: opened.append(url))

    bridge._on_update_found(upd.UpdateInfo("2.4.0", "u", "z", "https://page"))
    bridge.doUpdate()
    assert opened == ["https://page"]
    assert bridge.snapshot()["update"] is None  # спрятана после перехода
