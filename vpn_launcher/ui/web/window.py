# -*- coding: utf-8 -*-
"""Окно приложения на HTML-интерфейсе (макет GPT «Cyber Purple»).

Внутри - QWebEngineView с ассетами ui/web/assets; логика живёт в скрытом
MainWindow (ui/window.py), мост - ui/web/bridge.py. Окно без рамки: шапку,
кнопки свернуть/закрыть и перетаскивание рисует страница.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui.web.bridge import Bridge

# стартовый размер до замера страницы (макет: 620 + поле под ракету)
PAGE_W, PAGE_H = 700, 880
MAX_W, MAX_H = 1000, 1400  # страховка от абсурдной высоты при отсутствии шрифтов


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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(PAGE_W, PAGE_H)

        self.bridge = Bridge(win, host=self, parent=self)

        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        page = self.view.page()
        page.setWebChannel(self.channel)
        # тёмный фон на время загрузки страницы (иначе мелькает белый прямоугольник)
        page.setBackgroundColor(QColor(10, 13, 18))
        self.bridge.page = page
        page.loadFinished.connect(self._on_loaded)
        self.view.setGeometry(0, 0, PAGE_W, PAGE_H)

        # логика может закрыться сама (передача окна при повышении прав) -
        # тогда закрываемся и мы
        self._alive = True
        win.installEventFilter(self)

        self._drag_offset: tuple[int, int] | None = None
        self._measured_at = 0.0
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
        self.measure()

    def measure(self) -> None:
        """Подогнать размер окна под содержимое страницы (строки, списки)."""
        if self.view.page() is None:
            return
        self.view.page().runJavaScript(
            "[document.documentElement.scrollWidth,"
            " document.documentElement.scrollHeight]",
            self._on_size,
        )

    def on_state_pushed(self) -> None:
        """Мост прислал состояние: иногда страница стала выше/ниже."""
        now = time.monotonic()
        if now - self._measured_at < 0.5:
            return
        self._measured_at = now
        self.measure()

    def _on_size(self, size) -> None:  # noqa: ANN001
        try:
            w, h = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            return
        if w <= 0 or h <= 0:
            return
        self.setFixedSize(min(w + 2, MAX_W), min(h + 2, MAX_H))
        self.view.setGeometry(0, 0, self.width(), self.height())

    # ---- окно ------------------------------------------------------------
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