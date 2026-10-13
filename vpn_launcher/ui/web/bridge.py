# -*- coding: utf-8 -*-
"""Мост HTML-интерфейса (QtWebEngine) и логики окна.

Логика целиком остаётся в MainWindow (ui/window.py) - мост её не дублирует,
а только переводит команды страницы в вызовы существующих обработчиков и
отдаёт странице снимок состояния для отрисовки.

Команды объявлены слотами QWebChannel: страница зовёт bridge.имя(...), Qt
доставляет вызов в поток объекта (GUI), поэтому логика окна не трогается из
IPC-потока. QObject родителя - окно, значит слоты безопасны по потоку.
"""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QEventLoop, QObject, QTimer, Slot

from vpn_launcher.ui import theme

_POLL_MS = 120  # как часто страница забирает состояние окна
_CONFIRM_GUARD_MS = 180_000  # страховка: страница не ответила - считаем «Отмена»

# состояние ламп Qt -> классы ламп макета
_LAMP = {
    "ok": "ready",
    "busy": "connecting",
    "warn": "connecting",
    "err": "error",
    "off": "off",
}

# цвет текста статуса -> класс текста (красные ошибки в HTML)
_KIND = {
    theme.DANGER.name(): "error",
    theme.WARN.name(): "warn",
    theme.ACCENT2.name(): "ok",
}


