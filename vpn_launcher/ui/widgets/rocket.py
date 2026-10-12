# -*- coding: utf-8 -*-
"""Плашка-ракета «DPI»: кнопка обхода, приклеенная к правому краю окна.

Просьба 12.10.2026: кнопку «Обход DPI» убрать из интерфейса - вместо неё
ракета, которая торчит с правого края окна, под ней подпись DPI. Живёт
в отдельном frameless-окне (дочерним к главному не делаем: ребёнок не
может вылезать за границы родителя - обрезался бы), ездит за главным
окном (window.py: moveEvent/showEvent -> attach_to), гаснет при
сворачивании. Поведение прежнее: ЛКМ - вкл/выкл, ПКМ - автоподбор;
когда обход работает - рамка, ореол и подпись горят зелёным.

Ракета - векторная (как GameButton/Led, без эмодзи: глиф не у всех
шрифтов есть): светлый корпус, циан-иллюминатор (ACCENT), пламя
зелёное (ACCENT2), пока обход работает, тусклое - когда нет.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QEnterEvent, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtGui import QPainterPath, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme

W, H = 64, 92       # размер плашки целиком
GLUE_PX = 14        # сколько px перекрывает окно (ровно ширина поля)
TOP_PX = 300        # отступ сверху от верха главного окна


class RocketButton(QWidget):
    """Отдельное прозрачное окно с ракетой; clicked = ЛКМ, ПКМ = меню."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(W, H)
        self.setToolTip("ЛКМ - вкл/выкл обхода, ПКМ - подобрать заново")
        # ПКМ = явный повторный подбор (как у старой кнопки «Обход DPI»)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._active = False
        self._hover = False
        self._down = False
        self._caps = theme.f_caps()

    # ---- координаты (главное окно ставит) --------------------------------
    def attach_to(self, x: int, y: int, win_w: int) -> None:
        """Приклеить к правому краю главного окна в (x, y) шириной win_w."""
        self.move(x + win_w - GLUE_PX, y + TOP_PX)

    def set_active(self, on: bool) -> None:
        """Обход запущен: зелёная рамка/ореол/подпись."""
        if on != self._active:
            self._active = on
            self.update()

    def is_active(self) -> bool:
        return self._active

    # ---- мышь --------------------------------------------------------------
    def enterEvent(self, e: QEnterEvent) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self._down = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._down:
            self._down = False
            self.update()
            inside = QRectF(0, 0, self.width(), self.height()).contains(
                e.position()
            )
            if inside and self.isEnabled():
                self.clicked.emit()
        super().mouseReleaseEvent(e)

    # ---- paint --------------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        on = self.isEnabled()
        active = on and self._active

        if active:  # мягкий зелёный ореол, пока обход работает
            glow = QRadialGradient(QPointF(w / 2, h / 2), (w + h) / 4)
            halo = QColor(theme.ACCENT2)
            halo.setAlpha(70)
            glow.setColorAt(0.0, halo)
            halo.setAlpha(0)
            glow.setColorAt(1.0, halo)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(-6, -6, w + 12, h + 12))

        if not on:
            top, bottom, br = (23, 26, 34), (19, 21, 28), (40, 44, 56)
        elif self._hover:
            top, bottom, br = (31, 37, 50), (25, 29, 40), (72, 82, 108)
        else:
            top, bottom, br = (27, 31, 42), (21, 24, 32), (46, 52, 68)
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(*top))
        grad.setColorAt(1.0, QColor(*bottom))
        p.setBrush(grad)
        p.setPen(QPen(QColor(theme.ACCENT2) if active else QColor(*br),
                      1.4 if active else 1.0))
        p.drawRoundedRect(QRectF(1.5, 1.5, w - 3, h - 3), 16, 16)

        self._paint_rocket(p, on, active)

        p.setFont(self._caps)
        if active:
            p.setPen(QColor(theme.ACCENT2))
        elif on:
            p.setPen(QColor(230, 234, 242) if self._hover else theme.TEXT_DIM)
        else:
            p.setPen(theme.MUTED)
        p.drawText(QRectF(0, 50, w, 30), Qt.AlignmentFlag.AlignCenter, "DPI")

    def _paint_rocket(self, p: QPainter, on: bool, active: bool) -> None:
        """Векторная ракета в стиле UI (светлый корпус, циан-иллюминатор,
        зелёное пламя при работающем обходе; всё - как виджеты рисуют)."""
        outline = QPen(QColor(23, 27, 36), 1.0)
        p.setPen(outline)
        if on:
            body_hi, body_lo = QColor(202, 208, 220), QColor(118, 126, 144)
        else:
            body_hi, body_lo = QColor(96, 102, 118), QColor(60, 66, 82)

        # пламя (за корпусом)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT2) if active else QColor(74, 82, 100))
        fp = QPainterPath()
        fp.moveTo(29.5, 36)
        fp.quadTo(32, 43 if active else 40, 34.5, 36)
        fp.closeSubpath()
        p.drawPath(fp)

        # плавники
        p.setPen(outline)
        p.setBrush(body_lo)
        p.drawPolygon(QPolygonF([QPointF(26, 25), QPointF(19, 37), QPointF(26, 34)]))
        p.drawPolygon(QPolygonF([QPointF(38, 25), QPointF(45, 37), QPointF(38, 34)]))

        # корпус: нос-конус + цилиндр со скруглым дном
        body = QPainterPath()
        body.moveTo(32, 7)
        body.cubicTo(35.5, 12, 38, 17, 38, 22)
        body.lineTo(38, 32)
        body.quadTo(38, 36, 34, 36)
        body.lineTo(30, 36)
        body.quadTo(26, 36, 26, 32)
        body.lineTo(26, 22)
        body.cubicTo(26, 17, 28.5, 12, 32, 7)
        body.closeSubpath()
        bg = QLinearGradient(0, 7, 0, 36)
        bg.setColorAt(0.0, body_hi)
        bg.setColorAt(1.0, body_lo)
        p.setBrush(bg)
        p.drawPath(body)

        # иллюминатор
        p.setBrush(QColor(theme.ACCENT) if on else theme.MUTED)
        p.setPen(QPen(QColor(23, 27, 36), 1.2))
        p.drawEllipse(QPointF(32, 20), 3.2, 3.2)
