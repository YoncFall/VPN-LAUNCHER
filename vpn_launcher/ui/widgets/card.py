# -*- coding: utf-8 -*-
"""Большая карточка интерфейса. Порт New-GameCard (theme.ps1:1090-1134).

- мягкое свечение по контуру (24,34,46, a=26);
- заливка градиентом (27,31,42) -> (22,25,34);
- рамка Line (46,52,68), радиус 14;
- акцентная полоска сверху (x=radius..radius+70) - УБРАТА по просьбе.

Визуальное отклонение (просьба, скриншот «интерфейс градиент»): по рамке идут
акцентные градиенты - ярче всего правый верхний и левый нижний углы; линии
проходят через скругления углов (полукруги доведены по просьбе) и гаснут
вдоль рёбер: верх влево, право вниз, низ вправо, лево вверх.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme

_EDGE_ALPHA = 215  # яркость акцента в светлых углах (было 180, стало чуть ярче)


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

        self._edge_gradients(p, w, h, r)

    # ---- акцентные градиенты по периметру, через дуги углов ---------------
    def _edge_gradients(self, p: QPainter, w: int, h: int, r: int) -> None:
        L, T = 1.0, 1.0
        R, B = float(w - 1), float(h - 1)
        tl = QRectF(L, T, 2 * r, 2 * r)
        tr = QRectF(R - 2 * r, T, 2 * r, 2 * r)
        bl = QRectF(L, B - 2 * r, 2 * r, 2 * r)

        # верх: дуга TL + прямая + дуга TR; слева прозрачный -> справа яркий
        top = QPainterPath()
        top.moveTo(L, T + r)
        top.arcTo(tl, 180, -90)
        top.lineTo(R - r, T)
        top.arcTo(tr, 90, -90)
        g_top = QLinearGradient(QPointF(L, T), QPointF(R, T))
        g_top.setColorAt(0.0, QColor(0, 216, 255, 0))
        g_top.setColorAt(1.0, QColor(0, 216, 255, _EDGE_ALPHA))

        # право: сверху яркий -> снизу прозрачный
        right = QPainterPath()
        right.moveTo(R, T + r)
        right.lineTo(R, B - r)
        g_right = QLinearGradient(QPointF(R, T), QPointF(R, B))
        g_right.setColorAt(0.0, QColor(0, 216, 255, _EDGE_ALPHA))
        g_right.setColorAt(1.0, QColor(0, 216, 255, 0))

        # низ: дуга BL + прямая; слева яркий -> справа прозрачный
        bottom = QPainterPath()
        bottom.moveTo(L, B - r)
        bottom.arcTo(bl, 180, 90)
        bottom.lineTo(R - r, B)
        g_bot = QLinearGradient(QPointF(R, B), QPointF(L, B))
        g_bot.setColorAt(0.0, QColor(0, 216, 255, 0))
        g_bot.setColorAt(1.0, QColor(0, 216, 255, _EDGE_ALPHA))

        # лево: снизу яркий -> сверху прозрачный
        left = QPainterPath()
        left.moveTo(L, B - r)
        left.lineTo(L, T + r)
        g_left = QLinearGradient(QPointF(L, B), QPointF(L, T))
        g_left.setColorAt(0.0, QColor(0, 216, 255, _EDGE_ALPHA))
        g_left.setColorAt(1.0, QColor(0, 216, 255, 0))

        for path, g in ((top, g_top), (right, g_right), (bottom, g_bot), (left, g_left)):
            pen = QPen(QBrush(g), 1)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(path)
