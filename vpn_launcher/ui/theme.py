# -*- coding: utf-8 -*-
"""Палитра и шрифты. Порт theme.ps1:612-645 ($script:T и Get-GameFont)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# ---- $script:T (theme.ps1:612-626) ----
BG = QColor(12, 14, 19)
BG2 = QColor(18, 21, 29)
CARD = QColor(24, 27, 37)
CARD_HI = QColor(33, 38, 51)
LINE = QColor(46, 52, 68)
LINE_HI = QColor(72, 82, 108)
FIELD = QColor(19, 22, 30)
TEXT = QColor(230, 234, 242)
TEXT_DIM = QColor(132, 142, 162)
ACCENT = QColor(0, 216, 255)
ACCENT_D = QColor(0, 150, 190)
ACCENT2 = QColor(0, 240, 168)
DANGER = QColor(255, 77, 109)
WARN = QColor(255, 196, 84)
MUTED = QColor(58, 64, 80)

# ---- рамки контролов (theme.ps1:54-57, 131-132) ----
BORDER = QColor(58, 66, 86)
BORDER_HOVER = QColor(96, 108, 138)
BORDER_FOCUS = QColor(0, 200, 240)
PLACEHOLDER = QColor(110, 118, 136)

# ---- скроллбар DarkListBox (theme.ps1:227-246) ----
SB_BG = QColor(15, 17, 24)
SB_TRACK = QColor(28, 32, 42)
SB_THUMB_TOP = QColor(78, 90, 116)
SB_THUMB_BOT = QColor(50, 58, 78)

_FAMILY: str | None = None


def family() -> str:
    """Bahnschrift, иначе Segoe UI (порт probe-логики Get-GameFont)."""
    global _FAMILY
    if _FAMILY is None:
        try:
            _FAMILY = "Bahnschrift" if "Bahnschrift" in QFontDatabase.families() else "Segoe UI"
        except RuntimeError:  # QFontDatabase требует QApplication; Bahnschrift есть на Win10/11
            _FAMILY = "Bahnschrift"
    return _FAMILY


def font(size: float, bold: bool = False) -> QFont:
    f = QFont(family())
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


# ---- набор шрифтов (theme.ps1:638-645) ----
def f_body() -> QFont:
    return font(9)


def f_head() -> QFont:
    return font(9.5, bold=True)


def f_logo() -> QFont:
    return font(17, bold=True)


def f_sub() -> QFont:
    return font(8)


def f_btn() -> QFont:
    return font(8.5, bold=True)


def f_caps() -> QFont:
    return font(8, bold=True)


def f_mono() -> QFont:
    return font(8.5)


def f_row() -> QFont:
    return font(9)
