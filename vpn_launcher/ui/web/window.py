# -*- coding: utf-8 -*-
"""Окно приложения на HTML-интерфейсе (макет GPT «Cyber Purple»).

Внутри - QWebEngineView с ассетами ui/web/assets; логика живёт в скрытом
MainWindow (ui/window.py), мост - ui/web/bridge.py. Окно без рамки: шапку,
кнопки свернуть/закрыть и перетаскивание рисует страница.
"""
from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from vpn_launcher.core.log import write_log
from vpn_launcher.ui.web.bridge import Bridge

# Размер окна фиксирован и связан с assets/backdrop.png (подложка-свечение):
# окно не «прыгает» при загрузке серверов, ореол всегда совпадает с карточкой.
# Правка геометрии = перегенерировать подложку (см. gen_backdrop в КОНТЕКСТ.md).
PAGE_W, PAGE_H = 760, 952
MAX_W, MAX_H = 1000, 1400  # страховка от абсурдной высоты при отсутствии шрифтов

# Передача окна при повышении прав (UAC): сигнал «новое окно видно» старому
# экземпляру отдаём, когда страница РЕАЛЬНО отрисовалась (иначе старое окно
# закрывается раньше, чем новое что-то показывает: окно гаснет и появляется
# снова - жалоба 13.10). Опрос покадрово + страховка по таймауту.
HANDOFF_POLL_MS = 100  # период проверки «страница отрисовалась»
HANDOFF_FALLBACK_MS = 8000  # страховка: сигнал уйдёт даже без отрисовки


