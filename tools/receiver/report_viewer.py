# -*- coding: utf-8 -*-
"""Мини-приложение: отчёты диагностики по датам.

Только чтение уже расшифрованных отчётов приёмника
(%LOCALAPPDATA%\\VPN-LAUNCHER-RECEIVER\\reports). Слева - даты и отчёты,
справа - вердикт, что делать и краткие результаты проверок. Полный текст
отчёта открывается кнопкой в блокноте/просмотрщике по умолчанию.

Запуск без консоли:
    .\\venv\\Scripts\\pythonw.exe tools\\receiver\\report_viewer.py
"""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_TITLE = "VPN LAUNCHER - отчёты диагностики"

# Причина сбора (совпадает с vpn_launcher/core/diagnostics.py:TRIGGERS).
TRIGGER_TEXT = {
    "manual": "ручной запуск",
    "dpi_fail": "автоподбор DPI не нашёл стратегию",
    "watchdog": "сторож: Discord не отвечает",
}


def reports_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "VPN-LAUNCHER-RECEIVER" / "reports"


def _parse_dt(text: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def _report_row(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    report = obj.get("report") if isinstance(obj, dict) else None
    if not isinstance(report, dict):
        return None
    verdict = report.get("verdict") if isinstance(report.get("verdict"), dict) else {}
    system = report.get("system") if isinstance(report.get("system"), dict) else {}
    created = str(report.get("created") or "")
    when = _parse_dt(created)
    if when is None:
        try:
            when = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            when = datetime.now()
    return {
        "path": path,
        "json": obj,
        "report": report,
        "id": str(report.get("id") or path.stem),
        "created": created,
        "dt": when,
        "date": when.strftime("%d.%m.%Y"),
        "time": when.strftime("%H:%M:%S"),
        "version": str(system.get("version") or "?"),
        "code": str(verdict.get("code") or "unknown"),
        "title": str(verdict.get("title") or "Без вердикта"),
        "severity": str(verdict.get("severity") or "info"),
        "actions": [str(a) for a in verdict.get("actions") or []],
        "trigger": str(report.get("trigger") or ""),
        "triggerText": TRIGGER_TEXT.get(
            str(report.get("trigger") or ""), "не указана"
        ),
    }


def scan_reports(root: str | Path | None = None) -> list[dict[str, Any]]:
    """Все читаемые отчёты, новые сверху."""
    base = Path(root) if root is not None else reports_root()
    rows: list[dict[str, Any]] = []
    if not base.exists():
        return rows
    for path in base.rglob("*.json"):
        row = _report_row(path)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r["dt"], reverse=True)
    return rows


def group_by_date(rows: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """[(дата, [отчёты]), ...] - даты и отчёты уже отсортированы."""
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    current = ""
    for row in rows:
        if row["date"] != current:
            current = row["date"]
            groups.append((current, []))
        groups[-1][1].append(row)
    return groups


# ---- HTML для правой панели ------------------------------------------------

_SEVERITY_COLOR = {"err": "#ff6175", "warn": "#ffb454", "info": "#51e49b"}
_SEVERITY_TEXT = {"err": "ошибка", "warn": "предупреждение", "info": "информация"}


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else "-"))


def _bool(value: Any) -> str:
    return "да" if value else "нет"


def _probe_summary(report: dict[str, Any]) -> tuple[str, list[str]]:
    """Кратко по слоям проверок + список провалов."""
    parts: list[str] = []
    fails: list[str] = []

    dns = [d for d in report.get("dns") or [] if isinstance(d, dict)]
    if dns:
        ok = [d for d in dns if d.get("v4") or d.get("v6")]
        parts.append(f"DNS {len(ok)}/{len(dns)}")
        for d in dns:
            if not (d.get("v4") or d.get("v6")):
                fails.append(f"DNS {d.get('host')}: {d.get('error') or 'нет адресов'}")

    tcp = [t for t in report.get("tcp") or [] if isinstance(t, dict)]
    if tcp:
        ok = [t for t in tcp if t.get("ok")]
        parts.append(f"TCP {len(ok)}/{len(tcp)}")
        for t in tcp:
            if not t.get("ok"):
                fails.append(f"TCP {t.get('host')}: {t.get('error') or 'нет соединения'}")

    tls = [t for t in report.get("tls") or [] if isinstance(t, dict)]
    if tls:
        ok = [t for t in tls if t.get("ok")]
        parts.append(f"TLS {len(ok)}/{len(tls)}")
        for t in tls:
            if not t.get("ok"):
                fails.append(f"TLS {t.get('host')}: {t.get('error') or 'рукопожатие не прошло'}")

    http = [h for h in report.get("http") or [] if isinstance(h, dict)]
    if http:
        ok = [h for h in http if h.get("status") and not h.get("error")]
        parts.append(f"HTTPS {len(ok)}/{len(http)}")
        for h in http:
            if h.get("error") or not h.get("status"):
                fails.append(f"HTTPS {h.get('url')}: {h.get('error') or 'нет ответа'}")

    return " · ".join(parts), fails


