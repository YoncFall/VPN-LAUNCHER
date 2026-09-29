# -*- coding: utf-8 -*-
"""Главное окно. Раскладка - точный порт VPN.ps1:84-222 (карточка 14,54,592x664).

Вид: тёмно-синий градиентный фон (Bg2->Bg), скруглённые углы 12 (как
Install-GameCorners), шапка с неоновым логотипом, градиентные линии
(кант шапки, подчёркивание, полоска карточки, разделители с акцентной
точкой). Списки (NeonList в GameFrame, inset 3 как New-GameListBox) и
пикер (GamePicker) - этап 4.

Логика (этап 5) - порт обработчиков VPN.ps1: загрузка подписки (120-156),
пинг (379-436), исключения (226-302), подключение/отключение/проверка
конфига (458-611), таймер 10с (615-641), --autoconnect (655-687), закрытие
окна (643-651). Отклонения (в комментариях у мест):
  - загрузка/пинг/внешний IP идут в QThread - в PS это runspace/DoEvents
    (экран не подвисает, статусы и их порядок те же);
  - при закрытии окна воркеры ждутся до 2с, затем terminate - порт
    BeginStop из FormClosing (там принудительная остановь джоба);
  - текст singbox.log.err читается как UTF-8 (в PS - системная кодировка).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

from vpn_launcher import __version__
from vpn_launcher.core.config import (
    GAME_SAFE_PROCESSES,
    new_sing_box_config,
    test_sing_box_config,
)
from vpn_launcher.core.log import write_log
from vpn_launcher.core.state import load_state, save_state
from vpn_launcher.paths import LOG_FILE, install_root
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
from vpn_launcher.win.elevate import is_elevated, relaunch_elevated
from vpn_launcher.win.mutex import acquire_instance, focus_existing_window
from vpn_launcher.win.proc import get_running_exe_list, start_sing_box, stop_sing_box
from vpn_launcher.win.proxy import set_proxy_on, set_proxy_off
from vpn_launcher.workers import EgressWorker, PingWorker, SubscriptionWorker

WIN_W, WIN_H = 620, 726
WIN_RADIUS = 12  # Install-GameCorners (theme.ps1:1253)

# PS Color.Gray для 'Внешний IP недоступен' (VPN.ps1:639)
_GRAY = QColor(128, 128, 128)

# Add-Excl (VPN.ps1:255-256): авто-.exe и валидация имени.
# PS `-match` регистронезависим - флаг IGNORECASE; `\w` в Python для str юникоден,
# как Unicode-классы .NET.
_EXCL_EXE_END = re.compile(r"\.exe$", re.IGNORECASE)
_EXCL_NAME = re.compile(r"^[\w\-. ]+\.exe$", re.IGNORECASE)


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
    mode_changed = Signal(str)  # 'tun' | 'proxy'

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VPN ЛАУНЧЕР BY @YoncFALL")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(WIN_W, WIN_H)
        self._drag: QPointF | None = None

        self.state = load_state()
        self.nodes: list[dict] = []
        self.proc: subprocess.Popen | None = None
        self._busy = False  # идёт загрузка подписки (Busy в PS)
        self._loader: SubscriptionWorker | None = None
        self._pinger: PingWorker | None = None
        self._egress: EgressWorker | None = None
        self._ping_error = False
        self._ping_done = 0
        self._ping_total = 0
        self._auto_pending = False  # ждёт продолжения --autoconnect
        self._tick_count = 0

        self._apply_mask()
        self._build()
        self._restore_state()

        # таймер 10с: проверка процесса + внешний IP (VPN.ps1:615-641)
        self.tick = QTimer(self)
        self.tick.setInterval(10000)
        self.tick.timeout.connect(self._on_tick)

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
        self.btn_load.clicked.connect(self._load_click)
        self.btn_ping.clicked.connect(self._ping_click)

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
            card,
            "игры, Steam и античиты исключены автоматически",
            300, 424, 274, 16, theme.TEXT_DIM, theme.f_sub(), "right",
        )
        self.frame_excl = GameFrame(10, card)
        self.frame_excl.setGeometry(18, 444, 260, 84)
        # список исключений: Pad=14 (New-GameListBox ... $false 14, VPN.ps1:193)
        self.list_excl = NeonList(ping=False, pad=14, parent=self.frame_excl)
        self.list_excl.setGeometry(3, 3, 260 - 6, 84 - 6)
        self.picker_proc = GamePicker("выбери процесс или впиши имя .exe", card)
        self.picker_proc.setGeometry(288, 444, 286, 30)

        self.btn_add = GameButton("Добавить", "ghost", 8, card)
        self.btn_add.setGeometry(288, 478, 286, 30)
        self.btn_del = GameButton("Удалить", "ghost", 8, card)
        self.btn_del.setGeometry(288, 512, 138, 30)
        self.btn_clr = GameButton("Очистить", "ghost", 8, card)
        self.btn_clr.setGeometry(426, 512, 148, 30)
        self.btn_add.clicked.connect(self._excl_add)
        self.btn_del.clicked.connect(self._excl_del)
        self.btn_clr.clicked.connect(self._excl_clr)
        # Enter в поле = добавить (VPN.ps1:280-285), даблклик = удалить (298)
        self.picker_proc.submitted.connect(self._excl_add)
        self.list_excl.doubleClicked.connect(lambda *_: self._excl_del())
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
        self.btn_connect.clicked.connect(self._connect_click)
        self.btn_disconnect.clicked.connect(self._disconnect_click)
        self.btn_testcfg.clicked.connect(self._testcfg_click)

        self.led_status = Led(10, "off", card)
        self.led_status.setGeometry(18, 640, 10, 10)
        self.lbl_status = _label(
            card, "Готов", 36, 636, 250, 18, theme.TEXT, theme.f_body(),
        )
        self.lbl_egress = _label(
            card, "", 300, 636, 274, 18, theme.TEXT_DIM, theme.f_mono(), "right"
        )

    def _restore_state(self) -> None:
        """Стартовое состояние (VPN.ps1:111, 180-184, 219, 300-303, 653).

        Список серверов при старте пустой: 1.0.6 не сохраняет ноды.
        """
        self.field_sub.setText(str(self.state.get("subUrl") or ""))
        proxy = self.state.get("mode") == "proxy"
        self.radio_tun.set_checked(not proxy)
        self.radio_proxy.set_checked(proxy)
        for a in self.state.get("appList") or []:
            if a:
                self.list_excl.add_item(str(a))
        self.picker_proc.set_items(get_running_exe_list())  # Fill-ProcCombo
        self._status("Готов")
        title = "VPN ЛАУНЧЕР BY @YoncFALL"
        if is_elevated():
            title += " (администратор)"
        self.setWindowTitle(title)

    # ---- служебное -------------------------------------------------------
    def _status(self, text: str, color: QColor | None = None) -> None:
        """Текст статуса; цвет меняем только когда PS трогает ForeColor."""
        self.lbl_status.setText(text)
        if color is not None:
            self.lbl_status.setStyleSheet(
                f"color: {color.name()}; background: transparent;"
            )

    def _msg(self, text: str, title: str = "", *, icon: str = "") -> None:
        """MessageBox (тесты подменяют этот метод на запись в список)."""
        box = QMessageBox(self)
        if icon == "error":
            box.setIcon(QMessageBox.Icon.Error)
        elif icon == "info":
            box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _msg_confirm(self, text: str, title: str = "") -> bool:
        """MessageBox OKCancel (тесты подменяют; True = 'Да')."""
        box = QMessageBox(
            QMessageBox.Icon.Information,
            title,
            text,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            self,
        )
        return box.exec() == QMessageBox.StandardButton.Ok

    def _mode(self) -> str:
        return "tun" if self.radio_tun.checked() else "proxy"

    def _selected_tags(self) -> list[str]:
        """Get-SelectedTags (VPN.ps1:313-319)."""
        i = self.list_servers.selected_index()
        if 0 <= i < len(self.nodes):
            return [str(self.nodes[i].get("tag") or "")]
        return []

    def _app_list(self) -> list[str]:
        """Get-AppList (VPN.ps1:320-327): trim, пустые - в сторону."""
        out = []
        for t in self.list_excl.item_texts():
            a = t.strip()
            if a:
                out.append(a)
        return out

    def _select_mode(self, mode: str) -> None:
        self.radio_tun.set_checked(mode == "tun")
        self.radio_proxy.set_checked(mode == "proxy")
        self.mode_changed.emit(mode)

    def _open_log(self) -> None:
        """Порт VPN.ps1:158 - открываем журнал в блокноте, если он есть."""
        if LOG_FILE.exists():
            subprocess.Popen(["notepad.exe", str(LOG_FILE)])

    # ---- загрузка подписки (VPN.ps1:120-156) -----------------------------
    def _load_click(self) -> bool:
        """btnLoad; True - задача запущена (для цепочки --autoconnect)."""
        if self._busy:
            return False
        url = self.field_sub.text().strip()
        if not url:
            self._msg("Вставь ссылку на подписку.")
            return False
        self._busy = True
        self.btn_load.set_text("Загрузка...")
        self.btn_load.setEnabled(False)
        w = SubscriptionWorker(url)
        w.loaded.connect(self._on_loaded)
        w.failed.connect(self._on_load_failed)
        w.finished.connect(self._on_load_finished)
        self._loader = w
        w.start()
        return True

    def _on_loaded(self, nodes: list) -> None:
        self.nodes = list(nodes)
        self.state["subUrl"] = self.field_sub.text().strip()
        save_state(self.state)
        self.list_servers.set_nodes(self.nodes)  # и чистка пингов (Ping=@{})
        self._status(f"Серверов загружено: {len(self.nodes)}", theme.ACCENT2)
        if self._auto_pending:
            # откладываем: в PS сначала finally (сброс кнопки), потом проверка Count
            QTimer.singleShot(0, self._auto_continue)

    def _on_load_failed(self, msg: str) -> None:
        self._status("Ошибка загрузки", theme.DANGER)
        self._msg(msg, "VPN ЛАУНЧЕР BY @YoncFALL", icon="error")
        if self._auto_pending:
            # PS после PerformClick сверяет Nodes.Count - при пустом списке
            # статус autoconnect'а перекроет 'Ошибка загрузки'
            QTimer.singleShot(0, self._auto_continue)

    def _on_load_finished(self) -> None:
        self._busy = False
        self.btn_load.set_text("Загрузить подписку")
        self.btn_load.setEnabled(True)
        self._loader = None

    # ---- пинг (VPN.ps1:379-436) ------------------------------------------
    def _ping_click(self) -> None:
        try:
            if self._pinger is not None:
                return
            if not self.nodes:
                self._msg("Сначала загрузи подписку.")
                return
            # Ping[tag] = -2 для всех -> в колонках '...' до первого результата
            self.list_servers.set_pings(
                {str(n.get("tag") or ""): -2 for n in self.nodes}
            )
            self._ping_done = 0
            self._ping_total = len(self.nodes)
            self._ping_error = False
            self.btn_ping.setEnabled(False)
            self.btn_ping.set_text("Пинг...")
            w = PingWorker(self.nodes)
            w.result.connect(self._on_ping_result)
            w.failed.connect(self._on_ping_failed)
            w.finished.connect(self._on_ping_finished)
            self._pinger = w
            # жёлтым плавно загорается на время проверки (по просьбе - README)
            self.led_status.light_up("warn", pulse=False)
            w.start()
        except Exception as exc:
            self._pinger = None
            self.btn_ping.setEnabled(True)
            self.btn_ping.set_text("Проверить пинг")
            self._status("Ошибка проверки пинга (см. лог)", theme.DANGER)
            write_log(f"ping click ERROR: {exc}")

    def _on_ping_result(self, tag: str, ms: int) -> None:
        self.list_servers.set_ping(tag, ms)
        self._ping_done += 1
        self._status(
            f"Проверка пинга: {self._ping_done} из {self._ping_total}", theme.WARN
        )

    def _on_ping_failed(self, msg: str) -> None:
        self._ping_error = True
        self._status("Ошибка проверки пинга (см. лог)", theme.DANGER)
        write_log(f"ping ERROR: {msg}")

    def _on_ping_finished(self) -> None:
        self._pinger = None
        self.btn_ping.setEnabled(True)
        self.btn_ping.set_text("Проверить пинг")
        # проверка кончилась: жёлтая гаснет; если онлайн - обратно зелёная
        # пульсация (по просьбе - README)
        if self.proc is not None:
            self.led_status.light_up("ok", pulse=True)
        else:
            self.led_status.light_off()
        if self._ping_error:
            return
        vals = [v for v in self.list_servers.pings.values() if v >= 0]
        ok = len(vals)
        best = min(vals) if vals else None
        suffix = f", лучший {best} мс" if best is not None else ""
        self._status(
            f"Пинг готов: {ok} из {len(self.nodes)} доступны{suffix}",
            theme.ACCENT2 if ok > 0 else theme.DANGER,
        )
        # PS пишет best= пустым при отсутствии доступных (мертвый Measure)
        write_log(
            f"ping done: {ok} of {len(self.nodes)} reachable, "
            f"best={'' if best is None else best} ms"
        )

    # ---- исключения (VPN.ps1:226-302) ------------------------------------
    def _save_excl(self) -> None:
        """Save-ExclList (VPN.ps1:226-231)."""
        self.state["appList"] = self.list_excl.item_texts()
        save_state(self.state)

    def _excl_add(self) -> None:
        """Add-Excl (VPN.ps1:252-277) + Enter в поле (280-285)."""
        v = self.picker_proc.text().strip()
        if not v:
            return
        if not _EXCL_EXE_END.search(v):
            v += ".exe"
        if not _EXCL_NAME.fullmatch(v):
            self._status("Не похоже на имя процесса (.exe)", theme.DANGER)
            return
        if v in self.list_excl.item_texts():
            # WinForms Items.Contains - регистрозависим
            self._status(f"{v} уже есть в списке", theme.WARN)
            return
        if v.casefold() in {a.casefold() for a in GAME_SAFE_PROCESSES}:
            # PS `-contains` - регистронезависим
            self._status(f"{v} и так исключён автоматически", theme.WARN)
            return
        self.list_excl.add_item(v)
        self.picker_proc.setText("")
        self._save_excl()
        self._status(f"Добавлено исключение: {v}", theme.ACCENT2)
        write_log(f"exclusion added by user: {v}")

    def _excl_del(self, *_args) -> None:
        """btnExclDel (VPN.ps1:286-290); *_args - аргумент сигнала doubleClicked."""
        row = self.list_excl.selected_index()
        if row < 0:
            return
        self.list_excl.remove_row(row)
        self._save_excl()

    def _excl_clr(self) -> None:
        """btnExclClr (VPN.ps1:291-297)."""
        if self.list_excl.model().rowCount() == 0:
            return
        self.list_excl.clear_rows()
        self._save_excl()
        self._status("Список исключений очищен", theme.WARN)

    # ---- подключение (VPN.ps1:458-575) -----------------------------------
    def _connect_click(self) -> None:
        if not self.nodes:
            self._msg("Сначала загрузи подписку.")
            return
        mode = self._mode()
        sel = self._selected_tags()
        apps = self._app_list()

        self.state["mode"] = mode
        self.state["appList"] = apps
        self.state["subUrl"] = self.field_sub.text().strip()
        self.state["selected"] = ",".join(sel) if sel else ""
        save_state(self.state)

        # TUN требует администратора (VPN.ps1:474-523)
        if mode == "tun" and not is_elevated():
            self._status("Нужны права администратора...", theme.WARN)
            self.btn_connect.setEnabled(False)
            QApplication.processEvents()  # DoEvents
            ans = self._msg_confirm(
                'Режим "Весь трафик (TUN)" работает только с правами администратора.\n\n'
                "Сейчас приложение перезапустится с повышенными правами и подключится само.\n"
                'В окне Windows нажмите "Да".',
                "VPN ЛАУНЧЕР BY @YoncFALL",
            )
            if not ans:
                write_log("elevation cancelled by user")
                self._status("Отменено - подключение не выполнено", theme.DANGER)
                self.btn_connect.setEnabled(True)
                return
            try:
                relaunch_elevated(["--autoconnect"])
            except OSError:
                # лог 'elevation ERROR: ...' пишет сам relaunch_elevated
                self._status("Не удалось получить права администратора", theme.DANGER)
                self.btn_connect.setEnabled(True)
                return
            # цвет статуса остаётся Warn - PS его не переназначает (519)
            self._status("Запуск с правами администратора...")
            QApplication.processEvents()
            self.close()
            return

        self.btn_connect.setEnabled(False)
        self._status("Генерация конфига...")  # цвет не меняем (как PS, 526)
        QApplication.processEvents()
        try:
            cfg = new_sing_box_config(self.nodes, sel, mode, apps)
            ok, err = test_sing_box_config(cfg)
            if not ok:
                write_log(f"config check failed: {err}")
                if sel:
                    write_log("retry with selected server only")
                    cfg = new_sing_box_config(
                        self.nodes, sel, mode, apps, only_selected=True
                    )
                    ok, err = test_sing_box_config(cfg)
                if not ok:
                    raise RuntimeError("Конфиг не прошёл проверку: " + err)

            self._status("Запуск sing-box...")  # цвет не меняем (543)
            QApplication.processEvents()
            self.proc = start_sing_box(cfg, install_root())
            # Start-Sleep -Seconds 3 (557) - события продолжают крутиться
            for _ in range(60):
                QApplication.processEvents()
                time.sleep(0.05)
            if self.proc.poll() is not None:
                raise RuntimeError("sing-box завершился: " + _read_sb_err())
            if mode == "proxy":
                set_proxy_on()
            self.btn_disconnect.setEnabled(True)
            nsel = f"{len(sel)} сервер(а)" if sel else "авто-тест всех"
            self._status(
                f"ПОДКЛЮЧЕНО  |  pid {self.proc.pid}  |  {nsel}", theme.ACCENT2
            )
            # лампочки при успешном подключении (отклонение от 1.0.6 - см. README):
            # нижняя - плавно и с пульсацией, верхняя у минимизации - ровно
            self.led_status.light_up("ok", pulse=True)
            self.titlebar.led.light_up("ok", pulse=False)
            self._tick_count = 0
            self.tick.start()
        except Exception as ex:
            write_log(f"connect ERROR: {ex}")
            self._status("Не удалось подключиться", theme.DANGER)
            self.btn_connect.setEnabled(True)
            self._msg(str(ex), "Ошибка подключения", icon="error")

    def _disconnect_click(self) -> None:
        """btnDisconnect.Add_Click (VPN.ps1:577-589)."""
        stop_sing_box(self.proc)
        self.proc = None
        set_proxy_off()
        self.tick.stop()
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self._status("Отключено", theme.TEXT)
        self.lbl_egress.setText("")
        self.led_status.light_off()  # плавно угасают (см. led.py)
        self.titlebar.led.light_off()

    def _testcfg_click(self) -> None:
        """btnTestCfg.Add_Click (VPN.ps1:591-611)."""
        if not self.nodes:
            self._msg("Сначала загрузи подписку.")
            return
        mode = self._mode()
        try:
            cfg = new_sing_box_config(
                self.nodes, self._selected_tags(), mode, self._app_list()
            )
            ok, err = test_sing_box_config(cfg)
            if ok:
                self._status("Конфиг корректен", theme.ACCENT2)
                self._msg(
                    "Конфиг корректен.", "VPN ЛАУНЧЕР BY @YoncFALL", icon="info"
                )
            else:
                self._msg(err, "Ошибка конфига", icon="error")
        except Exception as ex:
            self._msg(str(ex), "Ошибка", icon="error")

    # ---- таймер 10с (VPN.ps1:615-641) ------------------------------------
    def _on_tick(self) -> None:
        self._tick_count += 1
        if self.proc is not None and self.proc.poll() is not None:
            self.tick.stop()
            set_proxy_off()
            self.proc = None
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            self._status(
                "Соединение оборвалось - sing-box завершился, смотри лог",
                theme.DANGER,
            )
            self.led_status.light_off()  # обрыв - лампочки гаснут плавно
            self.titlebar.led.light_off()
            return
        # (Counter % 3) == 1: внешний IP раз в 30с
        if self._tick_count % 3 == 1 and self._egress is None:
            w = EgressWorker()
            w.got.connect(self._on_egress)
            w.failed.connect(self._on_egress_failed)
            w.finished.connect(self._on_egress_finished)
            self._egress = w
            w.start()

    def _on_egress(self, ip: str) -> None:
        self.lbl_egress.setText(f"Внешний IP: {ip}")
        self.lbl_egress.setStyleSheet(
            f"color: {theme.ACCENT.name()}; background: transparent;"
        )

    def _on_egress_failed(self, _msg: str) -> None:
        self.lbl_egress.setText("Внешний IP недоступен")
        self.lbl_egress.setStyleSheet(f"color: {_GRAY.name()}; background: transparent;")

    def _on_egress_finished(self) -> None:
        self._egress = None

    # ---- --autoconnect (VPN.ps1:655-687) ---------------------------------
    def autoconnect(self) -> None:
        self._status("Загружаю подписку и подключаюсь...", theme.WARN)
        QApplication.processEvents()  # DoEvents
        if self._load_click():
            self._auto_pending = True
            return
        self._auto_continue()  # загрузка не запустилась - сверяем nodes как PS

    def _auto_continue(self) -> None:
        self._auto_pending = False
        if not self.nodes:
            self._status(
                "Не удалось загрузить подписку - проверь ссылку", theme.DANGER
            )
            return
        self._select_mode("tun")  # rbTun.Checked = $true, rbProxy = $false (672-673)
        want = {
            t.strip().casefold()
            for t in str(self.state.get("selected") or "").split(",")
            if t.strip()
        }
        if want:
            for i, n in enumerate(self.nodes):
                if str(n.get("tag") or "").casefold() in want:
                    self.list_servers.select_index(i)
                    break
        self.btn_connect.clicked.emit()  # btnConnect.PerformClick (684)

    # ---- закрытие (VPN.ps1:643-651) --------------------------------------
    def closeEvent(self, e) -> None:  # noqa: N802
        self.tick.stop()
        if self._pinger is not None:
            self._pinger.cancel()
        for w in (self._pinger, self._loader, self._egress):
            if w is not None and not w.wait(2000):
                w.terminate()  # порт BeginStop - принудительная остановка
                w.wait(500)
        stop_sing_box(self.proc)
        self.proc = None
        set_proxy_off()
        super().closeEvent(e)

    # ---- drag (за пустые места окна, как Install-GameCorners) -----------
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None


def _read_sb_err() -> str:
    """Текст stderr движка после падения ('sing-box завершился: ', 558-560)."""
    try:
        return (install_root() / "singbox.log.err").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    autoconnect = "--autoconnect" in args
    # single-instance (Host.cs): второй экземпляр поднимает окно первого
    if not acquire_instance():
        focus_existing_window()
        return 0
    app = QApplication([args[0]] if args else [])
    app.setStyle("Fusion")
    app.setApplicationName("VPN LAUNCHER")
    app.setOrganizationName("yoncfall-tech")

    win = MainWindow()
    scr = app.primaryScreen().availableGeometry()
    win.move(scr.center().x() - WIN_W // 2, scr.center().y() - WIN_H // 2)
    win.show()

    if autoconnect:
        QTimer.singleShot(700, win.autoconnect)  # AutoTimer.Interval = 700

    # VPN_SHOT=<path>: снять окно и выйти (визуальные сверки с 1.0.6)
    shot = os.environ.get("VPN_SHOT")
    if shot:

        def _grab() -> None:
            win.grab().save(shot)
            app.quit()

        QTimer.singleShot(700, _grab)

    return app.exec()
