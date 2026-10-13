# -*- coding: utf-8 -*-
"""Тёмная рамка-контейнер списка. Порт GameFrame (theme.ps1:130-154), вид по макету.

Заливка (11,16,23) #0b1017, рамка (43,53,68) #2b3544, радиус 8,
тонкий белый блик (a=50) по верхней грани между радиусами.
Внутрь - NeonList со своим скроллбаром (инсет 3).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class GameFrame(QWidget):
    def __init__(self, radius: int = 10, parent=None) -> None:
        super().__init__(parent)
        self._radius = radius

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(11, 16, 23))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(43, 53, 68), 1))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)

        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawLine(r + 1, 2, w - r - 1, 2)
