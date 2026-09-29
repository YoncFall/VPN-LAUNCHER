# -*- coding: utf-8 -*-
"""Реальные клики мышью по пикеру и спискам (QTest) - репро бага «не тыкается».

Этап 4 тестировал commit_from_popup()/select_index() напрямую; здесь кликаем
через viewport, как это делает Windows в живом окне.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vpn_launcher.ui.widgets.neon_list import NeonList  # noqa: E402
from vpn_launcher.ui.widgets.picker import GamePicker  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class TestPickerRealClicks:
    def test_chevron_click_opens(self, qapp):
        p = GamePicker("ph")
        p.set_items(["Steam.exe", "Discord.exe", "notepad.exe"])
        p.resize(286, 30)
        p.show()
        QTest.mouseClick(p, Qt.MouseButton.LeftButton, pos=QPoint(286 - 15, 15))
        assert p.drop_open(), "клик по шеврону не открыл попап"
        p.close_drop()
        p.close()

    def test_field_body_click_does_not_open(self, qapp):
        p = GamePicker("ph")
        p.set_items(["Steam.exe"])
        p.resize(286, 30)
        p.show()
        QTest.mouseClick(p, Qt.MouseButton.LeftButton, pos=QPoint(100, 15))
        assert not p.drop_open()  # паритет: OnMouseDown только зона 29px
        p.close()

    def test_item_click_commits(self, qapp):
        p = GamePicker("ph")
        p.set_items(["Steam.exe", "Discord.exe", "notepad.exe"])
        p.resize(286, 30)
        p.show()
        p.open_drop()
        assert p.drop_open()
        lst = p._pop.list
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(60, 14))
        assert p.text() == "Steam.exe", f"клик по строке не коммитнул: {p.text()!r}"
        assert not p.drop_open()
        p.close()

    def test_second_item_click_commits(self, qapp):
        p = GamePicker("ph")
        p.set_items(["Steam.exe", "Discord.exe", "notepad.exe"])
        p.resize(286, 30)
        p.show()
        p.open_drop()
        QTest.mouseClick(p._pop.list.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(60, 42))
        assert p.text() == "Discord.exe"
        p.close()

    def test_open_then_release_on_chevron_keeps_open(self, qapp):
        """Нажатие открывает, отпускание на шевроне не должно закрыть."""
        p = GamePicker("ph")
        p.set_items(["Steam.exe", "Discord.exe"])
        p.resize(286, 30)
        p.show()
        QTest.mousePress(p, Qt.MouseButton.LeftButton, pos=QPoint(286 - 15, 15))
        assert p.drop_open()
        QTest.mouseRelease(p, Qt.MouseButton.LeftButton, pos=QPoint(286 - 15, 15))
        assert p.drop_open(), "release на шевроне закрыл попап"
        p.close_drop()
        p.close()


class TestListRealClicks:
    def test_click_row_selects(self, qapp):
        lst = NeonList(ping=False, pad=14)
        lst.resize(254, 84)
        lst.show()
        lst.set_items(["a.exe", "b.exe"])
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(40, 14))
        assert lst.selected_index() == 0, "клик по строке не выделил"
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(40, 42))
        assert lst.selected_index() == 1
        lst.close()
