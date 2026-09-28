# -*- coding: utf-8 -*-
"""Горизонтальный разделитель. Порт New-GameDivider (theme.ps1:1137-1157)
с визуальным отклонением (просьба): вместо крохотной акцентной точки справа
- акцентный градиент вдоль всей линии: слева прозрачный -> справа голубой.

Базовая линия осталась как в 1.0.6: Line a=90 на y=1 (h=2).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QBrush, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme


class Divider(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(2)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        line = theme.LINE
        p.setPen(QPen(QColor(line.red(), line.green(), line.blue(), 90), 1))
        p.drawLine(0, 1, w, 1)

        # акцентный градиент поверх: прозрачный слева -> голубой справа
        grad = QLinearGradient(QPointF(0, 0), QPointF(w, 0))
        grad.setColorAt(0.0, QColor(0, 216, 255, 0))
        grad.setColorAt(1.0, QColor(0, 216, 255, 160))
        p.setPen(QPen(QBrush(grad), 1))
        p.drawLine(0, 1, w, 1)
