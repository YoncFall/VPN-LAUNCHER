# -*- coding: utf-8 -*-
"""Индикатор-лампочка. Порт New-GameLed (theme.ps1:1049-1087).

Состояния: off=Muted, busy=Accent, ok=Accent2, warn=Warn (пинг), err=Danger.
Мягкое свечение (a=150 у центра -> 0 у края) + ядро + белый блик.

Отклонение от 1.0.6 (по просьбе пользователя): плавное включение/гашение и
пульсация. set_state() остался мгновенным (как в PS); light_up(state, pulse)
гоняет яркость по таймеру: fade-in ~0.6с (ease-out), при pulse - дальше
«дыхание» 1.2с/цикл от яркости 1.0 до 0.35 и обратно («пик-пик-пик»),
light_off() - плавное гашение до полного «off». В 1.0.6 LED статусом вообще
не управлялся.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme

_STATES = {
    "off": theme.MUTED,
    "busy": theme.ACCENT,
    "ok": theme.ACCENT2,
    "warn": theme.WARN,  # пинг-проверка (по просьбе)
    "err": theme.DANGER,
}

_TICK_MS = 33          # ~30 кадров/с - глазом гладко
_RAMP_S = 0.6          # длительность включения/гашения
_PULSE_PERIOD_S = 1.2  # полный цикл «пик»
_PULSE_MIN = 0.35      # яркость в нижней точке пульсации


class Led(QWidget):
    def __init__(self, diameter: int = 10, state: str = "off", parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._state = state if state in _STATES else "off"
        self._brightness = 1.0  # 1.0 = «как нарисовано», 0.0 = погашен
        self._fade_from = 1.0  # яркость, с которой началось гашение
        self._pulse = False
        self._fading: str | None = None  # 'in' | 'out' | None
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ---- мгновенное состояние (как в 1.0.6) -------------------------------
    def set_state(self, state: str) -> None:
        if state in _STATES and state != self._state:
            self._state = state
            self.update()

    def state(self) -> str:
        return self._state

    # ---- плавное включение/гашение ----------------------------------------
    def light_up(self, state: str = "ok", pulse: bool = True) -> None:
        """Плавно загореться: fade-in, затем (pulse) непрерывный «пик-пик».

        Начинается с нуля - каждый раз видимое «загоралось не резко».
        """
        if state in _STATES:
            self._state = state
        self._pulse = pulse
        self._fading = "in"
        self._phase = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def light_off(self) -> None:
        """Плавно угаснуть (пульсация прекращается, финал - состояние off)."""
        self._pulse = False
        self._fading = "out"
        self._fade_from = self._brightness  # гаснем с текущей яркости
        self._phase = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def is_lit(self) -> bool:
        """Горит/горел: яркость > 0 (погашенный fade-out'ом = False)."""
        return self._brightness > 0.0

    # ---- таймер анимации ---------------------------------------------------
    def _tick(self) -> None:
        t = time.monotonic()
        k = (t - self._phase) / _RAMP_S
        if self._fading == "in":
            if k >= 1.0:
                self._brightness = 1.0
                if self._pulse:
                    self._fading = None
                    self._phase = t  # старт пульсации с пика
                else:
                    # дошли до полной яркости - дальше горим ровно
                    self._fading = None
                    self._brightness = 1.0
                    self._timer.stop()
            else:
                # ease-out: быстро нарастает в начале, мягко коснувшись пика
                self._brightness = 1.0 - (1.0 - k) ** 2
        elif self._fading == "out":
            if k >= 1.0:
                self._brightness = 0.0
                self._fading = None
                self._state = "off"
                self._timer.stop()
            else:
                self._brightness = self._fade_from * (1.0 - k)
        elif self._pulse and self._state != "off":
            # дыхание: cos - в нуле цикла пик (1.0), в середине - спад до 0.35
            u = ((t - self._phase) % _PULSE_PERIOD_S) / _PULSE_PERIOD_S
            self._brightness = _PULSE_MIN + (1.0 - _PULSE_MIN) * (
                0.5 + 0.5 * math.cos(2.0 * math.pi * u)
            )
        else:
            self._timer.stop()  # фаз нет - таймер не нужен
        self.update()

    # ---- paint -------------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = self.width()
        b = self._brightness
        if b >= 1.0:
            c = _STATES[self._state]
        else:
            # цвет между «погашенным» MUTED и цветом состояния
            off = theme.MUTED
            c0 = _STATES[self._state]
            c = QColor(
                round(off.red() + (c0.red() - off.red()) * b),
                round(off.green() + (c0.green() - off.green()) * b),
                round(off.blue() + (c0.blue() - off.blue()) * b),
            )

        glow = QRadialGradient(QPointF(d / 2, d / 2), (d + 4) / 2)
        glow.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), round(150 * b)))
        glow.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(-2, -2, d + 4, d + 4))

        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, d - 2, d - 2))

        hi = max(2.0, (d - 2) * 0.4)
        p.setBrush(QColor(255, 255, 255, round(160 * b)))
        p.drawEllipse(QRectF(2, 2, hi, hi))
