# -*- coding: utf-8 -*-
"""Проверка обновления (2.4.0): сравнение версий, разбор apps.json, мост.

Сеть не трогаем: fetch_latest/parse_latest кормятся фикстурами, воркеры
проверяются через подмену ядра.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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


def test_parse_latest_utf8_bom_is_tolerated():
    """BOM перед JSON (PowerShell пишет с BOM) не должен ломать разбор.

    Регрессия инцидента 31.10.2026: BOM в apps.json молча гасил плашку
    обновления у всех установленных копий.
    """
    bom_json = "\ufeff" + _APPS_JSON.lstrip("\n")
    info = upd.parse_latest(bom_json, "vpn-launcher", "2.3.3")
    assert info is not None
    assert info.version == "2.4.0"


class _FakeResp:
    """Мини-заглушка urlopen-ответа: только read()/контекст."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):  # noqa: ANN201
        return self

    def __exit__(self, *_a):  # noqa: ANN002, ANN201
        return False


def test_fetch_latest_tolerates_utf8_bom_bytes(monkeypatch):  # noqa: ANN001
    """Путь целиком: байты с BOM из сети -> UpdateInfo, а не молчаливый None."""
    data = ("\ufeff" + _APPS_JSON.lstrip("\n")).encode("utf-8")
    monkeypatch.setattr(
        upd.urllib.request, "urlopen", lambda *_a, **_k: _FakeResp(data)
    )
    info = upd.fetch_latest(current="2.3.3")
    assert info is not None
    assert info.version == "2.4.0"


def test_fetch_latest_offline_is_none(monkeypatch):  # noqa: ANN001
    def boom(*_a, **_k):
        raise OSError("offline")

    monkeypatch.setattr(upd.urllib.request, "urlopen", boom)
    assert upd.fetch_latest(current="2.3.3") is None


def test_helper_script_waits_for_pid_then_installs_silently(tmp_path):  # noqa: ANN001
    script = upd.helper_script(
        tmp_path / "Setup.exe", tmp_path / "VPNLauncher.exe", "2.4.8"
    )
    assert "Wait-Process" in script
    # тихий режим: без окон установщика; сам запуск приложения после установки
    assert "'/S'" in script
    assert "Start-Process -FilePath $App" in script
    assert "vpnlauncher_setup.log" in script  # ошибка установки не остаётся незамеченной
    # 2.4.8: никаких блокнотов и окон с текстом скрипта
    assert "notepad" not in script
    assert "MessageBox" not in script
    assert "vpnlauncher_update_error.txt" in script
    assert "Remove-Item -LiteralPath $Lock" in script
    # ждём смены версии, а не только код возврата установщика
    assert "$TargetVer" in script
    # 2.4.9: ненулевой код установщика - тоже ошибка, даже если версия уже
    # сменилась (частичное копирование из-за занятого файла)
    assert "$code -ne '0'" in script
    assert "$code -ne '4'" in script


def test_helper_script_installs_into_given_folder(tmp_path):  # noqa: ANN001
    """2.4.9: обновление ставится туда, где стоит программа.

    Без /DIR Setup.exe ставил в %LOCALAPPDATA%\\Programs\\VPNLauncher и при
    нестандартном пути удалял прежнюю копию вместе с state.json.
    """
    script = upd.helper_script(
        tmp_path / "Setup.exe",
        tmp_path / "VPNLauncher.exe",
        "2.4.9",
        tmp_path / "Install Dir",
    )
    assert "[string]$Dir" in script
    assert "$sa += '/DIR=\"' + $Dir + '\"'" in script
    assert "-ArgumentList $sa" in script
    # путь с пробелами обязан попасть в кавычках
    assert "'/DIR=\"'" in script


def test_launch_helper_passes_dir(tmp_path, monkeypatch):  # noqa: ANN001
    import subprocess  # noqa: PLC0415

    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):  # noqa: ANN001, ANN003
        captured["args"] = list(args)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    install_dir = tmp_path / "Install Dir"
    upd.launch_helper(
        tmp_path / "helper.ps1",
        tmp_path / "Setup.exe",
        tmp_path / "App.exe",
        "2.4.9",
        tmp_path / "update.lock",
        install_dir,
    )
    args = captured["args"]
    assert args[args.index("-Dir") + 1] == str(install_dir)


def test_write_helper_is_utf8_with_bom(tmp_path):  # noqa: ANN001
    dest = tmp_path / "helper.ps1"
    upd.write_helper(dest, tmp_path / "Setup.exe", tmp_path / "App.exe", "2.4.8")
    raw = dest.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "Обновление не установилось" in raw.decode("utf-8-sig")


# ---- lock на время обновления (2.4.8) --------------------------------------
def test_update_lock_roundtrip(tmp_path, monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(upd, "update_lock_path", lambda: tmp_path / "update.lock")

    assert upd.read_update_lock() is None
    upd.write_update_lock("2.4.8")
    info = upd.read_update_lock()
    assert info is not None and info["version"] == "2.4.8"

    upd.clear_update_lock()
    assert upd.read_update_lock() is None


def test_stale_update_lock_is_ignored(tmp_path, monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(upd, "update_lock_path", lambda: tmp_path / "update.lock")
    (tmp_path / "update.lock").write_text(
        '{"version": "2.4.8", "pid": 1, "ts": 0}', encoding="utf-8"
    )
    assert upd.read_update_lock() is None


def test_broken_update_lock_is_ignored(tmp_path, monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(upd, "update_lock_path", lambda: tmp_path / "update.lock")
    (tmp_path / "update.lock").write_text("{oops", encoding="utf-8")
    assert upd.read_update_lock() is None


def test_take_update_error_reads_and_removes(tmp_path, monkeypatch):  # noqa: ANN001
    path = tmp_path / "err.txt"
    path.write_text("Обновление не установилось.\nКод: 2", encoding="utf-8")
    monkeypatch.setattr(upd, "update_error_path", lambda: path)

    text = upd.take_update_error()

    assert text.startswith("Обновление не установилось")
    assert not path.exists()
    assert upd.take_update_error() == ""


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


def test_update_done_installs_into_current_folder(bridge, monkeypatch):  # noqa: ANN001
    """2.4.9: helper получает папку работающей копии, а не путь по умолчанию."""
    import vpn_launcher.ui.web.bridge as br  # noqa: PLC0415

    calls: dict[str, tuple] = {}
    fake_timer = type("_T", (), {"singleShot": staticmethod(lambda *a: None)})
    monkeypatch.setattr(br, "QTimer", fake_timer)
    monkeypatch.setattr(br, "update_lock_path", lambda: Path("update.lock"))
    monkeypatch.setattr(br, "write_update_lock", lambda v: None)
    monkeypatch.setattr(br, "write_helper", lambda *a: calls.setdefault("helper", a))
    monkeypatch.setattr(br, "launch_helper", lambda *a: calls.setdefault("launch", a))

    bridge._on_update_found(upd.UpdateInfo("2.4.9", "u", "z", "https://page"))
    bridge._on_update_done("C:/tmp/Setup.exe")

    expected = Path(sys.executable).parent
    assert calls["helper"][-1] == expected
    assert calls["launch"][-1] == expected
