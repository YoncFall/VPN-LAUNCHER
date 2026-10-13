# -*- coding: utf-8 -*-
"""Плашка-ракета «DPI»: кнопка обхода, приклеенная к правому краю окна.

Просьба 12.10.2026: кнопку «Обход DPI» убрать из интерфейса - вместо неё
ракета, которая торчит с правого края окна, под ней подпись DPI. Живёт
в отдельном frameless-окне (дочерним к главному не делаем: ребёнок не
может вылезать за границы родителя - обрезался бы), ездит за главным
окном (window.py: moveEvent/showEvent -> attach_to), гаснет при
сворачивании. Поведение прежнее: ЛКМ - вкл/выкл, ПКМ - автоподбор.

Вид (макет #rocket, 13.10): плоский левый край вплотную к рамке окна
(GLUE_PX=2), скруглены только правые углы (радиус 10); когда обход
работает - рамка, ореол и подпись горят фиолетовым (#b06aff), иначе
нейтральный тёмный (#17212e -> #101720). Ракета - векторная (без
эмодзи): светлый корпус, иллюминатор акцентный, пламя фиолетовое при
работающем обходе, тусклое - когда нет.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QEnterEvent, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtGui import QPainterPath, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme

W, H = 64, 92       # размер плашки целиком
GLUE_PX = 2         # сколько px перекрывает окно (макет: вплотную к краю)
TOP_PX = 388        # отступ сверху от верха главного окна (~51%, макет)

_ACTIVE = QColor(176, 106, 255)       # #b06aff рамка/ореол при работе обхода
_ACTIVE_TEXT = QColor(215, 181, 255)  # #d7b5ff подпись DPI
_ACTIVE_BG_TOP = QColor(48, 32, 71)   # #302047
_ACTIVE_BG_BOT = QColor(27, 20, 40)   # #1b1428


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

        if active:  # мягкий фиолетовый ореол, пока обход работает
            glow = QRadialGradient(QPointF(w / 2, h / 2), (w + h) / 4)
            halo = QColor(_ACTIVE)
            halo.setAlpha(70)
            glow.setColorAt(0.0, halo)
            halo.setAlpha(0)
            glow.setColorAt(1.0, halo)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(-6, -6, w + 12, h + 12))

        if active:  # вид макета #rocket.active
            top, bottom, br = (48, 32, 71), (27, 20, 40), (176, 106, 255)
        elif not on:
            top, bottom, br = (23, 33, 46), (16, 23, 32), (52, 66, 86)
        elif self._hover:
            top, bottom, br = (28, 40, 56), (20, 29, 40), (82, 113, 143)
        else:
            top, bottom, br = (23, 33, 46), (16, 23, 32), (52, 66, 86)
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(*top))
        grad.setColorAt(1.0, QColor(*bottom))

        # форма макета: плоский левый край (вплотную к окну), скруглены
        # только правые углы (радиус 10)
        rr = 10.0
        left, top_y, right, bot_y = 1.5, 1.5, w - 1.5, h - 1.5
        path = QPainterPath()
        path.moveTo(left, top_y)
        path.lineTo(right - rr, top_y)
        path.arcTo(QRectF(right - 2 * rr, top_y, 2 * rr, 2 * rr), 90, -90)
        path.lineTo(right, bot_y - rr)
        path.arcTo(QRectF(right - 2 * rr, bot_y - 2 * rr, 2 * rr, 2 * rr), 0, -90)
        path.lineTo(left, bot_y)
        p.setBrush(grad)
        p.setPen(QPen(QColor(*br), 1.4 if active else 1.0))
        p.fillPath(path, grad)
        p.drawPath(path)
        # левый край - отдельной линией (#40536b у макета)
        p.setPen(QPen(QColor(64, 83, 107), 1.0))
        p.drawLine(QPointF(left, top_y), QPointF(left, bot_y))

        self._paint_rocket(p, on, active)

        p.setFont(self._caps)
        if active:
            p.setPen(QColor(_ACTIVE_TEXT))
        elif on:
            p.setPen(QColor(199, 227, 255) if self._hover else theme.TEXT_DIM)
        else:
            p.setPen(theme.MUTED)
        p.drawText(QRectF(0, 50, w, 30), Qt.AlignmentFlag.AlignCenter, "DPI")

    def _paint_rocket(self, p: QPainter, on: bool, active: bool) -> None:
        """Векторная ракета в стиле UI (светлый корпус, акцентный иллюминатор,
        фиолетовое пламя при работающем обходе; всё - как виджеты рисуют)."""
        outline = QPen(QColor(23, 27, 36), 1.0)
        p.setPen(outline)
        if on:
            body_hi, body_lo = QColor(202, 208, 220), QColor(118, 126, 144)
        else:
            body_hi, body_lo = QColor(96, 102, 118), QColor(60, 66, 82)

        # пламя (за корпусом)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_ACTIVE) if active else QColor(74, 82, 100))
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
