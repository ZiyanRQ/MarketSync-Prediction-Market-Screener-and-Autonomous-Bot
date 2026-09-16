"""API Usage dashboard + developer call inspector (mock metrics for now)."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QGridLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..models.enums import UsageState
from ..services.api_usage_tracker import ApiUsageTracker
from ..services.cache_service import CacheService
from ..utils import formatting as fmt
from . import style

_STATE_COLOUR = {UsageState.LOW: style.POS, UsageState.MODERATE: style.WARN,
                 UsageState.HIGH: style.WARN, UsageState.CRITICAL: style.NEG}
INSPECTOR_COLS = ["Time", "Provider", "Operation", "Target", "Cache", "Cost", "Dur", "Reason"]


class ApiUsageWidget(QWidget):
    def __init__(self, usage: ApiUsageTracker, cache: CacheService) -> None:
        super().__init__()
        self.usage = usage
        self.cache = cache

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.state_label = QLabel("API LOW")
        self.state_label.setProperty("role", "value")
        layout.addWidget(self.state_label)

        self.metrics: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(1)
        names = ["BF Req/min", "BF Today", "BF Avg", "MB Req/min", "MB Today", "MB Avg",
                 "Calls/hour", "Cache Size", "Cache Hit%", "Dupes Avoided"]
        for i, name in enumerate(names):
            hdr = QLabel(name.upper()); hdr.setProperty("role", "hdr")
            val = QLabel("—"); val.setProperty("role", "value")
            r, c = divmod(i, 5)
            grid.addWidget(hdr, r * 2, c)
            grid.addWidget(val, r * 2 + 1, c)
            self.metrics[name] = val
        layout.addLayout(grid)

        self.table = QTableWidget(0, len(INSPECTOR_COLS))
        self.table.setHorizontalHeaderLabels(INSPECTOR_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        state = self.usage.state()
        self.state_label.setText(f"API {state.value}")
        self.state_label.setStyleSheet(f"color: {_STATE_COLOUR[state]};")
        bf = self.usage.provider_metrics("Betfair", self.cache)
        mb = self.usage.provider_metrics("Matchbook", self.cache)
        self.metrics["BF Req/min"].setText(bf["Requests / min"])
        self.metrics["BF Today"].setText(bf["Requests today"])
        self.metrics["BF Avg"].setText(bf["Avg response"])
        self.metrics["MB Req/min"].setText(mb["Requests / min"])
        self.metrics["MB Today"].setText(mb["Requests today"])
        self.metrics["MB Avg"].setText(mb["Avg response"])
        self.metrics["Calls/hour"].setText(str(self.usage.per_hour_estimate()))
        self.metrics["Cache Size"].setText(str(self.cache.size))
        self.metrics["Cache Hit%"].setText(fmt.pct(self.cache.hit_rate, 0))
        self.metrics["Dupes Avoided"].setText(str(self.cache.duplicates_avoided))

        recent = list(self.usage.calls)[-40:][::-1]
        self.table.setRowCount(len(recent))
        for r, call in enumerate(recent):
            cells = [fmt.clock(call.ts, with_millis=True), call.provider, call.operation,
                     call.target, "HIT" if call.cache_hit else "MISS",
                     f"{call.cost}", f"{call.duration_ms}ms", call.reason]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 4:
                    item.setForeground(QColor(style.POS if call.cache_hit else style.WARN))
                self.table.setItem(r, c, item)
