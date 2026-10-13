# -*- coding: utf-8 -*-
"""Векторные иконки интерфейса (макет GPT, 13.10.2026).

Требование макета: только вектор, без эмодзи и без внешних картинок/шрифтов.
Каждая иконка — путь в системе координат 24x24 (как SVG в макете),
рисуется штрихом с круглыми срезами; масштаб под размер виджета.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

_PEN_W = 1.7  # толщина штриха в координатах 24x24

_CACHE: dict[str, QPainterPath] = {}


def _line(p: QPainterPath, x1: float, y1: float, x2: float, y2: float) -> None:
    p.moveTo(x1, y1)
    p.lineTo(x2, y2)


def _path(name: str) -> QPainterPath:
    """Путь иконки (кэшируется: строится один раз на процесс)."""
    cached = _CACHE.get(name)
    if cached is not None:
        return cached

    p = QPainterPath()
    if name == "link":
        # две звеньевые полукруглые «цепи» (макет: link-глиф)
        p.addEllipse(QRectF(3.5, 13.0, 7.0, 7.0))
        p.addEllipse(QRectF(13.5, 4.0, 7.0, 7.0))
        _line(p, 10.0, 14.0, 14.0, 10.0)
    elif name == "globe":
        p.addEllipse(QRectF(3.0, 3.0, 18.0, 18.0))
        p.addEllipse(QRectF(8.0, 3.0, 8.0, 18.0))
        _line(p, 3.0, 12.0, 21.0, 12.0)
    elif name == "target":
        # перекрестие в круге — секция исключений
        p.addEllipse(QRectF(4.0, 4.0, 16.0, 16.0))
        _line(p, 12.0, 3.0, 12.0, 21.0)
        _line(p, 3.0, 12.0, 21.0, 12.0)
    elif name == "shield":
        # щит с часами — секция подключения (макет: shield + clock)
        p.moveTo(12.0, 3.0)
        p.lineTo(20.0, 7.0)
        p.lineTo(20.0, 12.0)
        p.cubicTo(20.0, 17.0, 16.5, 20.0, 12.0, 21.0)
        p.cubicTo(7.5, 20.0, 4.0, 17.0, 4.0, 12.0)
        p.lineTo(4.0, 7.0)
        p.closeSubpath()
        _line(p, 12.0, 8.0, 12.0, 12.5)
        _line(p, 12.0, 12.5, 15.0, 14.5)
    elif name == "shield_check":
        # щит с галкой — логотип в шапке (макет: brand-mark)
        p.moveTo(12.0, 3.0)
        p.lineTo(20.0, 7.0)
        p.lineTo(20.0, 12.0)
        p.cubicTo(20.0, 17.0, 16.5, 20.0, 12.0, 21.0)
        p.cubicTo(7.5, 20.0, 4.0, 17.0, 4.0, 12.0)
        p.lineTo(4.0, 7.0)
        p.closeSubpath()
        _line(p, 9.0, 12.0, 11.2, 14.2)
        _line(p, 11.2, 14.2, 15.2, 9.8)
    elif name == "download":
        _line(p, 12.0, 3.0, 12.0, 15.0)
        _line(p, 7.0, 10.0, 12.0, 15.0)
        _line(p, 17.0, 10.0, 12.0, 15.0)
        _line(p, 5.0, 16.0, 5.0, 20.0)
        _line(p, 5.0, 20.0, 19.0, 20.0)
        _line(p, 19.0, 20.0, 19.0, 16.0)
    elif name == "pulse":
        # пульс (макет: activity-линия) — «Проверить пинг»
        p.moveTo(2.0, 12.0)
        p.lineTo(6.0, 12.0)
        p.lineTo(9.0, 4.0)
        p.lineTo(14.0, 20.0)
        p.lineTo(17.0, 12.0)
        p.lineTo(22.0, 12.0)
    elif name == "doc":
        # документ — «Открыть лог»
        p.moveTo(5.0, 3.0)
        p.lineTo(14.0, 3.0)
        p.lineTo(19.0, 8.0)
        p.lineTo(19.0, 21.0)
        p.lineTo(5.0, 21.0)
        p.closeSubpath()
        _line(p, 14.0, 3.0, 14.0, 8.0)
        _line(p, 14.0, 8.0, 19.0, 8.0)
        _line(p, 8.0, 12.0, 16.0, 12.0)
        _line(p, 8.0, 16.0, 16.0, 16.0)
    elif name == "plus":
        _line(p, 12.0, 5.0, 12.0, 19.0)
        _line(p, 5.0, 12.0, 19.0, 12.0)
    elif name == "arrow":
        _line(p, 5.0, 12.0, 19.0, 12.0)
        _line(p, 13.0, 6.0, 19.0, 12.0)
        _line(p, 13.0, 18.0, 19.0, 12.0)
    elif name == "stop":
        p.addRoundedRect(QRectF(5.0, 5.0, 14.0, 14.0), 2.0, 2.0)
    elif name == "check":
        _line(p, 5.0, 12.0, 9.5, 16.5)
        _line(p, 9.5, 16.5, 19.0, 7.0)
    else:
        # неизвестное имя — пустой путь (падать не должны)
        _line(p, 0.0, 0.0, 0.0, 0.0)
    _CACHE[name] = p
    return p


def paint(
    painter: QPainter,
    name: str,
    rect: QRectF,
    color: QColor,
    pen_w: float = _PEN_W,
) -> None:
    """Нарисовать иконку `name` внутри `rect` цветом `color`."""
    painter.save()
    side = min(rect.width(), rect.height())
    scale = side / 24.0
    painter.translate(
        rect.x() + (rect.width() - side) / 2.0,
        rect.y() + (rect.height() - side) / 2.0,
    )
    painter.scale(scale, scale)
    pen = QPen(QColor(color), pen_w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_path(name))
    painter.restore()


class Icon(QWidget):
    """Отдельная иконка-виджет (заголовки секций)."""

    def __init__(
        self, name: str, size: int = 14, color: QColor | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._color = QColor(color) if color is not None else QColor(188, 162, 255)
        self.setFixedSize(size, size)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint(p, self._name, QRectF(0, 0, self.width(), self.height()), self._color)
