# -*- coding: utf-8 -*-
"""Шапка окна. Порт Install-GameTitleBar (theme.ps1:1160-1244), вид по макету 13.10.

- высота 62 (макет .titlebar min-height: 62);
- фон-градиент (16,21,29) -> (13,17,24) со скруглённым верхом (радиус 11:
  рамка окна остаётся видимой по периметру);
- нижняя граница Line на y=h-1;
- brand-mark: скруглённый квадрат 25x25 с фиолетовой рамкой и векторным
  щитом-галкой (icons.py, без эмодзи);
- логотип 'VPN ЛАУНЧЕР' (FLogo 17 Bold): фиолетовое свечение в три слоя
  (text-shadow из макета) + основной почти-белый текст;
- 'by YoncFall' (FSub) рядом с логотипом;
- LED + квадратики capmin/capclose;
- перетаскивание окна за пустые места.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from vpn_launcher.ui import icons, theme
from vpn_launcher.ui.widgets.led import Led
from vpn_launcher.ui.widgets.button import GameButton

LOGO = "VPN ЛАУНЧЕР"
BYLINE = "by YoncFall"

_MARK = 25      # размер brand-mark (макет .brand-mark 25x25)
_MARK_X = 14


class TitleBar(QWidget):
    HEIGHT = 62
    closed = Signal()
    minimize_requested = Signal()

    def __init__(self, width: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setFixedWidth(width)
        self._drag: QPointF | None = None

        self.led = Led(10, "off", self)
        self.led.move(width - 116, (self.HEIGHT - 10) // 2)

        self.btn_min = GameButton("", "capmin", 7, self)
        self.btn_min.setGeometry(width - 80, 16, 34, 30)
        self.btn_close = GameButton("", "capclose", 7, self)
        self.btn_close.setGeometry(width - 42, 16, 34, 30)
        self.btn_min.clicked.connect(self.minimize_requested)
        self.btn_close.clicked.connect(self.closed)

    # ---- drag ------------------------------------------------------------
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._drag = e.globalPosition().toPoint() - win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None

    # ---- paint -----------------------------------------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # фон со скруглённым верхом (inset 1px — рамка окна видна по краю)
        r = 11
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(16, 21, 29))
        bg.setColorAt(1.0, QColor(13, 17, 24))
        path = QPainterPath()
        path.moveTo(1, h)
        path.lineTo(1, 1 + r)
        path.arcTo(QRectF(1, 1, 2 * r, 2 * r), 180, -90)
        path.lineTo(w - 1 - r, 1)
        path.arcTo(QRectF(w - 1 - 2 * r, 1, 2 * r, 2 * r), 90, -90)
        path.lineTo(w - 1, h)
        path.closeSubpath()
        p.fillPath(path, bg)

        # нижняя граница
        p.setPen(QPen(theme.LINE, 1))
        p.drawLine(1, h - 1, w - 1, h - 1)

        # brand-mark: скруглённый квадрат с векторным щитом
        my = (h - _MARK) // 2
        box = QRectF(_MARK_X + 0.5, my + 0.5, _MARK - 1, _MARK - 1)
        p.setPen(QPen(QColor(167, 131, 255, 90), 1))
        p.setBrush(QColor(167, 131, 255, 34))
        p.drawRoundedRect(box, 7, 7)
        icons.paint(
            p,
            "shield_check",
            QRectF(_MARK_X + 5, my + 5, 15, 15),
            QColor(188, 162, 255),
        )

        # логотип: три слоя фиолетового свечения + основной текст (макет)
        p.setFont(theme.f_logo())
        fm = p.fontMetrics()
        x0 = _MARK_X + _MARK + 9
        w_main = fm.horizontalAdvance(LOGO)
        ty = (h - 22) // 2
        flags = int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter) | int(
            Qt.TextFlag.TextSingleLine
        ) | int(Qt.TextFlag.TextDontClip)
        for dx, dy, alpha, c in (
            (3, 2, 60, (141, 77, 255)),
            (2, 1, 120, (183, 138, 255)),
            (1, 1, 170, (196, 160, 255)),
        ):
            p.setPen(QColor(*c, alpha))
            p.drawText(QRectF(x0 + dx, ty + dy, w_main + 8, 22), flags, LOGO)
        p.setPen(QColor(243, 250, 255))
        p.drawText(QRectF(x0, ty, w_main + 8, 22), flags, LOGO)

        # byline
        p.setFont(theme.f_sub())
        p.setPen(QColor(174, 185, 202))
        p.drawText(
            QRectF(x0 + w_main + 10, (h - 14) // 2 + 3, 140, 14),
            flags,
            BYLINE,
        )