class Bridge(QObject):
    """Команды страницы -> окно; состояние окна -> страница."""

    def __init__(self, win, host: Any = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.win = win
        self.host = host  # WebWindow (перетаскивание/закрытие); None в тестах
        self.page: Any = None  # QWebEnginePage; ставит WebWindow
        self._last = ""
        self._status_kind = "info"
        self._modal_id = 0
        self._waits: dict[int, QEventLoop] = {}
        self._hooks_installed = False
        self._install_hooks()
        self.timer = QTimer(self)
        self.timer.setInterval(_POLL_MS)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    # ---- подмена Qt-диалогов на HTML-модалки --------------------------
    def _install_hooks(self) -> None:
        """MessageBox'ы окна уходят в страницу (окно Qt скрыто)."""
        if self._hooks_installed:
            return
        win = self.win
        original_status = win._status

        def status(text: str, color=None) -> None:  # noqa: ANN001
            self._status_kind = _KIND.get(color.name(), "info") if color else "info"
            original_status(text, color)

        def msg(text: str, title: str = "", *, icon: str = "") -> None:
            self.show_modal(text, title, icon, confirm=False)

        def confirm(text: str, title: str = "") -> bool:
            return self.ask_modal(text, title)

        win._status = status  # noqa: SLF001
        win._msg = msg  # noqa: SLF001
        win._msg_confirm = confirm  # noqa: SLF001
        self._hooks_installed = True

    # ---- команды страницы ------------------------------------------------
    @Slot()
    def ready(self) -> None:
        """Страница загрузилась - отдаём состояние."""
        self.push()

    @Slot()
    def loadSub(self) -> None:
        self.win._load_click()

    @Slot()
    def pingServers(self) -> None:
        self.win._ping_click()

    @Slot()
    def openLog(self) -> None:
        self.win._open_log()

    @Slot(str)
    def setSubUrl(self, url: str) -> None:
        self.win.field_sub.setText(url)

    @Slot(int)
    def selectServer(self, index: int) -> None:
        self.win.list_servers.select_index(index)

    @Slot(str)
    def setMode(self, mode: str) -> None:
        self.win._select_mode(mode)

    @Slot(str)
    def setAppMode(self, mode: str) -> None:
        self.win._select_app_mode(mode)

    @Slot(str)
    def setProcText(self, text: str) -> None:
        self.win.picker_proc.setText(text)

    @Slot()
    def addProcess(self) -> None:
        self.win._excl_add()

    @Slot(int)
    def selectExcl(self, index: int) -> None:
        self.win.list_excl.select_index(index)

    @Slot()
    def removeProcess(self) -> None:
        self.win._excl_del()

    @Slot()
    def clearProcesses(self) -> None:
        self.win._excl_clr()

    @Slot()
    def connectVpn(self) -> None:
        self.win._connect_click()

    @Slot()
    def disconnectVpn(self) -> None:
        self.win._disconnect_click()

    @Slot()
    def testConfig(self) -> None:
        self.win._testcfg_click()

    @Slot()
    def toggleDpi(self) -> None:
        self.win._zapret_click()

    @Slot()
    def autoDpi(self) -> None:
        self.win._zapret_pick()

    @Slot(str)
    def pageError(self, message: str) -> None:
        """Ошибка в JS страницы - в журнал приложения."""
        from vpn_launcher.core.log import write_log  # noqa: PLC0415

        write_log(f"web ui error: {message}")

    @Slot()
    def minimize(self) -> None:
        if self.host is not None:
            self.host.showMinimized()

    @Slot()
    def closeWin(self) -> None:
        if self.host is not None:
            self.host.close_app()

    @Slot(int, int)
    def dragStart(self, screen_x: int, screen_y: int) -> None:
        if self.host is not None:
            self.host.begin_drag(screen_x, screen_y)

    @Slot(int, int)
    def dragMove(self, screen_x: int, screen_y: int) -> None:
        if self.host is not None:
            self.host.drag_to(screen_x, screen_y)

    @Slot()
    def dragEnd(self) -> None:
        if self.host is not None:
            self.host.end_drag()

    @Slot(int, bool)
    def answerModal(self, modal_id: int, ok: bool) -> None:
        self._finish(int(modal_id), bool(ok))

    # ---- состояние окна -> страница --------------------------------------
    def snapshot(self) -> dict:
        """Снимок того, что странице нужно нарисовать."""
        win = self.win
        pings = win.list_servers.pings
        servers = []
        for i, node in enumerate(win.nodes):
            tag = str(node.get("tag") or "")
            text, cls = _ping_cell(pings.get(tag))
            servers.append(
                {
                    "i": i,
                    "proto": str(node.get("proto") or ""),
                    "name": str(node.get("display") or ""),
                    "pingText": text,
                    "pingClass": cls,
                }
            )
        return {
            "subUrl": win.field_sub.text(),
            "procText": win.picker_proc.text(),
            "servers": servers,
            "serverSelected": win.list_servers.selected_index(),
            "excl": win.list_excl.item_texts(),
            "exclSelected": win.list_excl.selected_index(),
            "picker": list(win.picker_proc.item_source),
            "mode": win._mode(),
            "appMode": win._app_mode(),
            "appSec": win.lbl_appsec.text(),
            "appHint": win.lbl_apps_hint.text(),
            "status": win.lbl_status.text(),
            "statusKind": self._status_kind,
            "lamp": _LAMP.get(win.led_status.state(), "off"),
            "dpiLamp": _LAMP.get(win.led_zapret.state(), "off"),
            "egress": win.lbl_egress.text() or "Внешний IP: недоступен",
            "connect": win.btn_connect.isEnabled(),
            "disconnect": win.btn_disconnect.isEnabled(),
            "testcfg": win.btn_testcfg.isEnabled(),
            "dpi": {
                "active": win.btn_zapret.is_active(),
                "busy": not win.btn_zapret.isEnabled(),
            },
        }

    def poll(self) -> None:
        """Таймер: отдать странице состояние, если оно изменилось."""
        if self.page is None:
            return
        blob = json.dumps(self.snapshot(), ensure_ascii=False)
        if blob != self._last:
            self._last = blob
            self._run(f"VPL.apply({blob});")
            self.state_pushed()

    def push(self) -> None:
        """Форс-выдача состояния (страница загрузилась)."""
        self._last = ""
        self.poll()

    def _run(self, js: str) -> None:
        if self.page is not None:
            self.page.runJavaScript(js)

    def state_pushed(self) -> None:
        """Хост узнал об изменении содержимого (может выроснуть окно)."""
        if self.host is not None:
            self.host.on_state_pushed()

    # ---- модальные окна (бывшие QMessageBox) ----------------------------
    def show_modal(self, text: str, title: str, icon: str, *, confirm: bool) -> int:
        self._modal_id += 1
        mid = self._modal_id
        payload = {
            "id": mid,
            "text": str(text),
            "title": str(title or ""),
            "icon": icon or "",
            "confirm": confirm,
        }
        self._run(f"VPL.modal({json.dumps(payload, ensure_ascii=False)});")
        return mid

    def ask_modal(self, text: str, title: str) -> bool:
        """Асинхронный «Да/Нет»: ждём ответа страницы в отдельном цикле."""
        if self.page is None:  # страницы нет (тесты/headless) - тихо отмена
            return False
        mid = self.show_modal(text, title, "", confirm=True)
        loop = QEventLoop()
        self._waits[mid] = loop
        guard = QTimer(self)
        guard.setSingleShot(True)
        guard.timeout.connect(lambda: self._finish(mid, False))
        guard.start(_CONFIRM_GUARD_MS)
        loop.exec()
        return bool(getattr(loop, "answer", False))

    def _finish(self, mid: int, ok: bool) -> None:
        loop = self._waits.pop(mid, None)
        if loop is None:
            return
        loop.answer = ok  # noqa: SLF001
        loop.quit()


def _ping_cell(ms: int | None) -> tuple[str, str]:
    """Пинг -> (текст, класс цвета) - те же пороги, что в NeonList."""
    if ms is None:
        return "---", ""
    if ms == -2:
        return "...", ""
    if ms < 0:
        return "offline", "bad"
    if ms < 120:
        return f"{ms} ms", "good"
    if ms < 260:
        return f"{ms} ms", "medium"
    return f"{ms} ms", "bad"