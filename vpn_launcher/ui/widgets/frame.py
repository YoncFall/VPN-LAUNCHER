# -*- coding: utf-8 -*-
"""Тёмная рамка-контейнер списка. Порт GameFrame (theme.ps1:130-154).

Заливка (18,21,29), рамка (46,52,68), радиус 10,
тонкий белый блик (a=70) по верхней грани между радиусами.
Внутрь на этапе 4 встанет NeonList со своим скроллбаром.
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
        p.setBrush(QColor(18, 21, 29))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(46, 52, 68), 1))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r, r)

        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.drawLine(r + 1, 2, w - r - 1, 2)
