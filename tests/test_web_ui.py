# -*- coding: utf-8 -*-
"""HTML-интерфейс (13.10.2026): ассеты, мост страницы и логика окна.

Мост проверяем без запуска браузера (offscreen + подставная «страница»),
поэтому тесты быстрые и не зависят от QtWebEngine.
"""
from __future__ import annotations

import json
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vpn_launcher.core import state as state_mod  # noqa: E402
from vpn_launcher.ui import theme  # noqa: E402
from vpn_launcher.ui.web.bridge import Bridge, _ping_cell  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("vpn_launcher.ui.window.set_proxy_off", lambda: None)
    monkeypatch.setattr("vpn_launcher.ui.window.set_proxy_on", lambda: None)


class FakePage:
    """Страница вместо QWebEnginePage: собирает присланные JS-вызовы."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def runJavaScript(self, js: str) -> None:  # noqa: N802
        self.calls.append(js)

    def modal_payloads(self) -> list[dict]:
        out = []
        for call in self.calls:
            m = re.match(r"VPL\.modal\((\{.*\})\);$", call, re.S)
            if m:
                out.append(json.loads(m.group(1)))
        return out

    def applied(self) -> list[dict]:
        out = []
        for call in self.calls:
            m = re.match(r"VPL\.apply\((\{.*\})\);$", call, re.S)
            if m:
                out.append(json.loads(m.group(1)))
        return out


@pytest.fixture
def web(qapp):  # noqa: ANN001, ANN201
    """MainWindow + мост с подставной страницей."""
    from vpn_launcher.ui.window import MainWindow

    win = MainWindow()
    bridge = Bridge(win)
    page = FakePage()
    bridge.page = page
    yield win, bridge, page
    win.btn_zapret.close()
    win.close()


# ---- ассеты -------------------------------------------------------------
def test_web_assets_exist():
    from vpn_launcher.ui.web.window import assets_dir

    d = assets_dir()
    assert (d / "app.html").exists()
    assert (d / "app.js").exists()


def test_page_html_has_all_hooks():
    """В разметке есть id, по которым страница общается с мостом."""
    from vpn_launcher.ui.web.window import assets_dir

    html = (assets_dir() / "app.html").read_text(encoding="utf-8")
    for hook in (
        'id="btnMinimize"',
        'id="btnClose"',
        'id="btnLoad"',
        'id="btnPing"',
        'id="btnLog"',
        'id="serverList"',
        'id="processList"',
        'id="processInput"',
        'id="addProcess"',
        'id="removeProcess"',
        'id="clearProcesses"',
        'id="appSecHeading"',
        'id="appsHint"',
        'id="connectButton"',
        'id="disconnectButton"',
        'id="checkConfigButton"',
        'id="connectionLamp"',
        'id="connectionStatusText"',
        'id="dpiLamp"',
        'id="externalIp"',
        'id="rocket"',
        'id="modalLayer"',
        'id="processDrop"',
    ):
        assert hook in html, hook
    # демо-разметка макета вычищена - строки приходят из Qt
    assert 'data-process="chrome.exe"' not in html
    assert "Netherlands · Amsterdam" not in html


def test_page_js_calls_bridge():
    """app.js дёргает команды моста (иначе интерфейс «мёртвый»)."""
    from vpn_launcher.ui.web.window import assets_dir

    js = (assets_dir() / "app.js").read_text(encoding="utf-8")
    for call in (
        "bridge.ready()",
        ".loadSub()",
        ".pingServers()",
        ".openLog()",
        ".connectVpn()",
        ".disconnectVpn()",
        ".testConfig()",
        ".toggleDpi()",
        ".autoDpi()",
        ".addProcess()",
        ".removeProcess()",
        ".clearProcesses()",
        ".setAppMode(",
        ".setMode(",
        ".selectServer(",
        ".selectExcl(",
        ".setSubUrl(",
        ".setProcText(",
        ".minimize()",
        ".closeWin()",
        ".answerModal(",
        ".dragStart(",
        ".dragMove(",
        ".dragEnd(",
    ):
        assert call in js, call
    # состояние страница берёт только из моста, не из демо-разметки
    assert "VPL.apply(" in js or "apply(" in js


# ---- снимок состояния ---------------------------------------------------
def test_snapshot_initial_state(web):  # noqa: ANN001
    win, bridge, _page = web
    s = bridge.snapshot()
    assert s["subUrl"] == ""
    assert s["servers"] == []
    assert s["serverSelected"] == -1
    assert s["status"] == "Готов"
    assert s["lamp"] == "off"
    assert s["dpiLamp"] == "off"
    assert s["connect"] is True
    assert s["disconnect"] is False
    assert s["egress"] == "Внешний IP: недоступен"
    assert s["mode"] in ("tun", "proxy")
    assert s["appSec"] in ("ИСКЛЮЧЕНИЯ", "ЧЕРЕЗ VPN")


def test_snapshot_servers_with_ping(web):  # noqa: ANN001
    win, bridge, _page = web
    win.nodes = [
        {"display": "DE-Frankfurt-01", "proto": "vless", "tag": "de"},
        {"display": "US-NewYork-02", "proto": "trojan", "tag": "us"},
    ]
    win.list_servers.set_nodes(win.nodes)
    win.list_servers.set_pings({"de": 42, "us": 700})
    win.list_servers.select_index(1)
    s = bridge.snapshot()
    assert [r["name"] for r in s["servers"]] == ["DE-Frankfurt-01", "US-NewYork-02"]
    assert s["servers"][0]["pingText"] == "42 ms"
    assert s["servers"][0]["pingClass"] == "good"
    assert s["servers"][1]["pingClass"] == "bad"
    assert s["servers"][0]["proto"] == "vless"
    assert s["serverSelected"] == 1


def test_snapshot_exceptions_and_modes(web):  # noqa: ANN001
    win, bridge, _page = web
    win.picker_proc.setText("mygame.exe")
    win._excl_add()
    win.list_excl.select_index(0)
    s = bridge.snapshot()
    assert s["excl"] == ["mygame.exe"]
    assert s["exclSelected"] == 0
    assert s["procText"] == ""
    win._select_app_mode("include")
    s = bridge.snapshot()
    assert s["appMode"] == "include"
    assert s["appSec"] == "ЧЕРЕЗ VPN"
    assert "через VPN" in s["appHint"]


def test_status_kind_follows_color(web):  # noqa: ANN001
    win, bridge, _page = web
    win._status("Готов")
    assert bridge.snapshot()["statusKind"] == "info"
    win._status("Ошибка загрузки", theme.DANGER)
    s = bridge.snapshot()
    assert s["statusKind"] == "error"
    assert s["status"] == "Ошибка загрузки"


def test_lamp_mapping(web):  # noqa: ANN001
    win, bridge, _page = web
    win.led_status.set_state("ok")
    win.led_zapret.set_state("warn")
    s = bridge.snapshot()
    assert s["lamp"] == "ready"
    assert s["dpiLamp"] == "connecting"


def test_ping_cell_matches_qt_rules():
    assert _ping_cell(None) == ("---", "")
    assert _ping_cell(-2) == ("...", "")
    assert _ping_cell(-1) == ("offline", "bad")
    assert _ping_cell(42) == ("42 ms", "good")
    assert _ping_cell(150) == ("150 ms", "medium")
    assert _ping_cell(900) == ("900 ms", "bad")


# ---- команды страницы ---------------------------------------------------
def test_commands_reach_window(qapp, web):  # noqa: ANN001
    win, bridge, _page = web
    calls: list[str] = []
    win._load_click = lambda: calls.append("load")  # noqa: SLF001
    win._ping_click = lambda: calls.append("ping")  # noqa: SLF001
    win._open_log = lambda: calls.append("log")  # noqa: SLF001
    win._connect_click = lambda: calls.append("connect")  # noqa: SLF001
    win._disconnect_click = lambda: calls.append("disconnect")  # noqa: SLF001
    win._testcfg_click = lambda: calls.append("testcfg")  # noqa: SLF001
    win._zapret_click = lambda: calls.append("dpi")  # noqa: SLF001
    win._zapret_pick = lambda: calls.append("dpi-auto")  # noqa: SLF001

    bridge.loadSub()
    bridge.pingServers()
    bridge.openLog()
    bridge.connectVpn()
    bridge.disconnectVpn()
    bridge.testConfig()
    bridge.toggleDpi()
    bridge.autoDpi()
    qapp.processEvents()
    assert calls == [
        "load",
        "ping",
        "log",
        "connect",
        "disconnect",
        "testcfg",
        "dpi",
        "dpi-auto",
    ]


def test_select_and_text_commands(qapp, web):  # noqa: ANN001
    win, bridge, _page = web
    win.nodes = [
        {"display": "A", "proto": "vless", "tag": "a"},
        {"display": "B", "proto": "vless", "tag": "b"},
    ]
    win.list_servers.set_nodes(win.nodes)
    bridge.selectServer(1)
    bridge.setSubUrl("https://sub.example/x")
    bridge.setProcText("game.exe")
    bridge.selectExcl(0)
    qapp.processEvents()
    assert win.list_servers.selected_index() == 1
    assert win.field_sub.text() == "https://sub.example/x"
    assert win.picker_proc.text() == "game.exe"


def test_poll_pushes_state_once(qapp, web):  # noqa: ANN001
    _win, bridge, page = web
    bridge.poll()
    bridge.poll()
    assert len(page.applied()) == 1  # без изменений повторно не гоним
    _win.lbl_egress.setText("Внешний IP: 1.2.3.4")
    bridge.poll()
    applied = page.applied()
    assert len(applied) == 2
    assert applied[-1]["egress"] == "Внешний IP: 1.2.3.4"


class FakeHost:
    """Окно вместо WebWindow: проверяем маршрутизацию команд страницы."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def showMinimized(self) -> None:  # noqa: N802
        self.calls.append(("minimize",))

    def close_app(self) -> None:
        self.calls.append(("close_app",))

    def begin_drag(self, x: int, y: int) -> None:
        self.calls.append(("dragStart", x, y))

    def drag_to(self, x: int, y: int) -> None:
        self.calls.append(("dragMove", x, y))

    def end_drag(self) -> None:
        self.calls.append(("dragEnd",))

    def on_state_pushed(self) -> None:
        self.calls.append(("state",))


