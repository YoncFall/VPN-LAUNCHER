# -*- coding: utf-8 -*-
"""Этап 4: offscreen-тесты виджетов (NeonList, NeonScrollBar, GamePicker, окно).

QT_QPA_PLATFORM=offscreen - рендер без экрана; grab() прогоняет paintEvent,
ловя ошибки отрисовки. Поведение сверяется с theme.ps1 (Set-GameListDraw,
GamePicker/GameDropPopup).

ВАЖНО: у тестов-методов обязан быть self - иначе pytest принимает первый
аргумент за экземпляр, фикстура qapp не вызывается, и QWidget без
QApplication роняет Qt (qFatal -> exit -1073740791).
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vpn_launcher.ui.widgets.led import Led  # noqa: E402
from vpn_launcher.ui.widgets.neon_list import NeonList  # noqa: E402
from vpn_launcher.ui.widgets.picker import GamePicker  # noqa: E402
from vpn_launcher.ui.widgets.scroll_bar import NeonScrollBar  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_side_effects(monkeypatch, tmp_path):
    """Этап 5: state.json - во временном каталоге, реестр прокси не трогаем.

    MainWindow() восстанавливает состояние и при close() трогает прокси - в
    тестах эти побочные эффекты на машине не нужны.
    """
    from vpn_launcher.core import state as state_mod

    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("vpn_launcher.ui.window.set_proxy_off", lambda: None)
    monkeypatch.setattr("vpn_launcher.ui.window.set_proxy_on", lambda: None)


def _nodes(n: int = 5) -> list[dict]:
    protos = ["vless", "vmess", "trojan", "shadowsocks", "hysteria2", "tuic"]
    return [
        {"display": f"srv{i + 1}", "proto": protos[i % len(protos)], "tag": f"tag{i + 1}"}
        for i in range(n)
    ]


# ---- NeonList -------------------------------------------------------------


class TestNeonList:
    def test_set_nodes_fills_rows(self, qapp):
        lst = NeonList(ping=True)
        lst.resize(550, 172)
        lst.set_nodes(_nodes(5))
        assert lst.item_texts() == ["srv1", "srv2", "srv3", "srv4", "srv5"]
        assert lst.selected_index() == -1

    def test_set_items_text_mode(self, qapp):
        lst = NeonList(ping=False)
        lst.set_items(["steam.exe", "Discord.exe"])
        assert lst.item_texts() == ["steam.exe", "Discord.exe"]

    def test_single_selection_cycle(self, qapp):
        lst = NeonList(ping=True)
        lst.set_nodes(_nodes(3))
        lst.select_index(1)
        assert lst.selected_index() == 1
        lst.select_index(2)  # одиночное: смена выделения
        assert lst.selected_index() == 2
        lst.select_index(99)  # вне диапазона - пусто
        assert lst.selected_index() == -1

    def test_pings_lifecycle(self, qapp):
        lst = NeonList(ping=True)
        lst.set_nodes(_nodes(3))
        lst.set_ping("tag2", 64)
        assert lst.pings == {"tag2": 64}
        lst.set_pings({"tag1": 120, "tag3": -1})
        assert lst.pings == {"tag1": 120, "tag3": -1}
        lst.clear_pings()
        assert lst.pings == {}

    def test_set_nodes_resets_pings(self, qapp):
        lst = NeonList(ping=True)
        lst.set_nodes(_nodes(2))
        lst.set_ping("tag1", 50)
        lst.set_nodes(_nodes(2))
        assert lst.pings == {}

    def test_render_selected_row(self, qapp):
        """grab() гоняет отрисовку плашки, полоски, колонок и пингов."""
        lst = NeonList(ping=True)
        lst.resize(550, 172)
        lst.set_nodes(_nodes(6))
        lst.set_ping("tag1", 64)
        lst.set_ping("tag2", -2)
        lst.set_ping("tag3", -1)
        lst.set_ping("tag4", 300)
        lst.select_index(0)
        pm = lst.grab()
        assert not pm.isNull() and pm.width() == 550

    def test_render_text_rows(self, qapp):
        lst = NeonList(ping=False)
        lst.resize(254, 78)
        lst.set_items(["steam.exe", "Discord.exe", "chrome.exe"])
        lst.select_index(1)
        assert not lst.grab().isNull()


# ---- NeonScrollBar ---------------------------------------------------------


class TestNeonScrollBar:
    def test_paint_with_scroll_range(self, qapp):
        sb = NeonScrollBar()
        sb.resize(14, 172)
        sb.setRange(0, 1000)
        sb.setPageStep(200)
        sb.setValue(300)
        assert not sb.grab().isNull()

    def test_size_hint_width(self, qapp):
        sb = NeonScrollBar()
        assert sb.sizeHint().width() == NeonScrollBar.WIDTH


# ---- GamePicker ------------------------------------------------------------


class TestGamePicker:
    def test_text_roundtrip(self, qapp):
        p = GamePicker("ph")
        assert p.text() == ""
        p.setText("steam.exe")
        assert p.text() == "steam.exe"

    def test_open_requires_items(self, qapp):
        p = GamePicker("ph")
        p.open_drop()
        assert not p.drop_open()
        p.set_items(["a.exe", "b.exe"])
        p.open_drop()
        assert p.drop_open()
        assert p._pop.item_count() == 2

    def test_filter_prefix_case_insensitive(self, qapp):
        p = GamePicker("ph")
        p.set_items(["Steam.exe", "Discord.exe", "notepad.exe"])
        p.open_drop()
        p.setText("st")  # StartsWith, lowerInvariant (theme.ps1:393-404)
        assert p._pop.item_count() == 1
        p.setText("")  # пусто - все пункты
        assert p._pop.item_count() == 3
        p.setText("zzz")  # совпадений нет - закрыть
        assert not p.drop_open()

    def test_commit_sets_text_and_closes(self, qapp):
        p = GamePicker("ph")
        p.set_items(["Steam.exe", "Discord.exe"])
        p.open_drop()
        p.commit_from_popup(1)
        assert p.text() == "Discord.exe"
        assert not p.drop_open()
        p.commit_from_popup(5)  # вне диапазона - no-op
        assert p.text() == "Discord.exe"

    def test_popup_height_and_width(self, qapp):
        """h = min(8,n)*28+8; под полем (y=bottom+2), ширина = ширина пикера."""
        p = GamePicker("ph")
        p.resize(286, 30)
        p.set_items([f"proc{i}.exe" for i in range(12)])
        p.open_drop()
        assert p._pop.height() == 8 * 28 + 8
        assert p._pop.width() == 286
        assert p._pop.y() == p.height() + 2  # под полем (при наличии места)

    def test_render_field(self, qapp):
        p = GamePicker("placeholder text")
        p.resize(286, 30)
        p.set_items(["steam.exe"])
        assert not p.grab().isNull()
        p.open_drop()
        assert not p._pop.grab().isNull()
        p.close_drop()

    def test_typing_with_open_popup_filters_live(self, qapp):
        """Набор при открытом списке фильтрует его живо (theme.ps1:300).

        Qt::Popup перехватывает клавиши у поля - попап обязан переслать их
        в поле, как в 1.0.6, где фокус всегда в TextBox.
        """
        p = GamePicker("ph")
        p.resize(286, 30)
        p.set_items(["adb.exe", "Ascon.CSC.exe", "conhost.exe", "csrss.exe"])
        p.open_drop()
        assert p.drop_open()
        assert p._pop.item_count() == 4
        # клавиши при открытом попапе уходят в него (активное окно)
        QTest.keyClicks(p._pop, "cs")
        assert p.text() == "cs"
        assert p._pop.item_count() == 1  # остались только совпадения
        assert p._pop.list.model().item(0).text() == "csrss.exe"
        assert p.drop_open()  # есть совпадения - список остаётся открытым

    def test_no_match_closes_and_returns_focus(self, qapp, monkeypatch):
        """Нет совпадений - список закрывается, фокус возвращается в поле."""
        p = GamePicker("ph")
        p.resize(286, 30)
        p.show()
        p.set_items(["adb.exe", "csrss.exe"])
        p.open_drop()
        # offscreen не активирует окна (hasFocus там всегда False) -
        # фиксируем вызов setFocus в close_drop программно
        calls = []
        monkeypatch.setattr(p._edit, "setFocus", lambda *a, **k: calls.append(1))
        QTest.keyClicks(p._pop, "z")
        assert p.text() == "z"
        assert not p.drop_open()  # совпадений нет - закрыть (theme.ps1:401)
        assert calls  # close_drop вернул фокус полю (набор продолжается)
        QTest.keyClicks(p._edit, "z")  # печать после закрытия идёт в поле
        assert p.text() == "zz"

    def test_popup_escape_and_down_close(self, qapp):
        """Escape/Down при открытом списке - закрыть (theme.ps1:304-305)."""
        p = GamePicker("ph")
        p.resize(286, 30)
        p.set_items(["a.exe", "b.exe"])
        p.open_drop()
        QTest.keyClick(p._pop, Qt.Key.Key_Escape)
        assert not p.drop_open()
        p.open_drop()
        QTest.keyClick(p._pop, Qt.Key.Key_Down)
        assert not p.drop_open()


# ---- Led (анимация, по просьбе - см. README «Отклонения») -------------------


def _spin(qapp: QApplication, seconds: float) -> None:
    """Крутим цикл событий, пока таймер анимации тикает."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)


