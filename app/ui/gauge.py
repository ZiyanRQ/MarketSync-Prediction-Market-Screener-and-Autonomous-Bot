"""A compact semicircular gauge (QPainter) for glanceable metrics like drawdown."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import style


class GaugeWidget(QWidget):
    def __init__(self, title: str = "") -> None:
        super().__init__()
        self._title = title
        self._value = 0.0
        self._max = 1.0
        self._text = "—"
        self.setMinimumSize(150, 110)

    def set_value(self, value: float, maximum: float, text: str) -> None:
        self._value = max(0.0, value)
        self._max = max(1e-6, maximum)
        self._text = text
        self.update()

    def _colour(self, frac: float) -> str:
        return style.POS if frac < 0.4 else style.WARN if frac < 0.75 else style.NEG

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 14
        rect = QRectF(margin, margin, w - 2 * margin, (h - 2 * margin) * 2)
        frac = min(1.0, self._value / self._max)

        # Track (180° arc) then the value arc on top.
        p.setPen(QPen(QColor(style.BORDER), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 180 * 16, -180 * 16)
        p.setPen(QPen(QColor(self._colour(frac)), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 180 * 16, int(-180 * 16 * frac))

        # Centre value + title.
        p.setPen(QColor(style.TEXT))
        f = QFont(self.font()); f.setPointSize(13); f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, h * 0.42, w, 22), Qt.AlignmentFlag.AlignCenter, self._text)
        p.setPen(QColor(style.MUTED))
        f2 = QFont(self.font()); f2.setPointSize(8)
        p.setFont(f2)
        p.drawText(QRectF(0, 0, w, 16), Qt.AlignmentFlag.AlignCenter, self._title)
        p.end()
