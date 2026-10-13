# -*- coding: utf-8 -*-
"""Секции интерфейса. Порт New-GameCard (theme.ps1:1090-1134) + макет 13.10.2026.

По макету окно больше не одна большая карточка, а четыре отдельные секции
(ПОДПИСКА/СЕРВЕРЫ/ИСКЛЮЧЕНИЯ/ПОДКЛЮЧЕНИЕ) с промежутками 9px на фоне окна.
Секции описаны списком прямоугольников set_panels() и рисуются этим виджетом
(контейнер card остаётся родителем всех контролов — координаты не меняли).

Вид каждой секции (макет .section): градиент (21,28,38)->(15,20,28),
рамка #342d4d, радиус 10, мягкое фиолетовое свечение по контуру.
Без панелей (set_panels не вызывался) — прежняя сплошная карточка.
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

_EDGE_ALPHA = 215  # яркость акцента в светлых углах (наследие карточки)


class GameCard(QWidget):
    def __init__(self, radius: int = 14, parent=None) -> None:
        super().__init__(parent)
        self._radius = radius
        self._panels: list[tuple[int, int, int, int]] = []

    def set_panels(self, rects: list[tuple[int, int, int, int]]) -> None:
        """Прямоугольники секций (x, y, w, h) в координатах этого контейнера."""
        self._panels = list(rects)
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        if self._panels:
            for x, y, pw, ph in self._panels:
                # мягкое фиолетовое свечение контура (box-shadow из макета)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(134, 73, 255, 16))
                p.drawRoundedRect(QRectF(x - 2, y - 2, pw + 4, ph + 4), 12, 12)
                # заливка секции
                grad = QLinearGradient(0, y, 0, y + ph)
                grad.setColorAt(0.0, QColor(theme.CARD))
                grad.setColorAt(1.0, QColor(theme.CARD_HI))
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(x, y, pw, ph), 10, 10)
                # рамка
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(theme.LINE, 1))
                p.drawRoundedRect(QRectF(x + 0.5, y + 0.5, pw - 1, ph - 1), 10, 10)
            return

        # ореол (в PS - PathGradientBrush по внешнему контуру)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(134, 73, 255, 26))
        p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), r + 3, r + 3)

        # заливка карточки
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(theme.CARD))
        grad.setColorAt(1.0, QColor(theme.CARD_HI))
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
        g_top.setColorAt(0.0, QColor(167, 131, 255, 0))
        g_top.setColorAt(1.0, QColor(167, 131, 255, _EDGE_ALPHA))

        # право: сверху яркий -> снизу прозрачный
        right = QPainterPath()
        right.moveTo(R, T + r)
        right.lineTo(R, B - r)
        g_right = QLinearGradient(QPointF(R, T), QPointF(R, B))
        g_right.setColorAt(0.0, QColor(167, 131, 255, _EDGE_ALPHA))
        g_right.setColorAt(1.0, QColor(167, 131, 255, 0))

        # низ: дуга BL + прямая; слева яркий -> справа прозрачный
        bottom = QPainterPath()
        bottom.moveTo(L, B - r)
        bottom.arcTo(bl, 180, 90)
        bottom.lineTo(R - r, B)
        g_bot = QLinearGradient(QPointF(R, B), QPointF(L, B))
        g_bot.setColorAt(0.0, QColor(167, 131, 255, 0))
        g_bot.setColorAt(1.0, QColor(167, 131, 255, _EDGE_ALPHA))

        # лево: снизу яркий -> сверху прозрачный
        left = QPainterPath()
        left.moveTo(L, B - r)
        left.lineTo(L, T + r)
        g_left = QLinearGradient(QPointF(L, B), QPointF(L, T))
        g_left.setColorAt(0.0, QColor(167, 131, 255, _EDGE_ALPHA))
        g_left.setColorAt(1.0, QColor(167, 131, 255, 0))

        for path, g in ((top, g_top), (right, g_right), (bottom, g_bot), (left, g_left)):
            pen = QPen(QBrush(g), 1)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(path)
