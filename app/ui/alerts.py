"""Local-only alert rules. No email/SMS/webhooks — in-app highlight + log only."""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QVBoxLayout, QWidget)

from ..models.opportunity import Opportunity


class AlertsWidget(QWidget):
    rules_changed = Signal(list)

    def __init__(self, rules: List[dict] | None = None) -> None:
        super().__init__()
        self.rules: List[dict] = rules or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(QLabel("LOCAL ALERT RULES  (net edge / liquidity / quality)"))

        editor = QHBoxLayout()
        self.min_net = QDoubleSpinBox(); self.min_net.setPrefix("net≥ "); self.min_net.setSuffix("%")
        self.min_net.setRange(0, 20); self.min_net.setValue(1.5)
        self.min_liq = QDoubleSpinBox(); self.min_liq.setPrefix("liq≥ £")
        self.min_liq.setRange(0, 100000); self.min_liq.setValue(500)
        self.min_qual = QDoubleSpinBox(); self.min_qual.setPrefix("qual≥ ")
        self.min_qual.setRange(0, 100); self.min_qual.setValue(80)
        self.sound = QCheckBox("sound")
        add = QPushButton("ADD"); add.clicked.connect(self._add)
        for w in (self.min_net, self.min_liq, self.min_qual, self.sound, add):
            editor.addWidget(w)
        layout.addLayout(editor)

        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        remove = QPushButton("REMOVE SELECTED"); remove.clicked.connect(self._remove)
        layout.addWidget(remove)
        self._render()

    def _add(self):
        self.rules.append({"min_net": self.min_net.value(), "min_liq": self.min_liq.value(),
                           "min_quality": self.min_qual.value(), "sound": self.sound.isChecked()})
        self._render()
        self.rules_changed.emit(self.rules)

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.rules):
            del self.rules[row]
            self._render()
            self.rules_changed.emit(self.rules)

    def _render(self):
        self.list.clear()
        for rule in self.rules:
            self.list.addItem(
                f"NET>{rule['min_net']:.2f}%  AND LIQ>£{rule['min_liq']:.0f}  "
                f"AND QUAL>{rule['min_quality']:.0f}" + ("  [sound]" if rule.get("sound") else ""))

    def evaluate(self, opp: Opportunity) -> bool:
        """True if the opportunity trips any rule."""
        for rule in self.rules:
            if (opp.net_edge >= rule["min_net"] and opp.liquidity >= rule["min_liq"]
                    and opp.quality.total >= rule["min_quality"]):
                return True
        return False
