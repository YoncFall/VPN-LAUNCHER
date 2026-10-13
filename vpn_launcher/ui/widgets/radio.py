# -*- coding: utf-8 -*-
"""Сегмент-радиокнопка режима. Порт New-GameRadio (theme.ps1:937-998), вид по макету.

Выбрана: градиент (43,35,69)->(33,26,54), фиолетовая рамка #7754ba, точка
6px Accent, текст (217,201,255). Не выбрана: фон #0b1017 (сливается с
контейнером SegmentBox), без рамки, текст (137,150,169) [hover (215,226,241)].
Радиус 5, шрифт FBtn. Контейнер SegmentBox — общая «пилюля» под пару
сегментов (как .mode-segments/.exception-segments в макете).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme


class SegmentBox(QWidget):
    """Контейнер-пилюля под пару сегментов-радио (фон #0b1017, рамка #283343).

    Рисуется ДО радио (создаётся раньше них), поэтому сегменты видны поверх.
    """

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(11, 16, 23))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(40, 51, 67), 1))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)


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
            top, bot = (43, 35, 69), (33, 26, 54)
            border, txt = QColor(119, 84, 186), QColor(217, 201, 255)
        elif self._hover:
            top, bot = (16, 21, 29), (16, 21, 29)
            border, txt = QColor(70, 85, 106), QColor(215, 226, 241)
        else:
            top, bot = (11, 16, 23), (11, 16, 23)
            border, txt = QColor(0, 0, 0, 0), QColor(137, 150, 169)

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(*top))
        grad.setColorAt(1.0, QColor(*bot))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 5, 5)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 5, 5)

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
