# -*- coding: utf-8 -*-
"""Тесты журнала (порта Write-VpnLog, core.ps1:25-33)."""
from vpn_launcher.core.log import MAX_LOG_SIZE, write_log


def test_line_format(tmp_path):
    p = tmp_path / "vpn-launcher.log"
    write_log("hello", path=p)
    line = p.read_text(encoding="utf-8")
    # 'yyyy-MM-dd HH:mm:ss  message'
    assert line[4] == "-" and line[7] == "-" and line[10] == " "
    assert line[13] == ":" and line[16] == ":"
    assert line[19:21] == "  "
    assert line.rstrip("\r\n").endswith("  hello")


def test_append_keeps_history(tmp_path):
    p = tmp_path / "log.txt"
    write_log("one", path=p)
    write_log("two", path=p)
    text = p.read_text(encoding="utf-8")
    assert "  one" in text and "  two" in text
    assert text.index("one") < text.index("two")


def test_rotation_deletes_oversized_file(tmp_path):
    p = tmp_path / "log.txt"
    p.write_bytes(b"x" * (MAX_LOG_SIZE + 1))
    write_log("fresh", path=p)
    assert "fresh" in p.read_text(encoding="utf-8")
    assert p.stat().st_size < MAX_LOG_SIZE
