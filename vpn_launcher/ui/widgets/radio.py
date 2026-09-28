# -*- coding: utf-8 -*-
"""Сегмент-радиокнопка режима. Порт New-GameRadio (theme.ps1:937-998).

Выбрана: градиент (24,52,68)->(16,40,55), голубая рамка, точка 6px,
текст Accent. Не выбрана: (23,26,36)->(19,22,31) [hover (31,37,50)->(25,29,40)],
рамка Line [LineHi], текст (150,158,176) [Text]. Радиус 8, шрифт FBtn.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme


class GameRadio(QWidget):
    toggled = Signal()

    def __init__(self, text: str, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self._checked = checked
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---- api -------------------------------------------------------------
    def checked(self) -> bool:
        return self._checked

    def set_checked(self, v: bool) -> None:
        if self._checked != v:
            self._checked = v
            self.update()

    # ---- state -----------------------------------------------------------
    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            e.position().toPoint()
        ):
            self._checked = True
            self.update()
            self.toggled.emit()

    # ---- painting --------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self._checked:
            top, bot = (24, 52, 68), (16, 40, 55)
            border, txt = theme.ACCENT, theme.ACCENT
        elif self._hover:
            top, bot = (31, 37, 50), (25, 29, 40)
            border, txt = theme.LINE_HI, theme.TEXT
        else:
            top, bot = (23, 26, 36), (19, 22, 31)
            border, txt = theme.LINE, QColor(150, 158, 176)

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(*top))
        grad.setColorAt(1.0, QColor(*bot))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

        if self._checked:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.ACCENT)
            p.drawEllipse(QRectF(14, (h - 6) / 2, 6, 6))
            inner = QRectF(22, 0, w - 28, h)
        else:
            inner = QRectF(8, 0, w - 16, h)

        p.setPen(txt if isinstance(txt, QColor) else QColor(txt))
        p.setFont(theme.f_btn())
        p.drawText(
            inner,
            int(Qt.AlignmentFlag.AlignCenter)
            | int(Qt.TextFlag.TextSingleLine)
            | int(Qt.TextFlag.TextDontClip),
            self._text,
        )
