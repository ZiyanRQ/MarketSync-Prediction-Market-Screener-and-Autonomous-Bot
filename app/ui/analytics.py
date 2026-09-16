"""Compare risk presets — selectivity vs signal count vs simulated profit."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..models.opportunity import Opportunity
from ..services.simulation_engine import SimulationEngine
from ..utils import formatting as fmt


class AnalyticsWidget(QWidget):
    def __init__(self, sim: SimulationEngine) -> None:
        super().__init__()
        self.sim = sim
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        title = QLabel("PRESET COMPARISON  (simulated £100 into every qualifying arb)")
        title.setProperty("role", "hdr")
        layout.addWidget(title)
        self.table = QTableWidget(3, 4)
        self.table.setHorizontalHeaderLabels(["Preset", "Signals", "Avg Net Edge", "Sim Profit"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

    def refresh(self, opps: List[Opportunity]) -> None:
        stats = self.sim.compare_presets(opps)
        for r, (name, data) in enumerate(stats.items()):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(str(data["signals"])))
            self.table.setItem(r, 2, QTableWidgetItem(fmt.pct(data["avg_edge"])))
            self.table.setItem(r, 3, QTableWidgetItem(fmt.money(data["profit"])))
