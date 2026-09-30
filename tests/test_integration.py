# -*- coding: utf-8 -*-
"""Этап 5: оркестрация окна - порт обработчиков VPN.ps1 (offscreen).

Сеть: только локальная (TCP-сервер для пинга, файл подписки вместо HTTP);
диалоги подменяются записью (win._msg/_msg_confirm), state.json - во
временном каталоге, реестр прокси заглушен. Сверяем тексты статусов и
порядок операций с VPN.ps1 (строки указаны у тестов).

ВАЖНО: у тестов-методов обязан быть self (см. test_ui_widgets.py).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vpn_launcher.core import state as state_mod  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SUB_FILE = FIXTURES / "subscription.txt"


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """state.json - во временном каталоге; реестр прокси не трогаем."""
    monkeypatch.setattr(state_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("vpn_launcher.ui.window.set_proxy_off", lambda: None)
    monkeypatch.setattr("vpn_launcher.ui.window.set_proxy_on", lambda: None)


def _await(qapp: QApplication, pred, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_window_pos_arg_parses_and_fails_safe():
    """--window-pos из передачи окна: битый аргумент -> None (центр экрана)."""
    from vpn_launcher.ui.window import _window_pos_arg

    assert _window_pos_arg(["app", "--window-pos=10,20", "--autoconnect"]) == (10, 20)
    assert _window_pos_arg(["app", "--window-pos=bad"]) is None
    assert _window_pos_arg(["app", "--autoconnect"]) is None


@pytest.fixture
def win(qapp):
    from vpn_launcher.ui.window import MainWindow

    w = MainWindow()
    w._msgs: list = []
    w._confirms: list = []
    w._msg = lambda text, title="", icon="": w._msgs.append((text, title, icon))
    w._msg_confirm = lambda text, title="": (
        w._confirms.append((text, title)) or True
    )
    yield w
    w.tick.stop()
    w.close()


# ---- исключения (VPN.ps1:226-302) -----------------------------------------


class TestExclusions:
    def test_add_appends_exe_and_saves(self, qapp, win):
        """Add-Excl (252-277): авто-.exe, пустой инпут выводится, state живёт."""
        win.picker_proc.setText("steam_thing")
        win._excl_add()
        assert win.list_excl.item_texts() == ["steam_thing.exe"]
        assert win.picker_proc.text() == ""
        assert win.lbl_status.text() == "Добавлено исключение: steam_thing.exe"
        assert win.state["appList"] == ["steam_thing.exe"]
        assert state_mod.load_state()["appList"] == ["steam_thing.exe"]
        assert win._msgs == []

    def test_add_duplicate_warns(self, qapp, win):
        """Items.Contains - регистрозависим (259)."""
        win.list_excl.add_item("a.exe")
        win.picker_proc.setText("a.exe")
        win._excl_add()
        assert win.list_excl.item_texts() == ["a.exe"]
        assert win.lbl_status.text() == "a.exe уже есть в списке"
        # другой регистр - Contains не видит дубль (баг 1.0.6, сохранён)
        win.picker_proc.setText("A.exe")
        win._excl_add()
        assert win.list_excl.item_texts() == ["a.exe", "A.exe"]

    def test_add_game_safe_case_insensitive(self, qapp, win):
        """GAME_SAFE `-contains` - регистронезависим (263)."""
        win.picker_proc.setText("StEaM.EXE")
        win._excl_add()
        assert win.list_excl.item_texts() == []
        assert win.lbl_status.text() == "StEaM.EXE и так исключён автоматически"

    def test_add_bad_name(self, qapp, win):
        """'^[\\w\\-. ]+\\.exe$' не проходит (258)."""
        win.picker_proc.setText("bad!name.exe")
        win._excl_add()
        assert win.list_excl.item_texts() == []
        assert win.lbl_status.text() == "Не похоже на имя процесса (.exe)"

    def test_add_empty_is_noop(self, qapp, win):
        win.picker_proc.setText("   ")
        win._excl_add()
        assert win.list_excl.item_texts() == []
        assert win.lbl_status.text() == "Готов"

    def test_picker_enter_adds(self, qapp, win):
        """Enter в поле = добавить (280-285)."""
        win.picker_proc.setText("game")
        win.picker_proc.submitted.emit()
        assert win.list_excl.item_texts() == ["game.exe"]

    def test_del_and_clr(self, qapp, win):
        """btnExclDel (286-290) / btnExclClr (291-297)."""
        win.list_excl.set_items(["a.exe", "b.exe"])
        win.list_excl.select_index(1)
        win._excl_del()
        assert win.list_excl.item_texts() == ["a.exe"]
        assert win.state["appList"] == ["a.exe"]
        win._excl_del()  # выделения больше нет - no-op
        assert win.list_excl.item_texts() == ["a.exe"]
        win._excl_clr()
        assert win.list_excl.item_texts() == []
        assert win.lbl_status.text() == "Список исключений очищен"
        assert state_mod.load_state()["appList"] == []


# ---- переключатель режима списка (новое, 30.09.2026) ------------------------


class TestAppModeSwitch:
    """«Исключения» ↔ «Только выбранные»: один список, две семантики.

    Дефолт обязан остаться режимом exclude (паритет с PS 1.0.6), включать
    include - только осознанным кликом; режим живёт отдельно от состава
    списка (state['appMode']), поэтому переключение не переписывает appList.
    """

    def test_default_is_exclude_with_ps_text(self, qapp, win):
        assert win._app_mode() == "exclude"
        assert win.radio_excl.checked() and not win.radio_vpnonly.checked()
        assert win.lbl_appsec.text() == "ИСКЛЮЧЕНИЯ"
        assert "Список процессов обновляется" in win.lbl_apps_hint.text()

    def test_switch_persists_and_rewrites_labels(self, qapp, win):
        win.radio_vpnonly.toggled.emit()
        assert win._app_mode() == "include"
        assert win.radio_vpnonly.checked() and not win.radio_excl.checked()
        assert win.lbl_appsec.text() == "ЧЕРЕЗ VPN"
        assert "Только эти процессы" in win.lbl_apps_hint.text()
        assert win.state["appMode"] == "include"
        assert state_mod.load_state()["appMode"] == "include"
        # состав списка при переключении не трогаем
        win.list_excl.add_item("mygame.exe")
        win.radio_excl.toggled.emit()
        assert win._app_mode() == "exclude"
        assert win.lbl_appsec.text() == "ИСКЛЮЧЕНИЯ"
        assert win.state["appList"] == ["mygame.exe"]
        assert state_mod.load_state()["appMode"] == "exclude"

    def test_exclude_still_rejects_game_safe(self, qapp, win):
        """Поведение 1.0.6 не едет: в exclude игры исключены автоматически."""
        win.picker_proc.setText("steam")
        win._excl_add()
        assert win.list_excl.item_texts() == []
        assert win.lbl_status.text() == "steam.exe и так исключён автоматически"

    def test_include_allows_game_safe_names(self, qapp, win):
        """В include базовый список игр не участвует - запрет был бы ложью:
        пользователь вправе пустить Steam через VPN осознанно."""
        win.radio_vpnonly.toggled.emit()
        win.picker_proc.setText("StEaM.EXE")
        win._excl_add()
        assert win.list_excl.item_texts() == ["StEaM.EXE"]
        assert win.lbl_status.text() == "Добавлено в список через VPN: StEaM.EXE"
        assert state_mod.load_state()["appMode"] == "include"

    def test_include_clear_message_differs(self, qapp, win):
        win.radio_vpnonly.toggled.emit()
        win.list_excl.add_item("a.exe")
        win._excl_clr()
        assert win.list_excl.item_texts() == []
        assert win.lbl_status.text() == "Список процессов через VPN очищен"

    def test_restore_include_from_state(self, qapp, tmp_path):
        state_mod.save_state(
            {
                "subUrl": "https://sub.example/x",
                "mode": "tun",
                "selected": "",
                "appList": ["x.exe"],
                "appMode": "include",
                "lastNodes": [],
                "autoUrlTest": True,
            }
        )
        from vpn_launcher.ui.window import MainWindow

        w = MainWindow()
        try:
            assert w._app_mode() == "include"
            assert w.lbl_appsec.text() == "ЧЕРЕЗ VPN"
            assert w.list_excl.item_texts() == ["x.exe"]
        finally:
            w.close()

    def test_restore_state_without_app_mode_is_exclude(self, qapp, tmp_path):
        """Старый state.json без поля (формат PS 1.0.6) читается как раньше."""
        state_mod.save_state(
            {
                "subUrl": "",
                "mode": "tun",
                "selected": "",
                "appList": ["x.exe"],
                "lastNodes": [],
                "autoUrlTest": True,
            }
        )
        from vpn_launcher.ui.window import MainWindow

        w = MainWindow()
        try:
            assert w._app_mode() == "exclude"
            assert w.lbl_appsec.text() == "ИСКЛЮЧЕНИЯ"
            assert w.list_excl.item_texts() == ["x.exe"]
        finally:
            w.close()

    def test_empty_include_list_stops_connect_when_declined(self, qapp, win):
        """Пустой include даёт route.final=direct: туннель поднимется и не
        захватит ничего. Спрашиваем до UAC, а не после."""
        win.radio_vpnonly.toggled.emit()
        confirms: list = []
        win._msg_confirm = lambda text, title="": (
            confirms.append((text, title)) or False
        )
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")
        win._connect_click()
        assert len(confirms) == 1 and "Список пуст" in confirms[0][0]
        assert win.lbl_status.text() == "Отменено: добавь процессы в список"
        assert win.btn_connect.isEnabled()

    def test_connect_passes_app_mode_to_config(self, qapp, win, monkeypatch):
        """Режим обязан дойти до сборки конфига, а не остаться в UI."""

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                pass

        seen: list = []

        def fake_build(nodes, sel, mode, apps, *a, **k):
            seen.append({"mode": mode, "apps": apps, "app_mode": k.get("app_mode")})
            return "cfg.json"

        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: True)
        monkeypatch.setattr(
            "vpn_launcher.ui.window.new_sing_box_config", fake_build
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.test_sing_box_config", lambda p: (True, "")
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: FakeProc()
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.install_kill_switch", lambda addrs: True
        )
        win.radio_vpnonly.toggled.emit()
        win.list_excl.add_item("mygame.exe")
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert seen and seen[0]["app_mode"] == "include"
        assert seen[0]["mode"] == "tun"
        assert seen[0]["apps"] == ["mygame.exe"]
        assert "ПОДКЛЮЧЕНО" in win.lbl_status.text()


# ---- пикер: браузеры в списке всегда (30.09.2026, по просьбе) ---------------


class TestPickerBrowsers:
    """Edge в списке исключений: статические браузеры + поиск по подстроке.

    Fill-ProcCombo (порт 1.0.6) кладёт в пикер только запущенные процессы,
    а фильтр был префиксным: закрытый Edge не появлялся вовсе, а запущенный
    (msedge.exe) не находился по слову «edge» - браузер в исключения было
    не подобрать. Теперь в источнике всегда лежат PICKER_EXTRA_APPS, а
    фильтр ищет по подстроке (picker.py::_filter_popup).
    """

    def test_msedge_always_in_source(self, qapp, win):
        assert "msedge.exe" in win.picker_proc.item_source

    def test_typing_edge_shows_msedge(self, qapp, win):
        win.picker_proc.setText("edge")
        win.picker_proc._filter_popup()
        pop = win.picker_proc._pop
        texts = [
            pop.list.model().item(i).text() for i in range(pop.item_count())
        ]
        assert "msedge.exe" in texts

    def test_browsers_merge_sorted_with_running(self, qapp, win):
        # запущенные не теряются, дубликаты схлопнуты, порядок как в PS Sort
        items = win.picker_proc.item_source
        assert "chrome.exe" in items and "firefox.exe" in items
        assert items == sorted(items, key=str.casefold)
        assert len({i.casefold() for i in items}) == len(items)


# ---- загрузка подписки (VPN.ps1:120-156) -----------------------------------


class TestLoad:
    def test_load_local_file(self, qapp, win):
        win.field_sub.setText(str(SUB_FILE))
        assert win._load_click() is True
        assert _await(qapp, lambda: win._loader is None)
        assert len(win.nodes) == 16
        assert win.lbl_status.text() == "Серверов загружено: 16"
        assert win.list_servers.item_texts() == [
            str(n["display"]) for n in win.nodes
        ]
        assert win.btn_load.isEnabled()
        assert win.state["subUrl"] == str(SUB_FILE)
        assert state_mod.load_state()["subUrl"] == str(SUB_FILE)

    def test_load_empty_url_shows_msg(self, qapp, win):
        assert win._load_click() is False
        assert win._msgs == [("Вставь ссылку на подписку.", "", "")]
        assert win.lbl_status.text() == "Готов"

    def test_load_error(self, qapp, win):
        win.field_sub.setText(str(FIXTURES / "no-such-subscription.txt"))
        assert win._load_click() is True
        assert _await(qapp, lambda: win._loader is None)
        assert win.nodes == []
        assert win.lbl_status.text() == "Ошибка загрузки"
        assert win._msgs and win._msgs[0][1] == "VPN ЛАУНЧЕР BY @YoncFALL"
        assert win._msgs[0][2] == "error"
        assert win.btn_load.isEnabled()


# ---- пинг (VPN.ps1:379-436) ------------------------------------------------


class TestPing:
    @pytest.fixture
    def local_server(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        port = srv.getsockname()[1]
        stop = threading.Event()

        def loop() -> None:
            while not stop.is_set():
                try:
                    c, _ = srv.accept()
                    c.close()
                except OSError:
                    return

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        yield port
        stop.set()
        srv.close()

    def test_ping_local_node(self, qapp, win, local_server):
        node = {
            "display": "local",
            "proto": "vless",
            "tag": "t-local",
            "server": "127.0.0.1",
            "server_port": local_server,
        }
        win.nodes = [node]
        win.list_servers.set_nodes(win.nodes)
        win._ping_click()
        assert win.btn_ping.isEnabled() is False
        # на время проверки нижняя LED горит жёлтым (по просьбе - README)
        assert win.led_status.state() == "warn"
        assert not win.led_status._pulse
        assert _await(qapp, lambda: win._pinger is None)
        assert win.list_servers.pings["t-local"] >= 0
        text = win.lbl_status.text()
        assert text.startswith("Пинг готов: 1 из 1 доступны")
        assert "лучший" in text
        assert win.btn_ping.isEnabled()
        # после проверки жёлтая плавно погасла (офлайн - светиться незачем)
        assert _await(qapp, lambda: not win.led_status.is_lit())
        assert win.led_status.state() == "off"

    def test_ping_restores_green_when_connected(self, qapp, win, local_server):
        """Онлайн: после пинга LED возвращается в зелёную пульсацию."""

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                pass

        win.proc = FakeProc()
        win.led_status.light_up("ok", pulse=True)
        node = {
            "display": "local",
            "proto": "vless",
            "tag": "t-local",
            "server": "127.0.0.1",
            "server_port": local_server,
        }
        win.nodes = [node]
        win.list_servers.set_nodes(win.nodes)
        win._ping_click()
        assert win.led_status.state() == "warn"
        assert _await(qapp, lambda: win._pinger is None)
        assert _await(qapp, lambda: win.led_status.state() == "ok")
        assert win.led_status._pulse
        win.proc = None  # без него teardown не трогает замоканный процесс

    def test_ping_without_nodes(self, qapp, win):
        """382-385: 'Сначала загрузи подписку.'."""
        win._ping_click()
        assert win._msgs == [("Сначала загрузи подписку.", "", "")]

    def test_ping_running_is_reentrant_guard(self, qapp, win):
        """381: пока джоб крутится - повторный клик no-op."""
        win.nodes = [{"display": "x", "proto": "vless", "tag": "x",
                      "server": "192.0.2.1", "server_port": 9}]  # TEST-NET, таймаут
        win.list_servers.set_nodes(win.nodes)
        win._ping_click()
        first = win._pinger
        assert first is not None
        win._ping_click()  # второй клик игнорируется
        assert win._pinger is first
        first.cancel()
        _await(qapp, lambda: win._pinger is None, timeout=10)


# ---- вспомогательные списки (VPN.ps1:313-327) ------------------------------


class TestLists:
    def test_selected_tags_and_app_list(self, qapp, win):
        assert win._selected_tags() == []
        win.nodes = [
            {"display": "a", "proto": "vless", "tag": "tag1"},
            {"display": "b", "proto": "vmess", "tag": "tag2"},
        ]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(1)
        assert win._selected_tags() == ["tag2"]
        win.list_servers.select_index(99)  # вне диапазона
        assert win._selected_tags() == []
        win.list_excl.set_items([" a.exe ", "", "b.exe"])
        assert win._app_list() == ["a.exe", "b.exe"]


# ---- восстановление состояния (VPN.ps1:111, 180-184, 653) ------------------


class TestRestore:
    def test_restore_from_state(self, qapp, tmp_path):
        state_mod.save_state(
            {
                "subUrl": "https://sub.example/x",
                "mode": "proxy",
                "selected": "",
                "appList": ["x.exe"],
                "lastNodes": [],
                "autoUrlTest": True,
            }
        )
        from vpn_launcher.ui.window import MainWindow

        w = MainWindow()
        assert w.field_sub.text() == "https://sub.example/x"
        assert w.radio_proxy.checked() and not w.radio_tun.checked()
        assert w.list_excl.item_texts() == ["x.exe"]
        assert w.lbl_status.text() == "Готов"
        # заголовок с пометкой админа только при повышенных правах (653)
        assert w.windowTitle().startswith("VPN ЛАУНЧЕР BY @YoncFALL")
        w.close()


# ---- подключение (VPN.ps1:458-575) -----------------------------------------


class TestConnect:
    def test_connect_without_nodes(self, qapp, win):
        win._connect_click()
        assert win._msgs == [("Сначала загрузи подписку.", "", "")]

    def test_testcfg_without_nodes(self, qapp, win):
        win._testcfg_click()
        assert win._msgs == [("Сначала загрузи подписку.", "", "")]

    def test_tun_elevation_cancelled(self, qapp, win, monkeypatch):
        """474-523: диалог UAC, отказ -> 'Отменено', state уже сохранён."""
        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: False)
        confirms: list = []
        win._msg_confirm = lambda text, title="": (
            confirms.append((text, title)) or False
        )
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")
        win._connect_click()
        assert len(confirms) == 1 and "TUN" in confirms[0][0]
        assert win.lbl_status.text() == "Отменено - подключение не выполнено"
        assert win.btn_connect.isEnabled()
        saved = state_mod.load_state()
        assert saved["mode"] == "tun"
        assert saved["selected"] == "tag1"
        assert saved["subUrl"] == "https://sub.example/x"

    @pytest.mark.parametrize("shown", [True, False])
    def test_tun_elevation_hands_window_over(self, qapp, win, monkeypatch, shown):
        """Бесшовная передача окна (по просьбе: окно не должно исчезать).

        Порядок: событие -> спавн нового с --window-pos -> ожидание сигнала
        (new window показано) -> освобождение события -> close старого.
        Даже если сигнал не пришёл (shown=False, таймаут), старое окно
        всё равно закрывается - как раньше.
        """
        events: list = []
        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: False)
        win._msg_confirm = lambda text, title="": True
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")
        monkeypatch.setattr(
            "vpn_launcher.ui.window.create_window_shown_event", lambda: 111
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.relaunch_elevated",
            lambda args: events.append(("relaunch", list(args))),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.wait_window_shown",
            lambda h, timeout_ms=0, pump=None: events.append(("wait", h)) or shown,
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.release_window_shown_event",
            lambda h: events.append(("release", h)),
        )
        monkeypatch.setattr(win, "close", lambda: events.append(("close",)))
        win._connect_click()
        assert [e[0] for e in events] == ["relaunch", "wait", "release", "close"]
        rel_args = events[0][1]
        assert rel_args[0] == "--autoconnect"
        assert rel_args[1].startswith("--window-pos=")
        assert win.lbl_status.text() == "Запуск с правами администратора..."

    def test_disconnect(self, qapp, win):
        """btnDisconnect (577-589); лампочки гаснут плавно (по просьбе)."""
        win.btn_connect.setEnabled(False)
        win.btn_disconnect.setEnabled(True)
        win.lbl_egress.setText("Внешний IP: 9.9.9.9")
        win.tick.start()
        win.led_status.light_up("ok", pulse=True)
        win.titlebar.led.light_up("ok", pulse=False)
        win._disconnect_click()
        assert win.lbl_status.text() == "Отключено"
        assert win.lbl_egress.text() == ""
        assert win.btn_connect.isEnabled() and not win.btn_disconnect.isEnabled()
        assert not win.tick.isActive()
        assert win.proc is None
        # плавное гашение обеих лампочек до полного off
        assert _await(
            qapp,
            lambda: not win.led_status.is_lit() and not win.titlebar.led.is_lit(),
        )
        assert win.led_status.state() == "off"
        assert win.titlebar.led.state() == "off"

    def test_connect_success_lights_leds(self, qapp, win, monkeypatch):
        """ПОДКЛЮЧЕНО -> нижняя LED пульсирует, верхняя горит (README-отклонение).

        Движок замокан; внутри _connect_click работает Start-Sleep -Seconds 3,
        поэтому тест занимает ~3с.
        """

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                pass

        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: True)
        monkeypatch.setattr(
            "vpn_launcher.ui.window.new_sing_box_config",
            lambda *a, **k: "cfg.json",
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.test_sing_box_config", lambda p: (True, "")
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: FakeProc()
        )
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert "ПОДКЛЮЧЕНО" in win.lbl_status.text()
        assert win.led_status.state() == "ok"
        assert win.led_status._pulse, "нижняя должна пульсировать"
        assert win.titlebar.led.state() == "ok"
        assert not win.titlebar.led._pulse, "верхняя горит ровно"
        assert win.btn_disconnect.isEnabled()
        assert win.tick.isActive()

    def test_connect_purges_config_and_installs_kill_switch(
        self, qapp, win, monkeypatch, tmp_path
    ):
        """Безопасность 01.10.2026: config.json удаляется сразу после старта
        движка (креды нод не живут на диске), kill switch вешается с адресами
        TUN из этого конфига, «Отключить» снимает фильтры.
        """

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                pass

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "inbounds": [
                        {"type": "tun", "address": ["172.19.0.1/30", "fdfe::1/64"]}
                    ]
                }
            ),
            encoding="utf-8",
        )
        ks_calls: list = []
        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: True)
        monkeypatch.setattr(
            "vpn_launcher.ui.window.new_sing_box_config",
            lambda *a, **k: str(cfg_path),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.test_sing_box_config", lambda p: (True, "")
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: FakeProc()
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.install_kill_switch",
            lambda addrs: ks_calls.append(addrs) or True,  # фильтры повесились
        )
        win.radio_tun.set_checked(True)
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert "ПОДКЛЮЧЕНО" in win.lbl_status.text()
        assert not cfg_path.exists(), "config.json обязан быть удалён после старта"
        assert win._sb_cfg_data is not None, "конфиг должен жить в памяти"
        assert ks_calls == [["172.19.0.1/30", "fdfe::1/64"]], (
            "kill switch получает адреса TUN из конфига"
        )

        # «Отключить» снимает kill switch и чистит памятный конфиг
        removed: list = []
        monkeypatch.setattr(
            "vpn_launcher.ui.window.remove_kill_switch", lambda: removed.append(1)
        )
        stale = Path(win._sb_cfg)
        stale.write_text("{}", encoding="utf-8")  # сирота после автоперезапуска
        win._disconnect_click()
        assert removed == [1]
        assert not stale.exists(), "«Отключить» удаляет config.json-сироту"
        assert win._sb_cfg_data is None

    def test_connect_failure_purges_config(self, qapp, win, monkeypatch, tmp_path):
        """Сбой подключения не оставляет config.json с кредами (S2, 01.10.2026).

        Было: файл уже записан, исключение (check не прошёл/движок умер)
        уходило в except БЕЗ purge - сирота лежала до следующего запуска.
        """
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: True)
        monkeypatch.setattr(
            "vpn_launcher.ui.window.new_sing_box_config",
            lambda *a, **k: str(cfg_path),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.test_sing_box_config", lambda p: (False, "boom")
        )
        win.radio_tun.set_checked(True)
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert "Не удалось подключиться" in win.lbl_status.text()
        assert not cfg_path.exists(), "после сбоя креды не должны остаться на диске"
        assert win._sb_cfg is None and win._sb_cfg_data is None
        assert win._msgs and win._msgs[0][2] == "error"

    def test_connect_failure_after_proxy_on_clears_proxy(
        self, qapp, win, monkeypatch, tmp_path
    ):
        """S2-прокси: сбой ПОСЛЕ включения прокси снимает наш ProxyServer.

        Было: set_proxy_on() отработал, исключение уходило в except без
        set_proxy_off - в HKCU оставался наш прокси на живой порт выключенного
        движка (часть приложений без интернета, пока пользователь не отключит).
        """
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        off: list = []
        monkeypatch.setattr(
            "vpn_launcher.ui.window.set_proxy_off", lambda: off.append(1)
        )
        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: True)
        monkeypatch.setattr(
            "vpn_launcher.ui.window.new_sing_box_config",
            lambda *a, **k: str(cfg_path),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.test_sing_box_config", lambda p: (True, "")
        )

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                pass

        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: FakeProc()
        )

        def boom(*_a, **_k):
            raise RuntimeError("led broken")

        # исключение ПОСЛЕ set_proxy_on: падает свет лампочки (630 в window.py)
        monkeypatch.setattr(win.led_status, "light_up", boom)
        win.radio_tun.set_checked(False)  # _mode() смотрит только на radio_tun
        win.radio_proxy.set_checked(True)
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert "Не удалось подключиться" in win.lbl_status.text()
        assert off == [1], "наш системный прокси обязан сниматься при сбое"

    def test_connect_failure_after_start_stops_engine(
        self, qapp, win, monkeypatch, tmp_path
    ):
        """Сбой подключения не оставляет уже запущенный движок.

        Отклонение от 1.0.6 (VPN.ps1:568-574 там молчит), снято по явному
        решению «фулл-защита» (01.10.2026): раньше except гасил прокси,
        фильтры и конфиг, но sing-box работал до следующего старта - чужой
        TUN/порты и «address already in use» у нового подключения.
        """
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        off: list = []
        stops: list = []
        monkeypatch.setattr(
            "vpn_launcher.ui.window.set_proxy_off", lambda: off.append(1)
        )
        monkeypatch.setattr("vpn_launcher.ui.window.set_proxy_on", lambda: None)
        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: True)
        monkeypatch.setattr(
            "vpn_launcher.ui.window.new_sing_box_config",
            lambda *a, **k: str(cfg_path),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.test_sing_box_config", lambda p: (True, "")
        )

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                pass

        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: FakeProc()
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.stop_sing_box", lambda p: stops.append(p)
        )

        def boom(*_a, **_k):
            raise RuntimeError("led broken")

        # исключение ПОСЛЕ старта движка и включения прокси (падает свет)
        monkeypatch.setattr(win.led_status, "light_up", boom)
        win.radio_tun.set_checked(False)  # _mode() смотрит только на radio_tun
        win.radio_proxy.set_checked(True)
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert "Не удалось подключиться" in win.lbl_status.text()
        assert len(stops) == 1 and win.proc is None, "движок обязан остановиться"
        assert off == [1], "прокси при этом снимается как раньше"
        assert not cfg_path.exists(), "конфиг не остаётся"

    @staticmethod
    def _ks_decline_mocks(monkeypatch, tmp_path):
        """Общая обвязка: TUN-подключение, kill switch не установился."""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(
            json.dumps(
                {"inbounds": [{"type": "tun", "address": ["172.19.0.1/30"]}]}
            ),
            encoding="utf-8",
        )

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def kill(self):
                pass

        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: True)
        monkeypatch.setattr(
            "vpn_launcher.ui.window.new_sing_box_config",
            lambda *a, **k: str(cfg_path),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.test_sing_box_config", lambda p: (True, "")
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: FakeProc()
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.install_kill_switch", lambda addrs: False
        )
        stops: list = []
        removed: list = []
        monkeypatch.setattr(
            "vpn_launcher.ui.window.stop_sing_box", lambda p: stops.append(p)
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.remove_kill_switch", lambda: removed.append(1)
        )
        return cfg_path, stops, removed

    def test_kill_switch_failed_declined_cancels_connect(
        self, qapp, win, monkeypatch, tmp_path
    ):
        """S6: kill switch не установился -> «Нет» = честная отмена.

        Было: TUN подключался молча без защиты (только запись в лог) - тихая
        утечка при обрыве движка. Теперь: отмена, движок остановлен,
        частичные фильтры сняты, статус говорит причину.
        """
        cfg_path, stops, removed = self._ks_decline_mocks(monkeypatch, tmp_path)
        win._msg_confirm = lambda text, title="": (
            win._confirms.append((text, title)) or False
        )
        win.radio_tun.set_checked(True)
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert "ПОДКЛЮЧЕНО" not in win.lbl_status.text()
        assert "Отменено: kill switch не установлен" in win.lbl_status.text()
        assert len(stops) == 1 and win.proc is None, "движок должен остановиться"
        assert removed, "частичные фильтры должны сниматься"
        assert win.btn_connect.isEnabled() and not win.btn_disconnect.isEnabled()
        assert not win.tick.isActive()
        assert win._confirms and "kill switch" in win._confirms[0][0].lower()
        assert not win._msgs, "отмена - не ошибка, лишний диалог не нужен"
        assert not cfg_path.exists(), "config.json должен быть удалён"
        assert win._sb_cfg is None and win._sb_cfg_data is None

    def test_kill_switch_failed_accepted_continues(
        self, qapp, win, monkeypatch, tmp_path
    ):
        """S6: «Да» в том же диалоге = осознанное продолжение без защиты."""
        self._ks_decline_mocks(monkeypatch, tmp_path)
        win._msg_confirm = lambda text, title="": (
            win._confirms.append((text, title)) or True
        )
        win.radio_tun.set_checked(True)
        win.nodes = [{"display": "a", "proto": "vless", "tag": "tag1"}]
        win.list_servers.set_nodes(win.nodes)
        win.list_servers.select_index(0)
        win.field_sub.setText("https://sub.example/x")

        win._connect_click()

        assert "ПОДКЛЮЧЕНО" in win.lbl_status.text()
        assert win._confirms and "БЕЗ защиты" in win._confirms[0][0]

    def test_restart_rewrites_config_from_memory(self, qapp, win, monkeypatch):
        """Автоперезапуск пересоздаёт config.json из памяти и снова удаляет."""

        class AliveProc:
            pid = 777

            def poll(self):
                return None

            def kill(self):
                pass

        rewrites: list = []
        purges: list = []
        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: AliveProc()
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.write_config",
            lambda data, path=None: rewrites.append((data, path)),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.purge_config_file",
            lambda path=None: purges.append(path),
        )
        win._sb_cfg = "c.json"
        win._sb_cfg_data = {"inbounds": [{"type": "tun", "address": ["172.19.0.1/30"]}]}

        assert win._restart_sing_box() is True
        assert rewrites == [
            (win._sb_cfg_data, "c.json")
        ], "конфиг восстановлен из памяти, а не с диска"
        assert purges == ["c.json"], "после успешного рестарта файл снова удалён"
        win._sb_cfg = None
        win._sb_cfg_data = None
        win.proc = None

    def test_failed_restart_purges_config(self, qapp, win, monkeypatch):
        """Сбой автоперезапуска не оставляет config.json с кредами (S2).

        Было: три ранних return False (OSError, падение на старте, «Отключить»
        во время перезапуска) миновали purge - после каждой неудачной попытки
        (до 3) файл лежал на диске.
        """
        purges: list = []
        rewrites: list = []
        monkeypatch.setattr(
            "vpn_launcher.ui.window.write_config",
            lambda data, path=None: rewrites.append(path),
        )
        monkeypatch.setattr(
            "vpn_launcher.ui.window.purge_config_file",
            lambda path=None: purges.append(path),
        )
        monkeypatch.setattr("vpn_launcher.ui.window.time.sleep", lambda _s: None)
        monkeypatch.setattr("vpn_launcher.ui.window.write_log", lambda _m: None)

        class DeadProc:
            pid = 778
            returncode = 1

            def poll(self):
                return 1

            def kill(self):
                pass

        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: DeadProc()
        )
        win._sb_cfg = "c.json"
        win._sb_cfg_data = {"inbounds": []}

        # 1) движок упал на старте (FATAL в конфиге)
        assert win._restart_sing_box() is False
        assert rewrites == ["c.json"], "конфиг пересоздан перед запуском"
        assert purges == ["c.json"], "неудачная попытка обязана удалить конфиг"

        # 2) OSError на старте (движок/диск недоступны)
        purges.clear()
        rewrites.clear()
        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box",
            lambda cfg, root: (_ for _ in ()).throw(OSError("нет файла")),
        )
        assert win._restart_sing_box() is False
        assert rewrites == ["c.json"]
        assert purges == ["c.json"], "OSError-ветка тоже без сироты"
        win._sb_cfg = None
        win._sb_cfg_data = None


# ---- таймер 10с (VPN.ps1:615-641) ------------------------------------------


class TestTick:
    def test_dead_proc_detected(self, qapp, win):
        """kill -> 'Соединение оборвалось...', коннект разблокирован (619-630)."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        win.proc = proc
        win.btn_connect.setEnabled(False)
        win.btn_disconnect.setEnabled(True)
        win.tick.start()
        win._on_tick()
        assert (
            win.lbl_status.text()
            == "Соединение оборвалось - sing-box завершился, смотри лог"
        )
        assert win.proc is None
        assert win.btn_connect.isEnabled() and not win.btn_disconnect.isEnabled()
        assert not win.tick.isActive()

    def test_dead_proc_restarts_engine(self, qapp, win, monkeypatch):
        """Смерть движка -> автоперезапуск с тем же конфигом, тик живёт.

        Отклонение от 1.0.6: раньше обрыв оставлял пользователя без
        туннеля до ручного переподключения (и без записи в лог).
        """
        logs: list[str] = []
        monkeypatch.setattr("vpn_launcher.ui.window.write_log", logs.append)
        monkeypatch.setattr("vpn_launcher.ui.window.time.sleep", lambda _s: None)

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()

        class AliveProc:
            pid = 777

            def poll(self):
                return None

            def kill(self):
                pass

        calls: list = []
        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box",
            lambda cfg, root: calls.append(cfg) or AliveProc(),
        )
        win.proc = dead
        win._sb_cfg = "cfg.json"
        win._sb_restarts = 0
        win.tick.start()
        win._on_tick()

        assert calls == ["cfg.json"], "конфиг последнего подключения"
        assert win.proc is not None and win.proc.pid == 777
        assert win.tick.isActive(), "тик продолжает следить за движком"
        assert win._sb_restarts == 1
        assert "восстановлено" in win.lbl_status.text()
        assert any("sing-box exited" in m for m in logs), "причина смерти в логе"
        assert any("restarted ok" in m for m in logs)

    def test_restart_gives_up_after_three_attempts(self, qapp, win, monkeypatch):
        """Лимит 3 восстановлений за сессию -> честный обрыв, без петли."""
        monkeypatch.setattr("vpn_launcher.ui.window.write_log", lambda _m: None)
        monkeypatch.setattr("vpn_launcher.ui.window.time.sleep", lambda _s: None)

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()

        class AliveProc:
            pid = 777

            def poll(self):
                return None

            def kill(self):
                pass

        monkeypatch.setattr(
            "vpn_launcher.ui.window.start_sing_box", lambda cfg, root: AliveProc()
        )
        win.proc = dead
        win._sb_cfg = "cfg.json"
        win._sb_restarts = 0
        win.tick.start()
        for _ in range(4):
            win.proc = dead  # движок снова умирает после каждого перезапуска
            win._on_tick()

        assert win._sb_restarts == 3
        assert win.proc is None
        assert win._sb_cfg is None
        assert (
            win.lbl_status.text()
            == "Соединение оборвалось - sing-box завершился, смотри лог"
        )
        assert not win.tick.isActive()

    def test_egress_labels(self, qapp, win):
        """631-640: IP / 'Внешний IP недоступен'."""
        win._on_egress("1.2.3.4")
        assert win.lbl_egress.text() == "Внешний IP: 1.2.3.4"
        win._on_egress_failed("timeout")
        assert win.lbl_egress.text() == "Внешний IP недоступен"


