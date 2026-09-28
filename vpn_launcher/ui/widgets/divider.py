# -*- coding: utf-8 -*-
"""Горизонтальный разделитель. Порт New-GameDivider (theme.ps1:1137-1157).

Линия Line a=90 на y=1 (h=2) + крохотная акцентная точка a=120 справа.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 216, 255, 120))
        p.drawEllipse(w - 3, 0, 3, 3)
