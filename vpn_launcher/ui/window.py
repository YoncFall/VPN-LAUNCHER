# -*- coding: utf-8 -*-
"""Главное окно. Раскладка - точный порт VPN.ps1:84-222 (карточка 14,54,592x664).

Вид: тёмно-синий градиентный фон (Bg2->Bg), скруглённые углы 12 (как
Install-GameCorners), шапка с неоновым логотипом, градиентные линии
(кант шапки, подчёркивание, полоска карточки, разделители с акцентной
точкой). Списки (NeonList в GameFrame, inset 3 как New-GameListBox) и
пикер (GamePicker) - этап 4; логика - на этапах 2 и 5.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from vpn_launcher import __version__
from vpn_launcher.paths import LOG_FILE
from vpn_launcher.ui import theme
from vpn_launcher.ui.widgets.button import GameButton
from vpn_launcher.ui.widgets.card import GameCard
from vpn_launcher.ui.widgets.divider import Divider
from vpn_launcher.ui.widgets.field import GameField
from vpn_launcher.ui.widgets.frame import GameFrame
from vpn_launcher.ui.widgets.led import Led
from vpn_launcher.ui.widgets.neon_list import NeonList
from vpn_launcher.ui.widgets.picker import GamePicker
from vpn_launcher.ui.widgets.radio import GameRadio
from vpn_launcher.ui.widgets.title_bar import TitleBar

WIN_W, WIN_H = 620, 726
WIN_RADIUS = 12  # Install-GameCorners (theme.ps1:1253)


def _label(
    parent: QWidget,
    text: str,
    x: int,
    y: int,
    w: int,
    h: int,
    color: QColor,
    font,
    align: str = "left",
) -> QLabel:
    """Порт New-GameLabel/New-GameCaption (theme.ps1:1016-1047)."""
    l = QLabel(text, parent)
    l.setGeometry(x, y, w, h)
    l.setFont(font)
    l.setStyleSheet(f"color: {color.name()}; background: transparent;")
    a = Qt.AlignmentFlag.AlignVCenter
    if align == "right":
        a |= Qt.AlignmentFlag.AlignRight
    elif align == "center":
        a |= Qt.AlignmentFlag.AlignHCenter
    else:
        a |= Qt.AlignmentFlag.AlignLeft
    l.setAlignment(a)
    return l


class MainWindow(QWidget):
    mode_changed = Signal(str)  # 'tun' | 'proxy' - подключение логики (этап 5)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VPN LAUNCHER")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(WIN_W, WIN_H)
        self._drag: QPointF | None = None
        self._apply_mask()
        self._build()

    # ---- chrome ----------------------------------------------------------
    def _apply_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, WIN_W, WIN_H), WIN_RADIUS, WIN_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        grad = QLinearGradient(0, 0, 0, WIN_H)
        grad.setColorAt(0.0, theme.BG2)
        grad.setColorAt(1.0, theme.BG)
        p.fillRect(QRectF(0, 0, WIN_W, WIN_H), grad)

    # ---- construction ----------------------------------------------------
    def _build(self) -> None:
        bar = TitleBar(WIN_W, self)
        bar.move(0, 0)
        bar.closed.connect(self.close)
        bar.minimize_requested.connect(self.showMinimized)
        self.titlebar = bar

        card = GameCard(14, self)
        card.setGeometry(14, 54, 592, 664)
        self.card = card

        # --- ПОДПИСКА (VPN.ps1:110-118) ---
        _label(card, "ПОДПИСКА", 18, 12, 300, 16, theme.TEXT_DIM, theme.f_caps())
        self.field_sub = GameField(
            "", "вставь ссылку на подписку (https://...)", card
        )
        self.field_sub.setGeometry(18, 30, 556, 30)

        self.btn_load = GameButton("Загрузить подписку", "ghost", 8, card)
        self.btn_load.setGeometry(18, 66, 208, 34)
        self.btn_ping = GameButton("Проверить пинг", "ghost", 8, card)
        self.btn_ping.setGeometry(232, 66, 150, 34)
        self.btn_log = GameButton("Открыть лог", "ghost", 8, card)
        self.btn_log.setGeometry(388, 66, 186, 34)
        self.btn_log.clicked.connect(self._open_log)

        div1 = Divider(card)
        div1.setGeometry(18, 106, 556, 2)

        # --- СЕРВЕРЫ (VPN.ps1:163-172) ---
        _label(card, "СЕРВЕРЫ", 18, 118, 200, 16, theme.TEXT_DIM, theme.f_caps())
        # хинт на строке подписи: в коде 1.0.6 он (300,136) перекрывался с
        # колонкой ПИНГ (480..561) - визуальная коллизия, здесь исправлена
        _label(
            card, "выбери сервер · пусто - авто-тест всех",
            300, 118, 274, 16, theme.TEXT_DIM, theme.f_sub(), "right",
        )
        _label(card, "ПРОТОКОЛ", 18, 136, 57, 14, theme.TEXT_DIM, theme.f_caps(), "right")
        _label(card, "СЕРВЕР", 81, 136, 300, 14, theme.TEXT_DIM, theme.f_caps())
        _label(card, "ПИНГ", 480, 136, 81, 14, theme.TEXT_DIM, theme.f_caps(), "right")
        self.frame_servers = GameFrame(10, card)
        self.frame_servers.setGeometry(18, 152, 556, 178)
        # список серверов: пинг-колонки, как New-GameListBox -Ping (VPN.ps1:170)
        self.list_servers = NeonList(ping=True, parent=self.frame_servers)
        self.list_servers.setGeometry(3, 3, 556 - 6, 178 - 6)

        div2 = Divider(card)
        div2.setGeometry(18, 340, 556, 2)

        # --- РЕЖИМ (VPN.ps1:177-185) ---
        _label(card, "РЕЖИМ", 18, 352, 200, 16, theme.TEXT_DIM, theme.f_caps())
        self.radio_tun = GameRadio("Весь трафик - TUN (нужен админ)", True, card)
        self.radio_tun.setGeometry(18, 371, 270, 36)
        self.radio_proxy = GameRadio("Системный прокси", False, card)
        self.radio_proxy.setGeometry(294, 371, 280, 36)
        self.radio_tun.toggled.connect(lambda: self._select_mode("tun"))
        self.radio_proxy.toggled.connect(lambda: self._select_mode("proxy"))

        div3 = Divider(card)
        div3.setGeometry(18, 412, 556, 2)

        # --- ИСКЛЮЧЕНИЯ (VPN.ps1:190-205) ---
        _label(card, "ИСКЛЮЧЕНИЯ", 18, 424, 320, 16, theme.TEXT_DIM, theme.f_caps())
        _label(
            card, "игры, Steam и античиты исключены автоматически",
            300, 424, 274, 16, theme.TEXT_DIM, theme.f_sub(), "right",
        )
        self.frame_excl = GameFrame(10, card)
        self.frame_excl.setGeometry(18, 444, 260, 84)
        # список исключений: текстовый режим (VPN.ps1:193)
        self.list_excl = NeonList(ping=False, parent=self.frame_excl)
        self.list_excl.setGeometry(3, 3, 260 - 6, 84 - 6)
        self.picker_proc = GamePicker("выбери процесс или впиши имя .exe", card)
        self.picker_proc.setGeometry(288, 444, 286, 30)

        self.btn_add = GameButton("Добавить", "ghost", 8, card)
        self.btn_add.setGeometry(288, 478, 286, 30)
        self.btn_del = GameButton("Удалить", "ghost", 8, card)
        self.btn_del.setGeometry(288, 512, 138, 30)
        self.btn_clr = GameButton("Очистить", "ghost", 8, card)
        self.btn_clr.setGeometry(426, 512, 148, 30)
        _label(
            card,
            "Список процессов обновляется при запуске. В поле можно вписать имя .exe вручную.",
            18, 550, 556, 16, theme.TEXT_DIM, theme.f_sub(),
        )

        div4 = Divider(card)
        div4.setGeometry(18, 574, 556, 2)

        # --- подключение (VPN.ps1:210-222) ---
        self.btn_connect = GameButton("ПОДКЛЮЧИТЬСЯ", "accent", 9, card)
        self.btn_connect.setGeometry(18, 586, 288, 42)
        self.btn_disconnect = GameButton("ОТКЛЮЧИТЬ", "danger", 9, card)
        self.btn_disconnect.setGeometry(316, 586, 118, 42)
        self.btn_disconnect.setEnabled(False)
        self.btn_testcfg = GameButton("Проверить конфиг", "ghost", 9, card)
        self.btn_testcfg.setGeometry(444, 586, 130, 42)

        self.led_status = Led(10, "off", card)
        self.led_status.setGeometry(18, 640, 10, 10)
        self.lbl_status = _label(
            card,
            "Готов - оболочка, логика на этапах 2-5",
            36, 636, 250, 18, theme.TEXT, theme.f_body(),
        )
        self.lbl_egress = _label(
            card, "", 300, 636, 274, 18, theme.TEXT_DIM, theme.f_mono(), "right"
        )

    # ---- behavior --------------------------------------------------------
    def _select_mode(self, mode: str) -> None:
        self.radio_tun.set_checked(mode == "tun")
        self.radio_proxy.set_checked(mode == "proxy")
        self.mode_changed.emit(mode)

    def _open_log(self) -> None:
        """Порт VPN.ps1:158 - открываем журнал в блокноте, если он есть."""
        if LOG_FILE.exists():
            subprocess.Popen(["notepad.exe", str(LOG_FILE)])

    # ---- drag (за пустые места окна, как Install-GameCorners) -----------
    def mousePressEvent(self, e) -> None:  # noqa: N802
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

    # VPN_SHOT=<path>: снять окно и выйти (визуальные сверки с 1.0.6)
    shot = os.environ.get("VPN_SHOT")
    if shot:
        from PySide6.QtCore import QTimer

        def _grab() -> None:
            win.grab().save(shot)
            app.quit()

        QTimer.singleShot(700, _grab)

    return app.exec()
