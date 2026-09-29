# -*- coding: utf-8 -*-
"""Свой скроллбар. Этап 4.

Порт геометрии DarkListBox (theme.ps1:227-246): подложка (15,17,24), трек 4px
(28,32,42), ползунок-градиент (78,90,116)->(50,58,78), min 20px, радиус 2.
В Qt рисуется целиком своим виджетом — нативного белого ползунка нет,
поэтому и мерцания при hover не будет.

Паритет: дословно та же арифметика, что в PS (GetScrollInfo + NC-полоса):
  thumbH = max(20, sh * nPage / (nMax - nMin + 1)),
  thumbY = top + 2 + (sh - 4 - thumbH) * pos / range.
Колёсико/клик по треку даёт QScrollBar (стандартный шаг), рисуем только вид.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QScrollBar

from vpn_launcher.ui import theme


class NeonScrollBar(QScrollBar):
    """Вертикальный скроллбар без стрелок: подложка, трек 4px, ползунок 4px."""

    WIDTH = 14

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setFixedWidth(self.WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        # стиль - пустой: фон и рамки рисует paintEvent (иначе QSS перекроет)
        self.setStyleSheet("background: transparent; border: none;")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.WIDTH, 24)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # подложка всей полосы (перекрывает фон списка под скроллбаром)
        p.fillRect(0, 0, w, h, QColor(theme.SB_BG))

        tx = (w - 4) // 2
        p.fillRect(tx, 2, 4, max(1, h - 4), QColor(theme.SB_TRACK))

        up, down, page = self.minimum(), self.maximum(), self.pageStep()
        total = down - up + 1
        if total <= page or h <= 8:
            return  # прокрутки нет (в PS полоса в этом случае не рисуется)
        thumb_h = max(20, h * page // total)
        thumb_h = min(thumb_h, h - 4)
        rng = max(1, total - page)  # range = nMax - nMin - nPage + 1
        pos = min(max(self.value() - up, 0), rng)
        ty = 2 + (h - 4 - thumb_h) * pos // rng

        grad = QLinearGradient(0, ty, 0, ty + thumb_h)
        grad.setColorAt(0.0, QColor(theme.SB_THUMB_TOP))
        grad.setColorAt(1.0, QColor(theme.SB_THUMB_BOT))
        path = QPainterPath()
        path.addRoundedRect(QRectF(tx, ty, 4, thumb_h), 2, 2)
        p.fillPath(path, grad)
