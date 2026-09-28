# -*- coding: utf-8 -*-
"""Индикатор-лампочка. Порт New-GameLed (theme.ps1:1049-1087).

Состояния: off=Muted, busy=Accent, ok=Accent2, err=Danger.
Мягкое свечение (a=150 у центра -> 0 у края) + ядро + белый блик.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme

_STATES = {
    "off": theme.MUTED,
    "busy": theme.ACCENT,
    "ok": theme.ACCENT2,
    "err": theme.DANGER,
}


class Led(QWidget):
    def __init__(self, diameter: int = 10, state: str = "off", parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._state = state if state in _STATES else "off"

    def set_state(self, state: str) -> None:
        if state in _STATES and state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = self.width()
        c = _STATES[self._state]

        glow = QRadialGradient(QPointF(d / 2, d / 2), (d + 4) / 2)
        glow.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 150))
        glow.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(-2, -2, d + 4, d + 4))

        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, d - 2, d - 2))

        hi = max(2.0, (d - 2) * 0.4)
        p.setBrush(QColor(255, 255, 255, 160))
        p.drawEllipse(QRectF(2, 2, hi, hi))
