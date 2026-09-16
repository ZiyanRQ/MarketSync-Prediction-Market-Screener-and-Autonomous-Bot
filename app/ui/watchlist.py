"""Starred opportunities. Persisted locally; shows live mock updates."""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..models.opportunity import Opportunity
from ..utils import formatting as fmt
from . import style


class WatchlistWidget(QWidget):
    open_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._open)
        layout.addWidget(self.list)
        self._by_row: List[Opportunity] = []

    def refresh(self, opps: List[Opportunity], watch_ids: set) -> None:
        watched = [o for o in opps if o.key in watch_ids]
        self.list.clear()
        self._by_row = watched
        for opp in watched:
            item = QListWidgetItem(
                f"{opp.market.event[:22]:<22} {opp.market.selection[:12]:<12} "
                f"net {opp.net_edge:5.2f}%  {opp.risk.value}")
            item.setForeground(QColor(style.POS if opp.net_edge > 0 else style.NEG))
            self.list.addItem(item)

    def _open(self, item):
        row = self.list.row(item)
        if 0 <= row < len(self._by_row):
            self.open_requested.emit(self._by_row[row])
