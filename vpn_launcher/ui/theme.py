# -*- coding: utf-8 -*-
"""Палитра и шрифты. Порт theme.ps1:612-645 ($script:T и Get-GameFont)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# ---- палитра «Cyber Purple» (макет GPT, 13.10.2026) -----------------------
# Цвета дословно из утверждённого HTML-макета: тёмный фон #0a0d12, секции
# градиентом #151c26->#0f141c с фиолетовой рамкой #342d4d, акцент
# фиолетовый #a783ff, успех — зелёный #51e49b, ошибка — #ff6175.
BG = QColor(9, 11, 15)          # фон окна #0a0d12
BG2 = QColor(14, 17, 24)        # верх градиента окна (чуть светлее)
CARD = QColor(21, 28, 38)       # секция сверху #151c26
CARD_HI = QColor(15, 20, 28)    # секция снизу #0f141c
LINE = QColor(52, 45, 77)       # рамки секций #342d4d
LINE_HI = QColor(84, 70, 122)   # рамка hover #544679
FIELD = QColor(11, 16, 23)      # поля и списки #0b1017
TEXT = QColor(232, 237, 245)    # #e8edf5
TEXT_DIM = QColor(129, 141, 160)  # #818da0
HEAD = QColor(197, 207, 221)    # #c5cfdd заголовки секций
ACCENT = QColor(167, 131, 255)  # #a783ff (Cyber Purple)
ACCENT_D = QColor(125, 86, 226)
ACCENT2 = QColor(81, 228, 155)  # #51e49b успех/лампа DPI
DANGER = QColor(255, 97, 117)   # #ff6175
WARN = QColor(232, 196, 108)    # #e8c46c
MUTED = QColor(102, 115, 134)   # погашенная лампа #667386

# ---- рамки контролов ----
BORDER = QColor(48, 59, 74)     # #303b4a
BORDER_HOVER = QColor(70, 85, 106)  # #46556a
BORDER_FOCUS = QColor(167, 131, 255)  # фокус — акцентный фиолет
PLACEHOLDER = QColor(93, 105, 123)  # #5d697b

# ---- скроллбар списков ----
SB_BG = QColor(11, 16, 23)
SB_TRACK = QColor(24, 29, 40)
SB_THUMB_TOP = QColor(96, 82, 132)
SB_THUMB_BOT = QColor(58, 50, 84)

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


# f_btn = 10px bold (как в макете; Bahnschrift округляет 8/8.5pt до одних
# же 11px, поэтому берём пиксельный размер) - тексты влезают в равные доли
def f_btn() -> QFont:
    f = QFont(family())
    f.setPixelSize(10)
    f.setBold(True)
    return f


def f_caps() -> QFont:
    return font(8, bold=True)


def f_mono() -> QFont:
    return font(8.5)


def f_row() -> QFont:
    return font(9)
