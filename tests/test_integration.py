# -*- coding: utf-8 -*-
"""Этап 5: оркестрация окна - порт обработчиков VPN.ps1 (offscreen).

Сеть: только локальная (TCP-сервер для пинга, файл подписки вместо HTTP);
диалоги подменяются записью (win._msg/_msg_confirm), state.json - во
временном каталоге, реестр прокси заглушен. Сверяем тексты статусов и
порядок операций с VPN.ps1 (строки указаны у тестов).

ВАЖНО: у тестов-методов обязан быть self (см. test_ui_widgets.py).
"""
from __future__ import annotations

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
