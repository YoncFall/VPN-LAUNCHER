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
# WebWindow в тестах должен рисоваться без GPU (offscreen иначе теряет контекст)
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-gpu-compositing --no-sandbox",
)

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


def test_page_keeps_mockup_glow():
    """Неоновая кайма из макета жива, а клик по прозрачному проходит сквозь.

    13.10 (просьба): тень карточки 0 18px 55px рисовала по полям
    полупрозрачную подложку - окно ловило клики. Она отключена (только
    тень, кайма ::before с blur 9px осталась).
    """
    from vpn_launcher.ui.web.window import assets_dir

    html = (assets_dir() / "app.html").read_text(encoding="utf-8")
    assert "#window { box-shadow: none !important; }" in html
    assert "#window::before" in html  # неоновая кайма на месте
    assert "filter: blur(9px)" in html
    assert "display: none !important" not in html


def test_window_margin_is_click_through(qapp):
    """Поля вокруг карточки прозрачны (alpha=0) -> клик идёт на рабочий стол.

    Карточка при этом непрозрачна - по ней клики ловятся как раньше.
    """
    import time

    from vpn_launcher.ui.window import MainWindow
    from vpn_launcher.ui.web.window import PAGE_H, PAGE_W, WebWindow

    win = MainWindow()
    view = WebWindow(win)
    view.show()
    try:
        img = None
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.2)
            img = view.grab().toImage()
            # ждём, пока страница отрисуется (карточка станет плотной)
            if img.pixelColor(PAGE_W // 2, PAGE_H // 2).alpha() > 200:
                break
        assert img is not None and img.width() == PAGE_W
        for name, x, y in (
            ("край окна", 6, 6),
            ("поле сверху", PAGE_W // 2, 18),
            ("поле слева", 18, PAGE_H // 2),
            # справа берём выше плашки DPI (она висит на середине правого поля
            # и обязана ловить свои клики, а её полупрозрачная тень - нет)
            ("поле справа", PAGE_W - 18, PAGE_H // 4),
            ("поле снизу", PAGE_W // 2, PAGE_H - 18),
        ):
            a = img.pixelColor(x, y).alpha()
            assert a == 0, f"{name} ({x},{y}): alpha={a}, клик не пройдёт сквозь"
        assert img.pixelColor(PAGE_W // 2, PAGE_H // 2).alpha() == 255
    finally:
        win.btn_zapret.close()
        win.close()
        view.close()
        qapp.processEvents()


def test_elevation_hands_over_visible_window_pos(qapp, monkeypatch):
    """Перезапуск с правами (UAC) получает позицию ВИДИМОГО окна.

    Регресс 13.10: с HTML-интерфейсом MainWindow скрыт и остаётся в (0,0),
    а в --window-pos уходила именно его координата - после включения обхода
    DPI окно уезжало в левый верхний угол вместо того, чтобы встать на
    старое место.
    """
    from vpn_launcher.ui.window import MainWindow
    from vpn_launcher.ui.web.window import WebWindow

    monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: False)
    relaunches: list[list[str]] = []
    monkeypatch.setattr(
        "vpn_launcher.ui.window.relaunch_elevated",
        lambda args: relaunches.append(list(args)),
    )
    monkeypatch.setattr(
        "vpn_launcher.ui.window.create_window_shown_event", lambda: 111
    )
    monkeypatch.setattr(
        "vpn_launcher.ui.window.wait_window_shown",
        lambda h, timeout_ms=0, pump=None: True,
    )
    monkeypatch.setattr(
        "vpn_launcher.ui.window.release_window_shown_event", lambda h: None
    )
    win = MainWindow()
    view = WebWindow(win)
    win.web_window = view
    view.move(123, 210)
    try:
        win._zapret_click()  # прав нет -> _zapret_elevate -> перезапуск
        assert relaunches and relaunches[0][0] == "--autozapret"
        assert relaunches[0][1] == "--window-pos=123,210", relaunches[0]
    finally:
        win.btn_zapret.close()
        win.close()
        view.close()
        qapp.processEvents()


def test_handoff_signal_waits_for_page_paint(qapp):
    """Сигнал «окно видно» уходит после отрисовки страницы, а не сразу.

    Иначе старое окно закрывается раньше, чем новое что-то показывает:
    окно гаснет и появляется снова (жалоба 13.10 «изчезает и потом
    появляется»).
    """
    import time

    from vpn_launcher.ui.window import MainWindow
    from vpn_launcher.ui.web.window import PAGE_H, PAGE_W, WebWindow

    win = MainWindow()
    view = WebWindow(win)
    fired: list[bool] = []  # была ли карточка уже плотной в момент сигнала

    def on_visible() -> None:
        img = view.grab().toImage()
        fired.append(img.pixelColor(PAGE_W // 2, PAGE_H // 2).alpha() > 200)

    view.show()
    view.signal_when_visible(on_visible)
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline and not fired:
        qapp.processEvents()
        time.sleep(0.05)
    try:
        assert fired == [True], "сигнал ушёл до отрисовки страницы"
        # повторный сигнал не шлём (старое окно уже разбужено)
        view._fire_handoff()
        assert len(fired) == 1
    finally:
        win.btn_zapret.close()
        win.close()
        view.close()
        qapp.processEvents()


def test_handoff_signal_fires_without_paint(qapp, monkeypatch):
    """Страховка: сигнал уходит даже если страница не отрисовалась.

    Без неё старое окно висело бы до своего таймаута (15с).
    """
    import time

    from vpn_launcher.ui.web import window as web_window
    from vpn_launcher.ui.window import MainWindow

    monkeypatch.setattr(web_window, "HANDOFF_FALLBACK_MS", 300)
    monkeypatch.setattr(  # опрос отрисовки отключаем - его не будет
        web_window.WebWindow, "_poll_paint", lambda self: None
    )
    win = MainWindow()
    view = web_window.WebWindow(win)  # не показываем: отрисовки не будет
    fired: list[str] = []
    view.signal_when_visible(lambda: fired.append("go"))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not fired:
        qapp.processEvents()
        time.sleep(0.05)
    try:
        assert fired == ["go"]
    finally:
        win.btn_zapret.close()
        win.close()
        view.close()
        qapp.processEvents()


def test_app_mode_values_match_backend():
    """Значения переключателей = язык приложения (core/config.py).

    Регресс 13.10: макет слал data-exclusion-mode="only", такого режима у
    приложения нет - при старте не горел ни один переключатель, а клик по
    «Только выбранные» уводил выбор на «Всё, кроме списка».
    """
    from vpn_launcher.core.config import APP_MODES
    from vpn_launcher.ui.web.window import assets_dir

    html = (assets_dir() / "app.html").read_text(encoding="utf-8")
    excl = set(re.findall(r'data-exclusion-mode="([^"]+)"', html))
    assert excl == set(APP_MODES), f"переключатели: {sorted(excl)}"
    conn = set(re.findall(r'data-connection-mode="([^"]+)"', html))
    assert conn == {"tun", "proxy"}, f"режимы подключения: {sorted(conn)}"


def test_render_syncs_radio_dot():
    """Точка радио-кнопки едет вместе с подсветкой сегмента (13.10)."""
    from vpn_launcher.ui.web.window import assets_dir

    js = (assets_dir() / "app.js").read_text(encoding="utf-8")
    assert "dot.checked = on" in js
    assert "renderModes(s) {" in js


def test_dpi_lamp_mapping_in_page():
    """Лампа DPI загорается: мост шлёт ready/connecting, страница ждёт их же.

    Регресс 13.10: страница ждала значение "on", которого мост не присылает,
    и лампа обхода не подсвечивалась (13.10).
    """
    from vpn_launcher.ui.web.window import assets_dir

    js = (assets_dir() / "app.js").read_text(encoding="utf-8")
    assert '"ready" ? "dpi-active"' in js
    assert "dpiLamp === \"on\"" not in js


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
    # connect/dpi обязаны быть отложены (см. test_confirm_slots_defer...):
    # пока слот страницы не вернулся, движок не доставляет ответ модалки и
    # окно «зависает» - поэтому догоняют в конец очереди после событий
    for _ in range(3):
        qapp.processEvents()
    assert calls == [
        "load",
        "ping",
        "log",
        "disconnect",
        "testcfg",
        "dpi-auto",
        "connect",
        "dpi",
    ]


def test_confirm_slots_defer_to_keep_page_channel_free(qapp, web):  # noqa: ANN001
    """Слот с подтверждением обязан вернуться странице ДО показа модалки.

    15.10 (баг «нажал ОК - зависло, закрыть нельзя»): QtWebEngine, пока
    занят вызовом из страницы, не доставляет обратно НИЧЕГО - answerModal
    из вложенного цикла подтверждения не приходит никогда (журнал юзера:
    обе попытки заканчивались только 180-секундной страховкой «отменён»).
    _connect_click и _zapret_click поэтому запускаются через
    QTimer.singleShot(0): слот страницы отрабатывает сразу, а диалог идёт
    из главного цикла, где ответ приходит за миллисекунды.
    """
    win, bridge, _page = web
    seen: list[str] = []
    win._connect_click = lambda: seen.append("connect")  # noqa: SLF001
    win._zapret_click = lambda: seen.append("dpi")  # noqa: SLF001

    bridge.connectVpn()
    bridge.toggleDpi()
    assert seen == []  # в тот же стек вызова страницы не заходим
    for _ in range(3):
        qapp.processEvents()
    assert seen == ["connect", "dpi"]


def test_modal_has_no_dark_backdrop():
    """15.10 (просьба): уведомление - без затемняющей подложки.

    «Нам важно просто уведомление увидеть пользователю» - карточка
    уведомления сама по себе заметна; слой при этом остаётся
    перехватчиком кликов, пока окно открыто.
    """
    from vpn_launcher.ui.web.window import assets_dir

    html = (assets_dir() / "app.html").read_text(encoding="utf-8")
    block = html.split("#modalLayer {", 1)[1].split("}", 1)[0]
    assert "background: transparent" in block
    assert "rgba(" not in block


def test_page_reports_js_errors():
    """Ошибки JS страницы уходят в журнал (иначе они не видны вообще).

    15.10: коллектора не существовало - window.__errs читался при
    подключении, но никто его не заполнял.
    """
    from vpn_launcher.ui.web.window import assets_dir

    js = (assets_dir() / "app.js").read_text(encoding="utf-8")
    assert 'addEventListener("error"' in js
    assert "unhandledrejection" in js
    assert "flushErrs()" in js
    assert "pageError" in js


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