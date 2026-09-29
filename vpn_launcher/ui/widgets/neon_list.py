# -*- coding: utf-8 -*-
"""Список с неоновой выделительной полоской. Этап 4.

Порт: Set-GameListDraw/DarkListBox/New-GameList (theme.ps1:810-914) + вёрстка
строк VPN.ps1:170 (серверы, -Ping) и VPN.ps1:193 (исключения, без пинга).
Поведение дословно как в owner-draw 1.0.6:
  - одиночное выделение (WinForms SelectionMode One: повторный клик по уже
    выделенной строке выделение не снимает);
  - выделение: плашка (3, y+2, W-6, h-4) радиус 5, градиент (44,62,82)->
    (28,44,62) сверху вниз, неон-полоска 3x(h-8) на x=3, y+4
    (Accent->AccentD);
  - строки с нечётным индексом: фон (22,25,34) во всю строку;
  - паддинг текста 8 (Bounds.X + Pad), EndEllipsis, высота строки 28
    (New-GameList ItemHeight), пустой (без фокусной) прямоугольник выключен;
  - ping-режим (и только пока строка < числа нод): прото 46px справа от
    padL капсом (VLESS/VMESS/TROJAN/SS/HY2/TUIC/???), имя с padL+52 шириной
    W-52-92, пинг в правом краю с отступом 10;
  - пинги: нет данных '---' (TextDim), -2 '...' (TextDim), <0 'offline'
    (Danger), иначе 'N ms': <120 Accent2, <260 Warn, иначе (255,140,90);
  - свой тёмный скроллбар (NeonScrollBar), горизонтального нет.

Координаты делегата - в системе viewport (как Bounds у WinForms, X=0).
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSize, Qt
from PySide6.QtGui import (
    QStandardItem,
    QStandardItemModel,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle, QListView

from vpn_launcher.ui import theme
from vpn_launcher.ui.widgets.scroll_bar import NeonScrollBar

ROW_H = 28  # New-GameList ItemHeight (theme.ps1:910)

_PROTO = {
    "vless": "VLESS",
    "vmess": "VMESS",
    "trojan": "TROJAN",
    "shadowsocks": "SS",
    "hysteria2": "HY2",
    "tuic": "TUIC",
}

# цвет пинга выше 260 мс (PS: FromArgb(255, 140, 90))
_SLOW = QColor(255, 140, 90)


class _NeonDelegate(QStyledItemDelegate):
    """Отрисовка строки: дословный порт Set-GameListDraw (theme.ps1:822-895)."""

    def __init__(self, view: "NeonList") -> None:
        super().__init__(view)
        self._view = view

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(40, ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        view = self._view
        rect = option.rect
        w, h, row = rect.width(), rect.height(), index.row()
        sel = bool(option.state & QStyle.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --- фон строки / плашка выделения (835-851) ---
        if sel:
            path = QPainterPath()
            path.addRoundedRect(3, rect.y() + 2, w - 6, h - 4, 5, 5)
            g = QLinearGradient(0, rect.y(), 0, rect.y() + h)
            g.setColorAt(0.0, QColor(44, 62, 82))
            g.setColorAt(1.0, QColor(28, 44, 62))
            painter.fillPath(path, g)
            bar = QLinearGradient(0, rect.y(), 0, rect.y() + h)
            bar.setColorAt(0.0, QColor(theme.ACCENT))
            bar.setColorAt(1.0, QColor(theme.ACCENT_D))
            painter.fillRect(3, rect.y() + 4, 3, h - 8, bar)
        elif row % 2 == 1:
            painter.fillRect(rect, QColor(22, 25, 34))

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        clr = QColor(theme.TEXT) if sel else QColor(206, 212, 226)
        pad_l = view.pad  # Bounds.X = 0 в координатах viewport
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine

        nodes = view.nodes
        if view.ping and row < len(nodes):
            node = nodes[row]
            # прото: rect (padL, y, 46, h), правый край, капс, TextDim
            painter.setFont(theme.f_caps())
            painter.setPen(QPen(QColor(theme.TEXT_DIM)))
            painter.drawText(
                pad_l, rect.y(), 46, h,
                flags | Qt.AlignmentFlag.AlignRight,
                _PROTO.get(node.get("proto", ""), "???"),
            )
            # имя: rect (padL+52, y, W-52-92, h)
            painter.setFont(theme.f_row())
            painter.setPen(QPen(clr))
            name_rect_w = max(0, w - 52 - 92)
            fm = painter.fontMetrics()
            painter.drawText(
                pad_l + 52, rect.y(), name_rect_w, h,
                flags,
                fm.elidedText(text, Qt.TextElideMode.ElideRight, name_rect_w),
            )
            # пинг: правый край с отступом 10 (876-891)
            ping_txt, ping_clr = self._ping_style(view.pings.get(node.get("tag")))
            tw = fm.horizontalAdvance(ping_txt)
            painter.setPen(QPen(ping_clr))
            painter.drawText(w - tw - 10, rect.y(), tw, h, flags, ping_txt)
        else:
            painter.setFont(theme.f_row())
            painter.setPen(QPen(clr))
            tw = max(0, w - pad_l - 8)
            fm = painter.fontMetrics()
            painter.drawText(
                pad_l, rect.y(), tw, h, flags,
                fm.elidedText(text, Qt.TextElideMode.ElideRight, tw),
            )
        painter.restore()

    @staticmethod
    def _ping_style(ms) -> tuple[str, QColor]:
        """Формат и цвет пинга (theme.ps1:876-887)."""
        if ms is None:
            return "---", QColor(theme.TEXT_DIM)
        if ms == -2:
            return "...", QColor(theme.TEXT_DIM)
        if ms < 0:
            return "offline", QColor(theme.DANGER)
        clr = QColor(theme.ACCENT2) if ms < 120 else QColor(theme.WARN) if ms < 260 else _SLOW
        return f"{ms} ms", clr


class NeonList(QListView):
    """Список серверов (ping=True) или исключений (ping=False)."""

    def __init__(self, ping: bool = False, pad: int = 8, parent=None) -> None:
        super().__init__(parent)
        self.ping = ping
        self.pad = pad
        self.nodes: list[dict] = []
        self.pings: dict[str, int] = {}

        model = QStandardItemModel(self)
        self.setModel(model)
        self.setItemDelegate(_NeonDelegate(self))
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setVerticalScrollBar(NeonScrollBar(self))
        self.setStyleSheet(
            "QListView { background-color: #12151D; border: none; outline: none; }"
        )
        # фокус - по клику; рамку фокуса не рисуем (в 1.0.6 её нет)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ---- данные ----------------------------------------------------------
    def _model(self) -> QStandardItemModel:
        return self.model()  # type: ignore[return-value]

    def set_nodes(self, nodes: list[dict]) -> None:
        """Заполнить ping-список (текст строки = node['display'], VPN.ps1:139)."""
        self.nodes = list(nodes)
        self.pings = {}
        self._rebuild([str(n.get("display", "")) for n in self.nodes])

    def set_items(self, texts: list[str]) -> None:
        """Заполнить текстовый список (исключения, VPN.ps1:271)."""
        self._rebuild(list(texts))

    def add_item(self, text: str) -> None:
        """Порт Items.Add (VPN.ps1:271/301)."""
        item = QStandardItem(text)
        item.setEditable(False)
        self._model().appendRow(item)

    def remove_row(self, row: int) -> None:
        """Порт Items.RemoveAt (VPN.ps1:288).

        После удаления выделения нет - WinForms не переносит SelectedItems
        на соседнюю строку, и второй клик 'Удалить' уже no-op.
        """
        if 0 <= row < self._model().rowCount():
            self._model().removeRow(row)
            self.clearSelection()

    def clear_rows(self) -> None:
        """Порт Items.Clear (VPN.ps1:293)."""
        self._model().clear()
        self._model().setColumnCount(1)
        self.clearSelection()

    def _rebuild(self, texts: list[str]) -> None:
        m = self._model()
        m.clear()
        m.setColumnCount(1)
        for t in texts:
            item = QStandardItem(t)
            item.setEditable(False)
            m.appendRow(item)
        self.clearSelection()

    # ---- пинги (Set-GameListDraw читает $script:Ping) ---------------------
    def set_ping(self, tag: str, ms: int) -> None:
        self.pings[tag] = ms
        self.viewport().update()

    def set_pings(self, pings: dict[str, int]) -> None:
        self.pings = dict(pings)
        self.viewport().update()

    def clear_pings(self) -> None:
        self.pings = {}
        self.viewport().update()

    # ---- выделение --------------------------------------------------------
    def selected_index(self) -> int:
        """-1 - пусто; иначе индекс единственной выделенной строки (One)."""
        sm = self.selectionModel()
        if sm is None:
            return -1
        rows = sm.selectedRows()
        return rows[0].row() if rows else -1

    def select_index(self, row: int) -> None:
        if 0 <= row < self._model().rowCount():
            idx = self._model().index(row, 0)
            sm = self.selectionModel()
            if sm is not None:
                sm.setCurrentIndex(
                    idx,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        else:
            self.clearSelection()

    def item_texts(self) -> list[str]:
        m = self._model()
        return [m.item(r).text() for r in range(m.rowCount())]  # type: ignore[union-attr]
