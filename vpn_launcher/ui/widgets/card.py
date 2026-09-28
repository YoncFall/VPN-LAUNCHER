# -*- coding: utf-8 -*-
"""Большая карточка интерфейса. Порт New-GameCard (theme.ps1:1090-1134).

- мягкое свечение по контуру (24,34,46, a=26);
- заливка градиентом (27,31,42) -> (22,25,34);
- рамка Line (46,52,68), радиус 14;
- акцентная полоска сверху: x=radius..radius+70, h=2, градиент Accent a=255 -> a=0.

Визуальное отклонение (просьба, скриншот «интерфейс градиент»): по четырём
ребрам рамки идут акцентные градиенты - яркие в правом верхнем и левом нижнем
углах, гаснут вдоль направлений: верх влево, право вниз, низ вправо, лево вверх.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme

_EDGE_ALPHA = 180  # яркость акцента в «светлых» углах


class GameCard(QWidget):
    def __init__(self, radius: int = 14, parent=None) -> None:
        super().__init__(parent)
        self._radius = radius

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        # ореол (в PS - PathGradientBrush по внешнему контуру)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(24, 34, 46, 26))
        p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), r + 3, r + 3)

        # заливка карточки
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(27, 31, 42))
        grad.setColorAt(1.0, QColor(22, 25, 34))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)

        # рамка
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.LINE, 1))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)

        # акцентные градиенты по рёбрам: начало (яркое) -> конец (прозрачный)
        edges = [
            (float(w - r), 1.0, float(r), 1.0),  # верх: правый угол -> влево
            (float(w - 1), float(r), float(w - 1), float(h - r)),  # право: вниз
            (float(r), float(h - 1), float(w - r), float(h - 1)),  # низ: вправо
            (1.0, float(h - r), 1.0, float(r)),  # лево: нижний угол -> вверх
        ]
        for x0, y0, x1, y1 in edges:
            g = QLinearGradient(QPointF(x0, y0), QPointF(x1, y1))
            g.setColorAt(0.0, QColor(0, 216, 255, _EDGE_ALPHA))
            g.setColorAt(1.0, QColor(0, 216, 255, 0))
            p.setPen(QPen(QBrush(g), 1))
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # акцентная полоска сверху (theme.ps1:1122-1126)
        strip = QLinearGradient(QPointF(r, 0), QPointF(r + 70, 0))
        strip.setColorAt(0.0, QColor(0, 216, 255, 255))
        strip.setColorAt(1.0, QColor(0, 216, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(strip)
        p.drawRect(QRectF(r, 1, 70, 2))