def test_window_commands_reach_host(web):  # noqa: ANN001
    win, bridge, _page = web
    host = FakeHost()
    bridge.host = host
    bridge.minimize()
    bridge.closeWin()
    bridge.dragStart(100, 200)
    bridge.dragMove(110, 260)
    bridge.dragEnd()
    bridge.poll()
    assert host.calls == [
        ("minimize",),
        ("close_app",),
        ("dragStart", 100, 200),
        ("dragMove", 110, 260),
        ("dragEnd",),
        ("state",),
    ]


def test_window_commands_without_host_are_noop(web):  # noqa: ANN001
    """Без окна-хозяина команды страницы не должны падать."""
    _win, bridge, _page = web
    bridge.minimize()
    bridge.closeWin()
    bridge.dragStart(1, 1)
    bridge.dragMove(2, 2)
    bridge.dragEnd()


def test_bridge_hooks_dialogs_once(web):  # noqa: ANN001
    """Подмена диалогов ставится один раз (повторный Bridge не ломает окно)."""
    win, bridge, _page = web
    first_msg = win._msg
    second = Bridge(win)
    assert win._msg is not first_msg  # второй мост переподписал
    second._install_hooks()
    win._msg("через второй мост")
    win.close()
    del second


# ---- модальные окна -----------------------------------------------------
def test_msg_goes_to_web_modal(web):  # noqa: ANN001
    win, bridge, page = web
    win._msg("Сначала загрузи подписку.")
    payloads = page.modal_payloads()
    assert payloads and payloads[-1]["text"] == "Сначала загрузи подписку."
    assert payloads[-1]["confirm"] is False


def test_msg_error_icon_carried(web):  # noqa: ANN001
    win, bridge, page = web
    win._msg("Ошибка загрузки", "Заголовок", icon="error")
    payload = page.modal_payloads()[-1]
    assert payload["title"] == "Заголовок"
    assert payload["icon"] == "error"


def test_confirm_without_page_is_cancel(web):  # noqa: ANN001
    """Без страницы подтверждение не должно висеть (тесты/headless)."""
    win, bridge, _page = web
    bridge.page = None
    assert win._msg_confirm("Продолжить?", "Тема") is False


def test_confirm_answers_from_page(qapp, web):  # noqa: ANN001
    """Ответ страницы разблокирует подтверждение (False/True)."""
    from PySide6.QtCore import QTimer

    win, bridge, page = web

    def ask(ok: bool) -> bool:
        # ответ приходит из «страницы», пока окно подтверждения открыто
        def reply() -> None:
            bridge.answerModal(page.modal_payloads()[-1]["id"], ok)

        QTimer.singleShot(0, reply)
        return bool(win._msg_confirm("Продолжить?", "Тема"))

    assert ask(False) is False
    assert ask(True) is True