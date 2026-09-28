# -*- coding: utf-8 -*-
"""Шапка окна. Порт Install-GameTitleBar (theme.ps1:1160-1244), высота 46.

- фон-градиент (20,24,33) -> (12,14,19);
- нижняя граница Line на y=45;
- левый кант 3px: градиент Accent -> AccentD;
- градиентная подчёркивающая линия x=3..40% ширины, y=44 - УБРАНА по просьбе
  (синий штрих под шапкой больше не рисуется);
- логотип 'VPN ЛАУНЧЕР' (FLogo 17 Bold): слой свечения (0,180,215,a=110)
  со смещением (+1,+1) + основной текст Accent;
- 'by @YoncFALL' (FSub) TextDim справа от логотипа;
- LED + квадратики capmin/capclose (34x30, y=8);
- перетаскивание окна за пустые места.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme
from vpn_launcher.ui.widgets.led import Led
from vpn_launcher.ui.widgets.button import GameButton

LOGO = "VPN ЛАУНЧЕР"
BYLINE = "by @YoncFALL"


class TitleBar(QWidget):
    HEIGHT = 46
    closed = Signal()
    minimize_requested = Signal()

    def __init__(self, width: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setFixedWidth(width)
        self._drag: QPointF | None = None

        self.led = Led(10, "off", self)
        self.led.move(width - 116, (self.HEIGHT - 10) // 2)

        self.btn_min = GameButton("", "capmin", 7, self)
        self.btn_min.setGeometry(width - 80, 8, 34, 30)
        self.btn_close = GameButton("", "capclose", 7, self)
        self.btn_close.setGeometry(width - 42, 8, 34, 30)
        self.btn_min.clicked.connect(self.minimize_requested)
        self.btn_close.clicked.connect(self.closed)

    # ---- drag ------------------------------------------------------------
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._drag = e.globalPosition().toPoint() - win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None

    # ---- paint -----------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # фон с лёгким градиентом
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(20, 24, 33))
        bg.setColorAt(1.0, QColor(12, 14, 19))
        p.fillRect(QRectF(0, 0, w, h), bg)

        # нижняя граница
        p.setPen(QPen(theme.LINE, 1))
        p.drawLine(0, h - 1, w, h - 1)

        # акцентный кант слева
        edge = QLinearGradient(0, 0, 0, h)
        edge.setColorAt(0.0, theme.ACCENT)
        edge.setColorAt(1.0, theme.ACCENT_D)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(0, 0, 3, h), edge)

        # логотип: свечение + основной текст
        p.setFont(theme.f_logo())
        fm = p.fontMetrics()
        w_main = fm.horizontalAdvance(LOGO)
        ty = (h - 22) // 2
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter) | int(
            Qt.TextFlag.TextSingleLine
        ) | int(Qt.TextFlag.TextDontClip)
        p.setPen(QColor(0, 180, 215, 110))
        p.drawText(QRectF(17, ty + 1, w_main + 6, 22), flags, LOGO)
        p.setPen(theme.ACCENT)
        p.drawText(QRectF(16, ty, w_main + 6, 22), flags, LOGO)

        # byline
        p.setFont(theme.f_sub())
        p.setPen(theme.TEXT_DIM)
        p.drawText(
            QRectF(16 + w_main + 10, (h - 14) // 2 + 3, 140, 14),
            flags,
            BYLINE,
        )
