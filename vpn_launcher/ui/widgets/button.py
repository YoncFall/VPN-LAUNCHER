# -*- coding: utf-8 -*-
"""Игровая кнопка. Порт New-GameButton (theme.ps1:724-782).

Виды (kind):
  ghost   - тёмная с градиентом (27,31,42)->(21,24,32), радиус 8
  accent  - главная голубая (46,226,255)->(0,160,205), радиус 9
  danger  - красная 'ОТКЛЮЧИТЬ' (255,104,132)->(196,48,78), радиус 9
  capmin / capclose - квадратики шапки 34x30, радиус 7, глифы minus/cross
Выключенное состояние рисуется как ghost с тусклым текстом (как в 1.0.6).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme

# kind -> состояние -> (top, bottom, border, text)
_SKINS: dict[str, dict[str, tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]]] = {
    "ghost": {
        "normal": ((27, 31, 42), (21, 24, 32), (46, 52, 68), (176, 184, 200)),
        "hover": ((31, 37, 50), (25, 29, 40), (72, 82, 108), (230, 234, 242)),
        "down": ((17, 20, 28), (15, 17, 24), (46, 52, 68), (132, 142, 162)),
    },
    "accent": {
        "normal": ((46, 226, 255), (0, 160, 205), (0, 205, 245), (3, 26, 34)),
        "hover": ((96, 240, 255), (0, 176, 214), (120, 246, 255), (3, 26, 34)),
        "down": ((0, 140, 178), (0, 110, 148), (0, 190, 230), (3, 26, 34)),
    },
    "danger": {
        "normal": ((255, 104, 132), (196, 48, 78), (255, 92, 122), (42, 4, 12)),
        "hover": ((255, 130, 156), (222, 64, 96), (255, 150, 174), (42, 4, 12)),
        "down": ((196, 48, 78), (150, 34, 58), (220, 70, 100), (42, 4, 12)),
    },
    "capmin": {
        "normal": ((18, 21, 29), (16, 19, 26), (46, 52, 68), (150, 158, 176)),
        "hover": ((33, 38, 51), (28, 32, 43), (90, 100, 128), (230, 234, 242)),
        "down": ((18, 21, 29), (16, 19, 26), (46, 52, 68), (150, 158, 176)),
    },
    "capclose": {
        "normal": ((18, 21, 29), (16, 19, 26), (46, 52, 68), (150, 158, 176)),
        "hover": ((70, 20, 30), (58, 14, 24), (255, 77, 109), (255, 77, 109)),
        "down": ((18, 21, 29), (16, 19, 26), (46, 52, 68), (150, 158, 176)),
    },
}
_DISABLED_TEXT = (74, 81, 98)


class GameButton(QWidget):
    clicked = Signal()

    def __init__(
        self,
        text: str = "",
        kind: str = "ghost",
        radius: int = 8,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._kind = kind if kind in _SKINS else "ghost"
        self._radius = radius
        self._hover = False
        self._down = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---- text -------------------------------------------------------------
    def set_text(self, text: str) -> None:
        """Порт Set-BtnText (theme.ps1:676-679): смена подписи с перерисовкой."""
        self._text = text
        self.update()

    # ---- geometry --------------------------------------------------------
    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        return QSize(120, 34)

    # ---- state -----------------------------------------------------------
    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self._down = False
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        inside = self.rect().contains(e.position().toPoint())
        if self._down != inside:
            self._down = inside
            self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        was = self._down
        self._down = False
        self.update()
        if was and self.rect().contains(e.position().toPoint()) and self.isEnabled():
            self.clicked.emit()

    # ---- painting --------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        state = "down" if self._down and self.isEnabled() else (
            "hover" if self._hover and self.isEnabled() else "normal"
        )
        top, bot, border, txt = _SKINS[self._kind][state]
        if not self.isEnabled():
            top, bot, border = _SKINS["ghost"]["normal"][:3]
            txt = _DISABLED_TEXT

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(*top))
        grad.setColorAt(1.0, QColor(*bot))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(*border), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        # тонкий блик сверху (theme.ps1:755-756)
        if state != "down":
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawLine(QPointF(4, 2), QPointF(w - 5, 2))

        if self._kind == "capclose":
            pen = QPen(QColor(*txt), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(11, 9), QPointF(w - 11, h - 9))
            p.drawLine(QPointF(w - 11, 9), QPointF(11, h - 9))
        elif self._kind == "capmin":
            pen = QPen(QColor(*txt), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(9, h / 2), QPointF(w - 9, h / 2))
        else:
            p.setPen(QColor(*txt))
            p.setFont(theme.f_btn())
            p.drawText(
                QRectF(6, 0, w - 12, h),
                int(Qt.AlignmentFlag.AlignCenter)
                | int(Qt.TextFlag.TextSingleLine)
                | int(Qt.TextFlag.TextDontClip),
                self._text,
            )
