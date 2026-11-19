# -*- coding: utf-8 -*-
"""Мини-просмотрщик отчётов: разбор файлов, группировка, HTML, окно."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.receiver import report_viewer as v  # noqa: E402


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def _payload(
    rid: str,
    created: str,
    *,
    title: str = "TLS-рукопожатие рвётся",
    severity: str = "err",
    actions: list[str] | None = None,
    trigger: str | None = "dpi_fail",
) -> dict:
    report = {
        "id": rid,
        "created": created,
        "system": {"version": "2.4.7", "os": "Windows-11", "mode": "tun",
                   "appMode": "include", "elevated": False,
                   "vpnRunning": False, "dpiRunning": True},
        "dns": [{"host": "discord.com", "v4": [], "v6": [], "error": "нет ответа"}],
        "tcp": [{"host": "discord.com", "ok": False, "error": "timeout"}],
        "tls": [],
        "http": [],
        "zapret": {"strategy": "combo", "running": True},
        "singbox": {"running": False},
        "discord": {"running": True, "version": "1.0.0"},
        "verdict": {
            "code": "dns_fail",
            "title": title,
            "actions": actions or ["Включите VPN.", "Проверьте DNS."],
            "severity": severity,
        },
    }
    if trigger is not None:
        report["trigger"] = trigger
    return {"report": report, "text": "полный текст"}


def _write(root, name: str, payload) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_scan_reports_sorted_and_grouped(tmp_path):
    _write(tmp_path, "2026-11-11/report-old.json", _payload("aaaaaa", "2026-11-11T10:00:00+03:00"))
    _write(tmp_path, "2026-11-12/report-new.json", _payload("bbbbbb", "2026-11-12T22:30:00+03:00"))
    (tmp_path / "2026-11-12" / "broken.json").write_text("{oops", encoding="utf-8")

    rows = v.scan_reports(tmp_path)

    assert [r["id"] for r in rows] == ["bbbbbb", "aaaaaa"]
    assert rows[0]["date"] == "12.11.2026"
    assert rows[0]["time"] == "22:30:00"
    assert rows[0]["version"] == "2.4.7"
    groups = v.group_by_date(rows)
    assert [(d, len(items)) for d, items in groups] == [("12.11.2026", 1), ("11.11.2026", 1)]


def test_report_html_shows_problem_actions_and_escapes(tmp_path):
    title = "Проблема <script>alert(1)</script>"
    _write(tmp_path, "r.json", _payload("cccccc", "2026-11-12T12:00:00", title=title))
    row = v.scan_reports(tmp_path)[0]

    page = v.report_html(row)

    assert "Что делать" in page
    assert "Включите VPN." in page
    assert "DNS 0/1" in page
    assert "TCP discord.com: timeout" in page
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_report_html_shows_trigger(tmp_path):
    _write(tmp_path, "r.json", _payload("dddddd", "2026-11-12T12:00:00", trigger="watchdog"))
    row = v.scan_reports(tmp_path)[0]

    assert row["trigger"] == "watchdog"
    assert "сторож" in row["triggerText"]
    assert "причина: сторож" in v.report_html(row)


def test_report_without_trigger_is_not_an_error(tmp_path):
    _write(tmp_path, "r.json", _payload("eeeeee", "2026-11-12T12:00:00", trigger=None))
    row = v.scan_reports(tmp_path)[0]

    assert row["trigger"] == ""
    assert row["triggerText"] == "не указана"
    assert "причина: не указана" in v.report_html(row)


def test_viewer_lists_dates_without_network(tmp_path, qapp, monkeypatch):
    _write(tmp_path, "2026-11-11/report-old.json", _payload("aaaaaa", "2026-11-11T10:00:00"))
    _write(tmp_path, "2026-11-12/report-new.json", _payload("bbbbbb", "2026-11-12T22:30:00"))
    monkeypatch.setattr(v, "reports_root", lambda: tmp_path)

    win = v.ReportViewer()
    try:
        assert win.tree.topLevelItemCount() == 2
        assert win.tree.topLevelItem(0).childCount() == 1
        assert win.current is not None and win.current["id"] == "bbbbbb"
        win.search.setText("dns_fail")
        assert win.tree.topLevelItem(0).isHidden() is False
        win.search.setText("нет-такого")
        assert win.tree.topLevelItem(0).isHidden() is True
    finally:
        win.close()
