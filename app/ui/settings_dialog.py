"""Settings + risk-preset editor.

The editor operates on the live RiskEngine (new / duplicate / rename / save /
delete / restore defaults). General settings return commissions + refresh interval.
"""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from ..models.risk_profile import RiskProfile
from ..services.risk_engine import RiskEngine


class SettingsDialog(QDialog):
    def __init__(self, risk: RiskEngine, settings: Dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.risk = risk
        self.settings = dict(settings)
        self.resize(520, 460)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._risk_tab(), "Risk Presets")
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._budget_tab(), "API Budget")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._reload_list()

    # -- risk presets ------------------------------------------------------
    def _risk_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        self.preset_list = QListWidget()
        self.preset_list.currentTextChanged.connect(self._load_preset)
        outer.addWidget(self.preset_list, 1)

        form_box = QVBoxLayout()
        form = QFormLayout()
        self.f_name = QLineEdit()
        self.f_buffer = self._spin(0, 10, 0.25, "%")
        self.f_minnet = self._spin(0, 20, 0.25, "%")
        self.f_minliq = self._spin(0, 100000, 100, "£", prefix=True)
        self.f_maxage = self._spin(0, 600, 5, "s")
        self.f_minqual = self._spin(0, 100, 5, "")
        self.f_maxvol = self._spin(0, 100, 1, "%")
        self.f_maxexp = self._spin(0, 1000000, 500, "£", prefix=True)
        self.f_maxstake = self._spin(0, 1000000, 100, "£", prefix=True)
        form.addRow("Name", self.f_name)
        form.addRow("Safety buffer", self.f_buffer)
        form.addRow("Min net edge", self.f_minnet)
        form.addRow("Min liquidity", self.f_minliq)
        form.addRow("Max price age", self.f_maxage)
        form.addRow("Min quality", self.f_minqual)
        form.addRow("Max volatility", self.f_maxvol)
        form.addRow("Max exposure", self.f_maxexp)
        form.addRow("Max stake", self.f_maxstake)
        form_box.addLayout(form)

        actions = QHBoxLayout()
        for label, fn in [("New", self._new), ("Duplicate", self._duplicate),
                          ("Rename", self._rename), ("Save", self._save),
                          ("Delete", self._delete), ("Restore", self._restore)]:
            btn = QPushButton(label); btn.clicked.connect(fn)
            actions.addWidget(btn)
        form_box.addLayout(actions)
        outer.addLayout(form_box, 2)
        return page

    def _spin(self, lo, hi, step, suffix, prefix=False) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(lo, hi); box.setSingleStep(step)
        if prefix:
            box.setPrefix(suffix)
        elif suffix:
            box.setSuffix(suffix)
        return box

    def _reload_list(self):
        self.preset_list.clear()
        self.preset_list.addItems(list(self.risk.profiles.keys()))
        self._select(self.risk.active_name)

    def _select(self, name: str) -> None:
        matches = self.preset_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if matches:
            self.preset_list.setCurrentItem(matches[0])

    def _current_name(self) -> str:
        item = self.preset_list.currentItem()
        return item.text() if item else ""

    def _load_preset(self, name: str):
        prof = self.risk.profiles.get(name)
        if not prof:
            return
        self.f_name.setText(prof.name)
        self.f_buffer.setValue(prof.safety_buffer)
        self.f_minnet.setValue(prof.min_net_edge)
        self.f_minliq.setValue(prof.min_liquidity)
        self.f_maxage.setValue(prof.max_price_age)
        self.f_minqual.setValue(prof.min_quality)
        self.f_maxvol.setValue(prof.max_volatility)
        self.f_maxexp.setValue(prof.max_exposure)
        self.f_maxstake.setValue(prof.max_stake)

    def _current_from_form(self) -> RiskProfile:
        return RiskProfile(
            name=self.f_name.text().strip() or "UNNAMED",
            safety_buffer=self.f_buffer.value(), min_net_edge=self.f_minnet.value(),
            min_liquidity=self.f_minliq.value(), max_price_age=self.f_maxage.value(),
            min_quality=self.f_minqual.value(), max_volatility=self.f_maxvol.value(),
            max_exposure=self.f_maxexp.value(), max_stake=self.f_maxstake.value())

    def _new(self):
        self.risk.upsert(RiskProfile("NEW PRESET", 1.0, 0.5))
        self._reload_list(); self._select("NEW PRESET")

    def _duplicate(self):
        prof = self._current_from_form()
        prof.name = prof.name + " COPY"
        prof.builtin = False
        self.risk.upsert(prof)
        self._reload_list(); self._select(prof.name)

    def _rename(self):
        old = self._current_name()
        new, ok = QInputDialog.getText(self, "Rename preset", "New name:", text=old)
        if ok and new:
            prof = self.risk.profiles.get(old)
            if prof and not prof.builtin:
                self.risk.delete(old)
                prof.name = new
                self.risk.upsert(prof)
                self._reload_list(); self._select(new)

    def _save(self):
        prof = self._current_from_form()
        prof.builtin = self.risk.profiles.get(prof.name, RiskProfile("", 0, 0)).builtin
        self.risk.upsert(prof)
        self._reload_list(); self._select(prof.name)

    def _delete(self):
        self.risk.delete(self._current_name())
        self._reload_list()

    def _restore(self):
        self.risk.restore_defaults()
        self._reload_list()

    # -- general -----------------------------------------------------------
    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.c_betfair = self._spin(0, 20, 0.5, "%")
        self.c_betfair.setValue(self.settings.get("commission_betfair", 2.0))
        self.c_matchbook = self._spin(0, 20, 0.5, "%")
        self.c_matchbook.setValue(self.settings.get("commission_matchbook", 2.0))
        self.refresh_ms = QSpinBox(); self.refresh_ms.setRange(500, 10000)
        self.refresh_ms.setSingleStep(250)
        self.refresh_ms.setValue(int(self.settings.get("refresh_ms", 1500)))
        form.addRow("Betfair commission", self.c_betfair)
        form.addRow("Matchbook commission", self.c_matchbook)
        form.addRow("Refresh interval (ms)", self.refresh_ms)
        return page

    def _budget_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        note = QLabel("Mock budget controls for future live integration.")
        form.addRow(note)
        self.b_per_min = QSpinBox(); self.b_per_min.setRange(1, 10000); self.b_per_min.setValue(120)
        self.b_markets = QSpinBox(); self.b_markets.setRange(1, 10000); self.b_markets.setValue(200)
        form.addRow("Max requests/min", self.b_per_min)
        form.addRow("Max active markets", self.b_markets)
        return page

    def result_settings(self) -> Dict:
        return {
            "commission_betfair": self.c_betfair.value(),
            "commission_matchbook": self.c_matchbook.value(),
            "refresh_ms": self.refresh_ms.value(),
        }
