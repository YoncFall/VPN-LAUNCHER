# -*- coding: utf-8 -*-
"""Игровая кнопка. Порт New-GameButton (theme.ps1:724-782), вид по макету 13.10.

Виды (kind):
   ghost   - тёмная как секции (#171e28), рамка #303b4a, радиус 6
   accent  - главная фиолетовая «ПОДКЛЮЧИТЬСЯ» (градиент #7651c5->#51369a)
   danger  - «ОТКЛЮЧИТЬ»: тёмно-красная (#291a22) с розовым текстом (макет)
   capmin / capclose - квадратики шапки, глифы minus/cross
Опция icon: векторная иконка слева от текста (icons.py, без эмодзи).
Выключенное состояние рисуется как ghost с тусклым текстом (как в 1.0.6).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import theme
from vpn_launcher.ui import icons

# kind -> состояние -> (top, bottom, border, text)
_SKINS: dict[str, dict[str, tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]]] = {
    "ghost": {
        "normal": ((23, 30, 40), (23, 30, 40), (48, 59, 74), (185, 197, 213)),
        "hover": ((32, 42, 56), (32, 42, 56), (70, 85, 106), (232, 237, 245)),
        "down": ((17, 22, 30), (17, 22, 30), (48, 59, 74), (129, 141, 160)),
    },
    "accent": {
        "normal": ((118, 81, 197), (81, 54, 154), (140, 106, 214), (255, 255, 255)),
        "hover": ((133, 94, 214), (96, 63, 172), (167, 131, 255), (255, 255, 255)),
        "down": ((96, 66, 160), (66, 44, 120), (140, 106, 214), (232, 237, 245)),
    },
    "danger": {
        "normal": ((45, 28, 37), (41, 26, 34), (96, 48, 59), (242, 138, 153)),
        "hover": ((58, 32, 43), (58, 32, 43), (163, 75, 91), (255, 172, 184)),
        "down": ((35, 20, 28), (35, 20, 28), (96, 48, 59), (217, 106, 124)),
    },
    "capmin": {
        "normal": ((16, 21, 29), (16, 21, 29), (52, 45, 77), (150, 158, 176)),
        "hover": ((33, 38, 51), (28, 32, 43), (90, 100, 128), (230, 234, 242)),
        "down": ((16, 21, 29), (16, 21, 29), (52, 45, 77), (150, 158, 176)),
    },
    "capclose": {
        "normal": ((16, 21, 29), (16, 21, 29), (52, 45, 77), (150, 158, 176)),
        "hover": ((70, 20, 30), (58, 14, 24), (255, 97, 117), (255, 97, 117)),
        "down": ((16, 21, 29), (16, 21, 29), (52, 45, 77), (150, 158, 176)),
    },
}
_DISABLED_TEXT = (84, 92, 110)
_ICON = 13   # размер иконки в кнопке
_ICON_GAP = 5


class GameButton(QWidget):
    clicked = Signal()

    def __init__(
        self,
        text: str = "",
        kind: str = "ghost",
        radius: int = 8,
        parent=None,
        *,
        icon: str = "",
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._kind = kind if kind in _SKINS else "ghost"
        self._radius = radius
        self._icon = icon
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
            text_x = 6.0
            if self._icon:
                # векторная иконка слева от текста (макет, без эмодзи)
                icons.paint(
                    p,
                    self._icon,
                    QRectF(8, (h - _ICON) / 2.0, _ICON, _ICON),
                    QColor(*txt),
                )
                text_x = 6.0 + _ICON + _ICON_GAP
            p.setPen(QColor(*txt))
            p.setFont(theme.f_btn())
            p.drawText(
                QRectF(text_x, 0, w - text_x - 6, h),
                int(Qt.AlignmentFlag.AlignCenter)
                | int(Qt.TextFlag.TextSingleLine)
                | int(Qt.TextFlag.TextDontClip),
                self._text,
            )