def assets_dir() -> Path:
    """Каталог ассетов: в собранной программе - в _MEIPASS."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    return base / "assets"


def qwebchannel_js() -> str:
    """Исходник qwebchannel.js: ресурс Qt (работает и в собранной программе).

    Ресурс появляется только после импорта QtWebChannel, поэтому импортируем
    его тут же (в Qt6 нет отдельного .js рядом с модулем).
    """
    importlib.import_module("PySide6.QtWebChannel")
    from PySide6.QtCore import QFile, QIODevice

    handle = QFile(":/qtwebchannel/qwebchannel.js")
    if handle.open(QIODevice.OpenModeFlag.ReadOnly):
        data = bytes(handle.readAll())
        handle.close()
        return data.decode("utf-8")
    for candidate in _js_candidates():  # запасной путь (старые сборки PySide6)
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


def _js_candidates() -> list[Path]:
    out: list[Path] = []
    here = Path(__file__).resolve().parent
    out.append(here / "assets" / "qwebchannel.js")
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        out.append(base / "assets" / "qwebchannel.js")
    return out


class WebWindow(QWidget):
    """Видимое окно приложения; win - скрытый движок логики."""

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(win.windowTitle())
        # прозрачное окно: видно только карточку макета со свечением и ракету,
        # тёмной «подложки» вокруг нет (просьба 13.10)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(PAGE_W, PAGE_H)

        self.bridge = Bridge(win, host=self, parent=self)

        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        page = self.view.page()
        page.setWebChannel(self.channel)
        # прозрачная страница: пока она грузится - тоже ничего лишнего не видно
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        self.bridge.page = page
        page.loadFinished.connect(self._on_loaded)
        self.view.setGeometry(0, 0, PAGE_W, PAGE_H)

        # логика может закрыться сама (передача окна при повышении прав) -
        # тогда закрываемся и мы
        self._alive = True
        win.installEventFilter(self)

        self._drag_offset: tuple[int, int] | None = None
        # передача окна при UAC (см. signal_when_visible)
        self._load_done = False
        self._handoff: Callable[[], None] | None = None
        self._handoff_done = False
        self._watching = False
        page.setHtml(self._page_html(), assets_dir().as_uri() + "/")

    # ---- страница --------------------------------------------------------
    def _page_html(self) -> str:
        html = (assets_dir() / "app.html").read_text(encoding="utf-8")
        channel_js = qwebchannel_js()
        # ловим ошибки страницы (диагностика + журнал приложения)
        guard = (
            "<script>window.__errs=[];"
            "window.addEventListener('error',function(e){"
            "window.__errs.push(String(e.message));"
            "if(window.qt&&qt.webChannelTransport){} });</script>"
        )
        if channel_js:
            html = html.replace(
                '<script src="app.js"></script>',
                f"{guard}<script>{channel_js}</script>\n"
                '<script src="app.js"></script>',
                1,
            )
        return html

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            return
        self._load_done = True
        self.measure()
        self._watch_paint()  # при передаче окна (UAC) - ждём отрисовки

    def measure(self) -> None:
        """Диагностика вёрстки: реальные размеры страницы (в консоль/лог).

        Размер окна намеренно НЕ подгоняется под страницу: он фиксирован и
        связан с подложкой backdrop.png, иначе ореол перестаёт совпадать с
        карточкой (см. комментарий к PAGE_W/PAGE_H).
        """
        if self.view.page() is None:
            return
        self.view.page().runJavaScript(
            "[document.documentElement.scrollWidth,"
            " document.documentElement.scrollHeight]",
            self._on_size,
        )

    def on_state_pushed(self) -> None:
        """Состояние пришло - размер окна не меняем (см. measure)."""

    def _on_size(self, size) -> None:  # noqa: ANN001
        try:
            w, h = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            return
        if (w, h) != (PAGE_W, PAGE_H):
            write_log(f"web ui: page {w}x{h} != window {PAGE_W}x{PAGE_H}")

    # ---- передача окна при повышении прав (UAC) --------------------------
    def signal_when_visible(self, callback: Callable[[], None]) -> None:
        """Отдать сигнал передачи (win/elevate.py), когда страница видна.

        Старое окно закрывается по этому сигналу: если слать его сразу после
        show(), окно гаснет на время загрузки страницы и потом «появляется»
        (жалоба 13.10 «изчезает и потом появляется»). Оцениваем видимость
        покадрово (как в тесте click-through), со страховкой по таймауту:
        даже если страница не отрисуется, старое окно не повиснет.
        """
        self._handoff = callback
        self._handoff_done = False
        self._watching = False
        QTimer.singleShot(HANDOFF_FALLBACK_MS, self._fire_handoff)
        self._watch_paint()

    def _watch_paint(self) -> None:
        """Запустить один цикл опроса (без передачи сигнала не шлём)."""
        if self._handoff is None or self._watching:
            return
        self._watching = True
        QTimer.singleShot(HANDOFF_POLL_MS, self._poll_paint)

    def _poll_paint(self) -> None:
        if self.isVisible():  # grab() отрисует и скрытое - ждём показа окна
            img = self.grab().toImage()
            if img.pixelColor(PAGE_W // 2, PAGE_H // 2).alpha() > 200:
                # карточка плотная = страница показана
                self._watching = False
                self._fire_handoff()
                return
        QTimer.singleShot(HANDOFF_POLL_MS, self._poll_paint)

    def _fire_handoff(self) -> None:
        if self._handoff_done:
            return
        self._handoff_done = True
        callback, self._handoff = self._handoff, None
        if callback is not None:
            callback()

    # ---- окно ------------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        """Фон окна: ничего не рисуем.

        Видимая часть (карточка, свечение, кайма) - страница, ровно как в
        макете. Пустое поле вокруг остаётся с нулевой альфой, поэтому клики
        по прозрачному уходят СКВОЗЬ окно на рабочий стол/игру (просьба
        13.10); раньше здесь стоял невидимый слой alpha=1, который эти
        клики перехватывал.
        """
        super().paintEvent(e)

    def begin_drag(self, screen_x: int, screen_y: int) -> None:
        g = self.pos()
        self._drag_offset = (screen_x - g.x(), screen_y - g.y())

    def drag_to(self, screen_x: int, screen_y: int) -> None:
        if self._drag_offset is None:
            return
        self.move(screen_x - self._drag_offset[0], screen_y - self._drag_offset[1])

    def end_drag(self) -> None:
        self._drag_offset = None

    def close_app(self) -> None:
        """Закрытие из страницы: сначала логика (движок, kill switch), потом мы."""
        self.win.close()
        self.close()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802, ANN001
        if obj is self.win and ev.type() in (QEvent.Type.Close, QEvent.Type.Hide):
            if self._alive:
                self._alive = False
                self.close()
        return False

    def closeEvent(self, e) -> None:  # noqa: N802
        self._alive = False
        self.win.removeEventFilter(self)
        e.accept()