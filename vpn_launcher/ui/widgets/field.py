# -*- coding: utf-8 -*-
"""Тёмное поле ввода. Порт GameField (theme.ps1:54-130, New-GameField:1000).

Заливка (19,22,30), рамка 58,66,86 -> 96,108,138 (hover) -> 0,200,240 (focus),
плейсхолдер (110,118,136), шрифт FBody 9, padding 12.

ВАЖНО: QSS собирается лениво (в __init__), а не на уровне модуля -
theme.family() трогает QFontDatabase, которому нужен уже созданный
QApplication, иначе Qt падает (qFatal) ещё до запуска окна.
"""
from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLineEdit

from vpn_launcher.ui import theme

_RADIUS = 7


def _qss() -> str:
    return f"""
QLineEdit {{
    background-color: #13161E;
    border: 1px solid #3A4256;
    border-radius: {_RADIUS}px;
    padding: 0 12px;
    color: #E6EAF2;
    font: 9pt "{theme.family()}";
    selection-background-color: #0096BE;
    selection-color: #031A22;
}}
QLineEdit:hover {{ border-color: #606C8A; }}
QLineEdit:focus {{ border-color: #00C8F0; }}
"""


class GameField(QLineEdit):
    def __init__(self, text: str = "", placeholder: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setFont(theme.f_body())
        self.setStyleSheet(_qss())
        if placeholder:
            self.setPlaceholderText(placeholder)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, theme.PLACEHOLDER)
        self.setPalette(pal)