def report_html(row: dict[str, Any]) -> str:
    rep = row["report"]
    system = rep.get("system") if isinstance(rep.get("system"), dict) else {}
    verdict = rep.get("verdict") if isinstance(rep.get("verdict"), dict) else {}
    zapret = rep.get("zapret") if isinstance(rep.get("zapret"), dict) else {}
    singbox = rep.get("singbox") if isinstance(rep.get("singbox"), dict) else {}
    discord = rep.get("discord") if isinstance(rep.get("discord"), dict) else {}

    color = _SEVERITY_COLOR.get(row["severity"], "#56a8ff")
    severity = _SEVERITY_TEXT.get(row["severity"], row["severity"])

    parts = [
        "<style>",
        "body{font-family:'Segoe UI',sans-serif;color:#e8edf5;background:#11161e;"
        "font-size:13px;line-height:1.5;margin:0;padding:14px 16px;}",
        "h2{font-size:17px;margin:0 0 4px;}",
        "h3{font-size:12px;color:#8da2bd;text-transform:uppercase;"
        "letter-spacing:1px;margin:18px 0 6px;}",
        ".meta{color:#818da0;font-size:12px;margin-bottom:10px;}",
        ".badge{display:inline-block;padding:2px 8px;border-radius:9px;"
        f"border:1px solid {color};color:{color};font-size:11px;margin-bottom:8px;}}",
        "ol,ul{margin:6px 0 0 18px;padding:0;}li{margin:3px 0;}",
        "table{border-collapse:collapse;width:100%;}td{padding:2px 8px 2px 0;"
        "vertical-align:top;}td:first-child{color:#818da0;width:150px;}",
        ".fail{color:#ff9aa6;}.ok{color:#51e49b;}",
        "</style>",
        f'<span class="badge">{_e(severity)}</span>',
        f"<h2>{_e(row['title'])}</h2>",
        '<div class="meta">'
        f"{_e(row['date'])} {_e(row['time'])} · отчёт {_e(row['id'])} · "
        f"версия {_e(row['version'])} · код {_e(row['code'])} · "
        f"причина: {_e(row['triggerText'])}"
        "</div>",
    ]

    actions = [str(a) for a in verdict.get("actions") or []]
    if actions:
        parts.append("<h3>Что делать</h3><ol>")
        parts += [f"<li>{_e(a)}</li>" for a in actions]
        parts.append("</ol>")

    summary, fails = _probe_summary(rep)
    if summary or fails:
        parts.append("<h3>Проверки сети</h3>")
        if summary:
            parts.append(f"<p>{_e(summary)}</p>")
        if fails:
            parts.append('<ul class="fail">')
            parts += [f"<li>{_e(f)}</li>" for f in fails]
            parts.append("</ul>")

    rows = [
        ("ОС", system.get("os")),
        ("Режим", f"{system.get('mode') or '?'} / {system.get('appMode') or '?'}"),
        ("Права", "администратор" if system.get("elevated") else "обычные"),
        ("VPN запущен", _bool(system.get("vpnRunning"))),
        ("Обход DPI запущен", _bool(system.get("dpiRunning"))),
        ("Стратегия DPI", zapret.get("strategy") or "нет"),
        ("Sing-box запущен", _bool(singbox.get("running"))),
        ("Discord запущен", _bool(discord.get("running"))),
        ("Версия Discord", discord.get("version") or "-"),
    ]
    parts.append("<h3>Система</h3><table>")
    parts += [f"<tr><td>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in rows]
    parts.append("</table>")

    parts.append(
        '<h3>Полный отчёт</h3><p class="meta">'
        "Кнопка «Открыть полный отчёт» покажет журналы и аргументы winws."
        "</p>"
    )
    return "".join(parts)


# ---- окно ------------------------------------------------------------------


class ReportViewer(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1120, 720)
        self.setMinimumSize(820, 520)
        self.rows: list[dict[str, Any]] = []
        self.by_path: dict[str, dict[str, Any]] = {}
        self.current: dict[str, Any] | None = None

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.count_label = QLabel("Отчётов нет")
        self.count_label.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        top.addWidget(self.count_label)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по проблеме или ID")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        top.addWidget(self.search)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        folder = QPushButton("Папка отчётов")
        folder.clicked.connect(self.open_folder)
        top.addWidget(folder)
        layout.addLayout(top)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Время", "Проблема", "Версия"])
        self.tree.setColumnWidth(0, 74)
        self.tree.setColumnWidth(2, 58)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.splitter.addWidget(self.tree)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        right_layout.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        self.open_txt = QPushButton("Открыть полный отчёт")
        self.open_txt.clicked.connect(self.open_report)
        self.open_txt.setEnabled(False)
        buttons.addWidget(self.open_txt)
        buttons.addStretch(1)
        right_layout.addLayout(buttons)
        self.splitter.addWidget(right)
        self.splitter.setSizes([460, 640])
        layout.addWidget(self.splitter, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#818da0;font-size:11px;")
        layout.addWidget(self.status)
        self.setCentralWidget(central)

        self.tree.currentItemChanged.connect(self._on_select)
        self.search.textChanged.connect(self._apply_filter)
        self._apply_style()
        self.reload()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#0d1117; color:#e8edf5; }
            QTreeWidget, QTextBrowser, QLineEdit {
                background:#11161e; border:1px solid #273140; border-radius:8px;
            }
            QTreeWidget { alternate-background-color:#151c26; }
            QTreeWidget::item { padding:4px 4px; }
            QTreeWidget::item:selected { background:#1d3550; }
            QHeaderView::section {
                background:#151c26; color:#818da0; border:none;
                border-bottom:1px solid #273140; padding:5px;
            }
            QPushButton {
                background:#182231; border:1px solid #2d4058; border-radius:8px;
                padding:6px 12px;
            }
            QPushButton:hover { background:#20304a; }
            QPushButton:disabled { color:#5b6678; }
            QLineEdit { padding:5px 8px; }
            """
        )

    # ---- данные ---------------------------------------------------------
    def reload(self) -> None:
        selected = str(self.current["path"]) if self.current else ""
        self.rows = scan_reports()
        self.by_path = {str(r["path"]): r for r in self.rows}
        self._fill_tree()
        self.count_label.setText(
            f"Отчётов: {len(self.rows)}" if self.rows else "Отчётов нет"
        )
        self.status.setText(f"Папка: {reports_root()}")
        if selected and selected in self.by_path:
            self._select_path(selected)
        elif self.rows:
            self._select_first()
        else:
            self.current = None
            self.details.setHtml(
                "<p style='color:#818da0'>Пока ни одного отчёта. "
                "Когда пользователь пришлёт диагностику, он появится здесь.</p>"
            )
            self.open_txt.setEnabled(False)

    def _fill_tree(self) -> None:
        self.tree.clear()
        for date, items in group_by_date(self.rows):
            top = QTreeWidgetItem([date, f"{len(items)} отчёт(а)", ""])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(top)
            for row in items:
                child = QTreeWidgetItem([row["time"], row["title"], row["version"]])
                child.setData(0, Qt.ItemDataRole.UserRole, str(row["path"]))
                color = _SEVERITY_COLOR.get(row["severity"], "#e8edf5")
                child.setForeground(1, QColor(color))
                child.setToolTip(1, f"{row['title']}\nПричина: {row['triggerText']}")
                top.addChild(child)
            top.setExpanded(True)
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().casefold()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            shown = 0
            for j in range(top.childCount()):
                child = top.child(j)
                row = self.by_path.get(str(child.data(0, Qt.ItemDataRole.UserRole)))
                hit = not needle or (
                    row is not None
                    and needle
                    in f"{row['title']} {row['id']} {row['code']} {row['triggerText']}".casefold()
                )
                child.setHidden(not hit)
                if hit:
                    shown += 1
            top.setHidden(shown == 0)

    def _select_first(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.isHidden() or top.childCount() == 0:
                continue
            self.tree.setCurrentItem(top.child(0))
            return

    def _select_path(self, path: str) -> None:
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if str(child.data(0, Qt.ItemDataRole.UserRole)) == path:
                    self.tree.setCurrentItem(child)
                    return

    def _on_select(self, item: QTreeWidgetItem | None, _old=None) -> None:
        if item is None:
            return
        row = self.by_path.get(str(item.data(0, Qt.ItemDataRole.UserRole)))
        if row is None:
            return
        self.current = row
        self.details.setHtml(report_html(row))
        self.open_txt.setEnabled(True)

    # ---- кнопки ---------------------------------------------------------
    def open_folder(self) -> None:
        path = reports_root()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_report(self) -> None:
        if not self.current:
            return
        txt = self.current["path"].with_suffix(".txt")
        target = txt if txt.exists() else self.current["path"]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def main() -> int:
    app = QApplication(sys.argv)
    win = ReportViewer()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
