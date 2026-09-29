# -*- coding: utf-8 -*-
"""Поле-пикер с попапом. Этап 4.

Порт GamePicker/GameDropPopup/GameDropListBox + PickerDropFilter
(theme.ps1:260-594). Поведение дословно:
  - поле: заливка (19,22,30), радиус 7, рамка (58,66,86) -> hover (96,108,138)
    -> focus (0,200,240) со свечью a=60 (3px), плейсхолдер (110,118,136)
    при пустом тексте вне фокуса;
  - кнопка-шеврон 26px (зона x >= w-29): градиент (36,41,54)->(26,30,40),
    hover (52,60,80)->(36,42,58), радиус 5, рамка (60,70,92)/hover
    (100,118,152), разделитель a=80 BorderColor на x=w-29, шеврон
    (150,158,176), hover - акцент; hover считается по курсору при отрисовке
    (как в PS OnPaint);
  - попап: Qt.Popup (без активации окна, клик вне сам закрывает), скругление
    10, фон (18,21,29), рамка (72,82,108), блик (10..w-10, y=2) a=70;
    список (4,4,w-8,h-8), строки 28px, фон (19,22,30), плашка выбранной
    (40,56,76)->(28,44,62) r6 + рамка Accent 1px, текст padding 12,
    цвет (206,212,226)/выделенный (230,234,242);
  - фильтр: префикс (StartsWith, lowerInvariant) по тексту поля, пусто - все;
    совпадений нет - закрыть;
  - геометрия: под полем (y=bottom+2), h=min(8,n)*28+8, если не влезает -
    над полем; ширина = ширина пикера; репозиция при движении окна;
  - закрытие: клик вне пикера и попапа (Qt.Popup нативно, как
    PickerDropFilter), ESC, повторный клик по шеврону; Down/F4 - переключить;
  - выбор: hover двигает выделение (GameDropListBox.OnMouseMove), MouseUp
    коммитит: текст = пункт, SelectAll, фокус в поле.

Отклонение от PS: в попапе свой тёмный скроллбар (NeonScrollBar) вместо
нативного белого - в 1.0.6 нативный ползунок выглядел чужим в тёмном окне.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QListView,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

from vpn_launcher.ui import theme
from vpn_launcher.ui.widgets.scroll_bar import NeonScrollBar

ROW_H = 28
_BTN_ZONE = 29  # OnMouseMove: x >= ClientSize.Width - 29 (theme.ps1:342)


def _edit_qss() -> str:
    return f"""
    QLineEdit {{
        background: transparent;
        border: none;
        padding: 0;
        color: #E6EAF2;
        font: 9pt "{theme.family()}";
        selection-background-color: #0096BE;
        selection-color: #031A22;
    }}
    """


class _DropRowDelegate(QStyledItemDelegate):
    """Строка попапа: порт GameDropListBox.OnDrawItem (theme.ps1:474-494)."""

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(40, ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        from PySide6.QtGui import QFontMetrics

        r = option.rect
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(r, QColor(19, 22, 30))
        if sel:
            path = QPainterPath()
            path.addRoundedRect(r.x() + 2, r.y() + 2, r.width() - 4, r.height() - 4, 6, 6)
            g = QLinearGradient(0, r.y(), 0, r.y() + r.height())
            g.setColorAt(0.0, QColor(40, 56, 76))
            g.setColorAt(1.0, QColor(28, 44, 62))
            painter.fillPath(path, g)
            painter.setPen(QPen(QColor(theme.ACCENT)))
            painter.drawPath(path)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.setFont(theme.f_body())
        painter.setPen(QPen(QColor(theme.TEXT) if sel else QColor(206, 212, 226)))
        tw = max(4, r.width() - 16)
        painter.drawText(
            r.x() + 12, r.y(), tw, r.height(),
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            painter.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, tw
            ),
        )
        painter.restore()


class _HoverList(QListView):
    """Список попапа: hover двигает выделение, MouseUp коммитит (528-532)."""

    def __init__(self, owner: "GamePicker") -> None:
        super().__init__(owner)
        self._owner = owner
        self.setMouseTracking(True)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        idx = self.indexAt(e.position().toPoint())
        if idx.isValid() and idx != self.currentIndex():
            from PySide6.QtCore import QItemSelectionModel

            sm = self.selectionModel()
            if sm is not None:
                sm.setCurrentIndex(
                    idx,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                self._owner.commit_from_popup(idx.row())
            else:
                self._owner.close_drop()
            e.accept()
            return
        super().mouseReleaseEvent(e)


class _DropPopup(QWidget):
    """Попап-окно без активации: порт GameDropPopup (theme.ps1:510-577)."""

    def __init__(self, owner: "GamePicker") -> None:
        super().__init__(owner)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._owner = owner
        self._closing_by_code = False
        self.list = _HoverList(self)
        from PySide6.QtGui import QStandardItemModel

        self.list.setModel(QStandardItemModel(self.list))
        self.list.setItemDelegate(_DropRowDelegate())
        self.list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setFrameShape(QListView.Shape.NoFrame)
        self.list.setVerticalScrollBar(NeonScrollBar(self.list))
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # фокус остаётся в поле
        self.list.setStyleSheet(
            "QListView { background-color: #13161E; border: none; outline: none; }"
        )

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        self.list.setGeometry(4, 4, max(4, w - 8), max(4, h - 8))

    def hideEvent(self, e) -> None:  # noqa: N802
        """Закрытие Qt.Popup по клику вне = «пикер закрылся сам» (PickerDropFilter).

        От нашего close_drop() отличаем флагом: он выставляется до hide().
        """
        super().hideEvent(e)
        if self._closing_by_code:
            self._closing_by_code = False
            self._owner._auto_closed = False
        else:
            self._owner._mark_auto_closed()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 10, 10)
        p.fillPath(path, QColor(18, 21, 29))
        p.setPen(QPen(QColor(72, 82, 108), 1))
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.drawLine(10, 2, w - 10, 2)

    def item_count(self) -> int:
        return self.list.model().rowCount()  # type: ignore[union-attr]

    def set_items(self, items: list[str]) -> None:
        m = self.list.model()
        m.clear()  # type: ignore[union-attr]
        m.setColumnCount(1)  # type: ignore[union-attr]
        from PySide6.QtGui import QStandardItem

        for t in items:
            it = QStandardItem(t)
            it.setEditable(False)
            m.appendRow(it)  # type: ignore[union-attr]
        if items:
            self.list.setCurrentIndex(self.list.model().index(0, 0))


class GamePicker(QWidget):
    """Поле с кнопкой-шевроном и выпадающим списком процессов."""

    submitted = Signal()  # Enter в поле (Inner.KeyDown, theme.ps1:303 + VPN.ps1:301)

    def __init__(self, placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self._btn_hover = False
        self._auto_closed = False
        self.item_source: list[str] = []

        self._edit = QLineEdit(self)
        self._edit.setFrame(False)
        self._edit.setStyleSheet(_edit_qss())
        self._edit.setMouseTracking(True)
        self._edit.installEventFilter(self)
        self._edit.textChanged.connect(self._on_text_changed)

        self._pop = _DropPopup(self)
        self.setMouseTracking(True)
        self.setFont(theme.f_body())

    # ---- геометрия внутреннего поля (OnResize, theme.ps1:329-337) --------
    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        if w <= 1 or h <= 1:
            return
        lh = self._edit.fontMetrics().height()
        ih = max(14, min(lh + 2, h - 4))
        self._edit.setGeometry(10, max(1, (h - ih) // 2), max(10, w - 20 - 34), ih)

    def sizeHint(self):  # noqa: N802
        return QSize(286, 30)

    # ---- текст ------------------------------------------------------------
    def text(self) -> str:
        return self._edit.text()

    def setText(self, value: str) -> None:  # noqa: N802
        self._edit.setText(value)

    def set_items(self, items: list[str]) -> None:
        """Источник пунктов (WinForms ItemSource; заполняется при старте)."""
        self.item_source = list(items)
        self._filter_popup()

    # ---- попап ------------------------------------------------------------
    def drop_open(self) -> bool:
        return self._pop.isVisible()

    def toggle_drop(self) -> None:
        if self.drop_open():
            self.close_drop()
        else:
            self.open_drop()

    def open_drop(self) -> None:
        if not self.isEnabled() or self.drop_open():
            return
        self._filter_popup()
        if self._pop.item_count() == 0:
            return
        self._layout_popup()
        self._pop.show()
        self._pop.raise_()
        self.update()

    def close_drop(self) -> None:
        if self._pop.isVisible():
            self._pop._closing_by_code = True
            self._pop.hide()
        self.update()

    def _layout_popup(self) -> None:
        """Порт LayoutPopup (theme.ps1:362-370): под полем, иначе - над."""
        n = self._pop.item_count()
        if n == 0:
            return
        top_left = self.mapToGlobal(QPoint(0, 0))
        gx, gy = top_left.x(), top_left.y()
        h = min(8, n) * ROW_H + 8
        y = gy + self.height() + 2
        screen = QApplication.screenAt(top_left) or QApplication.primaryScreen()
        if screen is not None:
            wa = screen.availableGeometry()
            if y + h > wa.bottom():
                y = gy - 2 - h
        self._pop.setGeometry(gx, y, self.width(), h)

    def _filter_popup(self) -> None:
        """Порт FilterPopup (theme.ps1:393-404): префикс, lowerInvariant."""
        t = self._edit.text().strip().lower()
        shown = [
            it
            for it in self.item_source
            if it and (not t or it.lower().startswith(t))
        ]
        if not shown:
            self.close_drop()
            return
        self._pop.set_items(shown)
        if self.drop_open():
            self._layout_popup()

    def commit_from_popup(self, index: int) -> None:
        """Порт CommitFromPopup (theme.ps1:406-413)."""
        if index < 0 or index >= self._pop.item_count():
            return
        self._edit.setText(self._pop.list.model().item(index).text())  # type: ignore[union-attr]
        self._edit.selectAll()
        self.close_drop()
        self._edit.setFocus()

    def _on_text_changed(self) -> None:
        self._filter_popup()
        self.update()

    # ---- hover/кнопка ------------------------------------------------------
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        over = e.position().x() >= self.width() - _BTN_ZONE
        if over != self._btn_hover:
            self._btn_hover = over
            self.update()
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor
        )

    def leaveEvent(self, e) -> None:  # noqa: N802
        if self._btn_hover:
            self._btn_hover = False
            self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if e.position().x() >= self.width() - _BTN_ZONE:
            # клик по шеврону, когда попап уже закрыл Qt по клику вне
            # (Popup), - не открываем повторно: в PS такой клик просто
            # закрывал список (ToggleDrop при открытом)
            if getattr(self, "_auto_closed", False):
                self._auto_closed = False
                return
            self.toggle_drop()
        else:
            self._edit.setFocus()

    def _mark_auto_closed(self) -> None:
        """Qt.Popup закрылся по клику вне - запоминаем на текущий тик событий."""
        self._auto_closed = True
        QTimer.singleShot(0, self._clear_auto_closed)

    def _clear_auto_closed(self) -> None:
        self._auto_closed = False

    # ---- фильтр событий поля (KeyDown, theme.ps1:303-306) -----------------
    def eventFilter(self, obj, ev) -> bool:
        if obj is self._edit:
            t = ev.type()
            if t == QEvent.Type.KeyPress:
                key = ev.key()  # type: ignore[union-attr]
                if key == Qt.Key.Key_Escape:
                    self.close_drop()
                    return True
                if key in (Qt.Key.Key_Down, Qt.Key.Key_F4):
                    self.toggle_drop()
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # Enter -> добавить исключение (VPN.ps1:301, SuppressKeyPress)
                    self.submitted.emit()
                    return True
                return False
            if t in (
                QEvent.Type.MouseMove,
                QEvent.Type.Enter,
                QEvent.Type.Leave,
                QEvent.Type.FocusIn,
                QEvent.Type.FocusOut,
            ):
                # hover/фокус поля влияют на рамку - перерисовываем (300-311)
                self.update()
        return super().eventFilter(obj, ev)

    # ---- отрисовка (OnPaint, theme.ps1:415-466) ---------------------------
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if w <= 1 or h <= 1:
            return
        # hover считаем по курсору прямо при отрисовке (дословно как в PS)
        cp = self.mapFromGlobal(QCursor.pos())
        in_field = 0 <= cp.x() < w and 0 <= cp.y() < h
        over_btn = in_field and cp.x() >= w - _BTN_ZONE
        hover = in_field and not over_btn

        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, w - 2, h - 2), 7, 7)
        p.fillPath(path, QColor(19, 22, 30))
        focused = self._edit.hasFocus()
        line = (
            QColor(theme.BORDER_FOCUS)
            if focused
            else QColor(theme.BORDER_HOVER)
            if hover
            else QColor(theme.BORDER)
        )
        if focused:
            glow = QColor(theme.BORDER_FOCUS)
            glow.setAlpha(60)
            p.setPen(QPen(glow, 3))
            p.drawPath(path)
        p.setPen(QPen(line, 1))
        p.drawPath(path)

        # плейсхолдер: пусто и не в фокусе (436-443)
        if not self._edit.text() and not focused and self._placeholder:
            p.setPen(QPen(QColor(theme.PLACEHOLDER)))
            p.setFont(theme.f_body())
            ph_w = max(10, w - 40)
            p.drawText(
                QRectF(12, 1, ph_w, h - 2),
                Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                p.fontMetrics().elidedText(
                    self._placeholder, Qt.TextElideMode.ElideRight, ph_w
                ),
            )

        # кнопка-шеврон (444-459)
        bw, by = 26, 3
        bh = h - 6
        bp = QPainterPath()
        bp.addRoundedRect(QRectF(w - bw - 1, by, bw - 2, bh), 5, 5)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, QColor(52, 60, 80) if over_btn else QColor(36, 41, 54))
        g.setColorAt(1.0, QColor(36, 42, 58) if over_btn else QColor(26, 30, 40))
        p.fillPath(bp, g)
        p.setPen(QPen(QColor(100, 118, 152) if over_btn else QColor(60, 70, 92), 1))
        p.drawPath(bp)
        p.setPen(QPen(QColor(58, 66, 86, 80), 1))
        p.drawLine(w - _BTN_ZONE, by + 1, w - _BTN_ZONE, by + bh - 2)

        # шеврон-треугольник (460-465)
        if self.isEnabled():
            cx, cy = w - 15, h // 2
            tri = QPolygonF(
                [QPointF(cx - 4, cy - 2), QPointF(cx + 4, cy - 2), QPointF(cx, cy + 3)]
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(
                QColor(theme.ACCENT) if over_btn else QColor(150, 158, 176)
            )
            p.drawPolygon(tri)
