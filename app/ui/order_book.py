"""Compact dual-exchange order-book ladder.

Shows Betfair and Matchbook back/lay depth side by side with cumulative liquidity
and depth shading, and highlights the two rungs the current simulation is using.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from PySide6.QtCore import Qt

from ..models.market import Market
from ..utils import formatting as fmt
from . import style


class LadderWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self.title = QLabel("ORDER BOOK")
        self.title.setProperty("role", "hdr")
        layout.addWidget(self.title)

        self.table = QTableWidget(5, 6)
        self.table.setHorizontalHeaderLabels(
            ["BF Back", "BF Lay", "Odds", "Odds", "MB Back", "MB Lay"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(20)
        layout.addWidget(self.table)

    def _cell(self, text: str, shade: float = 0.0, colour: Optional[str] = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        if shade > 0:
            item.setBackground(QColor(31, 45, 61, int(min(1.0, shade) * 160)))
        if colour:
            item.setForeground(QColor(colour))
        return item

    def update_market(self, market: Optional[Market]) -> None:
        if market is None:
            self.table.clearContents()
            return
        bf, mb = market.betfair, market.matchbook
        self.title.setText(f"ORDER BOOK — {market.selection}")
        max_size = max([lvl.size for lvl in bf.back + bf.lay + mb.back + mb.lay] or [1])
        for r in range(5):
            def size_at(levels, i):
                return levels[i].size if i < len(levels) else 0.0

            def odds_at(levels, i):
                return levels[i].odds if i < len(levels) else None

            bf_bk, bf_ly = size_at(bf.back, r), size_at(bf.lay, r)
            mb_bk, mb_ly = size_at(mb.back, r), size_at(mb.lay, r)
            self.table.setItem(r, 0, self._cell(fmt.money_short(bf_bk), bf_bk / max_size, style.POS))
            self.table.setItem(r, 1, self._cell(fmt.money_short(bf_ly), bf_ly / max_size, style.NEG))
            self.table.setItem(r, 2, self._cell(fmt.odds(odds_at(bf.back, r))))
            self.table.setItem(r, 3, self._cell(fmt.odds(odds_at(mb.back, r))))
            self.table.setItem(r, 4, self._cell(fmt.money_short(mb_bk), mb_bk / max_size, style.POS))
            self.table.setItem(r, 5, self._cell(fmt.money_short(mb_ly), mb_ly / max_size, style.NEG))
