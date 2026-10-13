# -*- coding: utf-8 -*-
"""Горизонтальный разделитель. Порт New-GameDivider (theme.ps1:1137-1157).

Вид по макету 13.10: тонкая линия (47,61,79,a=180) — верхняя граница
строки статуса в секции подключения (.connection-status border-top).
Акцентный градиент убран: секции теперь раздельные, линии-разделители
между ними рисовать не нужно.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class Divider(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(2)

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(47, 61, 79, 180), 1))
        p.drawLine(0, 1, self.width(), 1)