class TestLed:
    def test_light_up_ramps_then_pulses(self, qapp):
        led = Led(10, "off")
        led.light_up("ok", pulse=True)
        _spin(qapp, 0.15)  # середина fade-in: плавно, не резко
        mid = led._brightness
        assert 0.0 < mid < 1.0, f"нет плавного разгона: {mid}"
        _spin(qapp, 0.6)  # пик достигнут, пошла пульсация «пик-пик»
        samples = []
        end = time.monotonic() + 1.4  # полный цикл дыхания (1.2с)
        while time.monotonic() < end:
            qapp.processEvents()
            samples.append(led._brightness)
            time.sleep(0.02)
        assert led.state() == "ok"
        assert max(samples) > 0.9, "нет пика"
        assert min(samples) < 0.6, "нет спада в пульсации"
        led._timer.stop()

    def test_light_off_fades_to_dark(self, qapp):
        led = Led(10, "ok")
        led.light_up("ok", pulse=True)
        _spin(qapp, 0.7)
        led.light_off()
        _spin(qapp, 0.8)  # fade-out 0.6с
        assert led._brightness == 0.0
        assert led.state() == "off"
        assert not led._timer.isActive()
        assert not led.is_lit()

    def test_set_state_stays_instant(self, qapp):
        """set_state - мгновенный (как в 1.0.6), без таймера."""
        led = Led(10, "off")
        led.set_state("busy")
        assert led.state() == "busy"
        assert not led._timer.isActive()
        assert not led.grab().isNull()


# ---- главное окно ----------------------------------------------------------


class TestMainWindowSmoke:
    def test_window_builds_and_paints(self, qapp):
        from vpn_launcher.ui.window import MainWindow

        win = MainWindow()
        assert win.list_servers.ping is True
        assert win.list_excl.ping is False
        assert win.picker_proc is not None
        # списки лежат внутри рамок с инсетом 3 (New-GameListBox)
        assert win.list_servers.geometry().topLeft().x() == 3
        assert win.list_excl.geometry().topLeft().x() == 3
        pm = win.grab()
        assert not pm.isNull() and pm.width() == 620
        win.close()