# ---- --autoconnect (VPN.ps1:655-687) ---------------------------------------


class TestAutoconnect:
    def test_no_url_fails_fast(self, qapp, win):
        win.autoconnect()
        assert win._msgs and win._msgs[0][0] == "Вставь ссылку на подписку."
        assert (
            win.lbl_status.text()
            == "Не удалось загрузить подписку - проверь ссылку"
        )

    def test_chain_load_select_and_connect(self, qapp, win, monkeypatch):
        """700мс-цепочка: загрузка файла -> TUN -> выбор ноды -> клик.

        UAC отменён - цепочка останавливается на 'Отменено', дойдя до
        btnConnect, что и проверяем (без реального запуска движка).
        """
        from vpn_launcher.core.subscription import fetch_nodes

        nodes = fetch_nodes(str(SUB_FILE))
        win.state["selected"] = nodes[1]["tag"]  # помним прошлый выбор (677-681)
        monkeypatch.setattr("vpn_launcher.ui.window.is_elevated", lambda: False)
        confirms: list = []
        win._msg_confirm = lambda text, title="": (
            confirms.append((text, title)) or False
        )

        win.field_sub.setText(str(SUB_FILE))
        win.autoconnect()
        assert win.lbl_status.text() == "Загружаю подписку и подключаюсь..."

        assert _await(qapp, lambda: len(confirms) > 0, timeout=10)
        # TUN выбран (672-673), нода по тегу (677-681), дошли до btnConnect (684)
        assert win.radio_tun.checked() and not win.radio_proxy.checked()
        assert win.list_servers.selected_index() == 1
        assert win.lbl_status.text() == "Отменено - подключение не выполнено"
        assert state_mod.load_state()["mode"] == "tun"
        assert win.btn_load.isEnabled()
