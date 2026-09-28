# -*- coding: utf-8 -*-
"""Главное окно. Этап 0 — каркас (размер и титлбар как в версии 1.0.6).

Точная геометрия блоков, кнопок и списков переносится на этапе 3-4 из VPN.ps1.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vpn_launcher import __version__
from vpn_launcher.ui import theme

WIN_W, WIN_H = 620, 726  # как в VPN.ps1 (главное окно 1.0.6)
TITLEBAR_H = 58


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VPN LAUNCHER")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(WIN_W, WIN_H)
        self._drag: QPoint | None = None
        self._build()

    # ---- construction ----------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setFixedHeight(TITLEBAR_H)
        bar.setStyleSheet(f"background-color: {theme.BG2.name()};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 10, 0)
        lay.setSpacing(8)

        col = QVBoxLayout()
        col.setSpacing(0)
        title = QLabel("VPN LAUNCHER")
        title.setFont(theme.f_logo())
        title.setStyleSheet(f"color: {theme.TEXT.name()}; background: transparent;")
        sub = QLabel(f"Python edition - dev {__version__}")
        sub.setFont(theme.f_sub())
        sub.setStyleSheet(f"color: {theme.TEXT_DIM.name()}; background: transparent;")
        col.addWidget(title)
        col.addWidget(sub)

        close_btn = QPushButton("X")
        close_btn.setFixedSize(34, 34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFont(theme.f_btn())
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {theme.BG.name()};
                color: {theme.TEXT_DIM.name()};
                border: 1px solid {theme.LINE.name()};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {theme.DANGER.name()};
                color: {theme.TEXT.name()};
                border-color: {theme.DANGER.name()};
            }}
            """
        )
        close_btn.clicked.connect(self.close)

        lay.addLayout(col)
        lay.addStretch(1)
        lay.addWidget(close_btn)
        root.addWidget(bar)

        body = QLabel(
            "Этап 0: среда и каркас готовы.\n"
            "Дальше — ядро (тесты), окно и списки по образцу 1.0.6."
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setFont(theme.f_body())
        body.setStyleSheet(
            f"color: {theme.TEXT_DIM.name()}; background-color: {theme.BG.name()};"
        )
        root.addWidget(body, 1)

        self.setStyleSheet(f"background-color: {theme.BG.name()};")

    # ---- drag by titlebar (клики по QLabel всплывают сюда) ---------------
    def mousePressEvent(self, e) -> None:  # noqa: N802 (Qt API)
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("VPN LAUNCHER")
    app.setOrganizationName("yoncfall-tech")

    win = MainWindow()
    scr = app.primaryScreen().availableGeometry()
    win.move(scr.center().x() - WIN_W // 2, scr.center().y() - WIN_H // 2)
    win.show()
    return app.exec()
