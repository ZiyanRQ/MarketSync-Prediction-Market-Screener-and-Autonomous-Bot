"""Simulated (paper) trading, organised into clear sections:

  BANKROLL      — pick or type a starting balance and reset.
  PERFORMANCE   — live bankroll / P&L / ROI stats.
  TRADE HISTORY — every paper trade you've booked (from the Inspector).
  WHAT-IF       — deploy a fixed stake into every qualifying arb and see the curve.

Reads opportunities via an injected provider callable — it never fetches. No real
orders are placed.
"""

from __future__ import annotations

from typing import Callable, List

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..models.trade import SimulatedTrade
from ..services.simulation_engine import SimulationEngine
from ..utils import formatting as fmt
from . import style

HISTORY_COLS = ["Time", "Event", "Selection", "Dir", "Capital", "BF", "MB",
                "Net%", "Preset", "Buf", "Profit", "ROI", "Status"]


class SimulatorWidget(QWidget):
    def __init__(self, sim: SimulationEngine, opps_provider: Callable[[], list]) -> None:
        super().__init__()
        self.sim = sim
        self.opps_provider = opps_provider

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(self._bankroll_group(), 1)
        top.addWidget(self._performance_group(), 2)
        root.addLayout(top)
        root.addWidget(self._history_group(), 1)
        root.addWidget(self._whatif_group())
        self.refresh_stats()

    # -- bankroll ----------------------------------------------------------
    def _bankroll_group(self) -> QGroupBox:
        box = QGroupBox("Bankroll")
        layout = QVBoxLayout(box)
        presets = QHBoxLayout()
        presets.setSpacing(3)
        for amount in (1000, 5000, 10000, 25000):
            btn = QPushButton(f"£{amount:,}")
            btn.clicked.connect(lambda _, a=amount: self._reset(a))
            presets.addWidget(btn)
        layout.addLayout(presets)

        custom = QHBoxLayout()
        self.custom_bankroll = QDoubleSpinBox()
        self.custom_bankroll.setPrefix("£"); self.custom_bankroll.setRange(100, 1000000)
        self.custom_bankroll.setSingleStep(500); self.custom_bankroll.setValue(5000)
        reset = QPushButton("SET / RESET")
        reset.clicked.connect(lambda: self._reset(self.custom_bankroll.value()))
        custom.addWidget(QLabel("Custom"))
        custom.addWidget(self.custom_bankroll, 1)
        custom.addWidget(reset)
        layout.addLayout(custom)
        return box

    # -- performance -------------------------------------------------------
    def _performance_group(self) -> QGroupBox:
        box = QGroupBox("Performance")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        self.stats: dict[str, QLabel] = {}
        names = ["Starting", "Current", "Available", "Locked", "Realised P&L",
                 "ROI", "Trades", "Avg Profit", "Utilisation", "Best Trade"]
        for i, name in enumerate(names):
            hdr = QLabel(name.upper()); hdr.setProperty("role", "hdr")
            val = QLabel("—"); val.setProperty("role", "value")
            r, c = divmod(i, 5)
            grid.addWidget(hdr, r * 2, c)
            grid.addWidget(val, r * 2 + 1, c)
            self.stats[name] = val
        return box

    # -- history -----------------------------------------------------------
    def _history_group(self) -> QGroupBox:
        box = QGroupBox("Trade History")
        layout = QVBoxLayout(box)
        hint = QLabel("Book a trade from the Opportunity Inspector — "
                      "select a row, then press S or click SIMULATE TRADE.")
        hint.setProperty("role", "hint")
        layout.addWidget(hint)
        self.table = QTableWidget(0, len(HISTORY_COLS))
        self.table.setHorizontalHeaderLabels(HISTORY_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        return box

    # -- what-if -----------------------------------------------------------
    def _whatif_group(self) -> QGroupBox:
        box = QGroupBox("What-if strategy")
        layout = QVBoxLayout(box)
        desc = QLabel("Deploy a fixed stake into every arb above the minimum edge, "
                      "starting from your bankroll, and plot the equity curve.")
        desc.setProperty("role", "hint")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        controls = QHBoxLayout()
        self.stake = QDoubleSpinBox(); self.stake.setPrefix("stake £"); self.stake.setRange(1, 100000)
        self.stake.setValue(100)
        self.min_edge = QDoubleSpinBox(); self.min_edge.setPrefix("min edge "); self.min_edge.setSuffix("%")
        self.min_edge.setRange(0, 20); self.min_edge.setValue(1.0); self.min_edge.setSingleStep(0.25)
        run = QPushButton("RUN WHAT-IF"); run.clicked.connect(self._run_whatif)
        controls.addWidget(self.stake)
        controls.addWidget(self.min_edge)
        controls.addWidget(run)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.whatif_out = QLabel("Run a scenario to see the result.")
        self.whatif_out.setProperty("role", "value")
        layout.addWidget(self.whatif_out)

        self.equity = pg.PlotWidget()
        self.equity.setBackground(style.PANEL)
        self.equity.showGrid(x=True, y=True, alpha=0.15)
        self.equity.setLabel("left", "bankroll £")
        self.equity.getAxis("left").setPen(style.MUTED)
        self.equity.getAxis("bottom").setPen(style.MUTED)
        self.equity.setMaximumHeight(150)
        self.equity_curve = self.equity.plot([], [], pen=pg.mkPen(style.POS, width=2))
        layout.addWidget(self.equity)
        return box

    # -- data --------------------------------------------------------------
    def _reset(self, amount: float) -> None:
        self.sim.reset_bankroll(amount)
        self.table.setRowCount(0)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        b = self.sim.bankroll
        avg = (b.realised / b.trades) if b.trades else 0.0
        util = (b.locked / b.current * 100) if b.current else 0.0
        best = max((t.theoretical_profit for t in self.sim.history), default=0.0)
        values = {
            "Starting": fmt.money(b.starting), "Current": fmt.money(b.current),
            "Available": fmt.money(b.available), "Locked": fmt.money(b.locked),
            "Realised P&L": fmt.signed_money(b.realised), "ROI": fmt.pct(b.roi),
            "Trades": str(b.trades), "Avg Profit": fmt.money(avg),
            "Utilisation": fmt.pct(util), "Best Trade": fmt.money(best),
        }
        for name, text in values.items():
            self.stats[name].setText(text)
        self.stats["Realised P&L"].setStyleSheet(
            f"color: {style.POS if b.realised >= 0 else style.NEG};")

    def add_trade(self, trade: SimulatedTrade) -> None:
        r = 0
        self.table.insertRow(r)  # newest first
        cells = [fmt.clock(trade.ts), trade.event, trade.selection, trade.direction,
                 fmt.money(trade.capital), fmt.odds(trade.betfair_odds),
                 fmt.odds(trade.matchbook_odds), fmt.pct(trade.net_edge), trade.risk_preset,
                 fmt.pct(trade.buffer), fmt.signed_money(trade.theoretical_profit),
                 fmt.pct(trade.roi), trade.status]
        for c, text in enumerate(cells):
            self.table.setItem(r, c, QTableWidgetItem(text))
        self.refresh_stats()

    def load_history(self, trades: List[SimulatedTrade]) -> None:
        self.table.setRowCount(0)
        for trade in trades:
            self.add_trade(trade)

    def _run_whatif(self) -> None:
        from ..models.risk_profile import RiskProfile
        opps = self.opps_provider()
        result = self.sim.whatif(opps, self.stake.value(), self.min_edge.value(),
                                 RiskProfile("WHATIF", 0.0, 0.0), self.sim.bankroll.starting)
        self.whatif_out.setText(
            f"End £{result['ending']:,.2f}   profit {fmt.signed_money(result['profit'])}   "
            f"ROI {fmt.pct(result['roi'])}   trades {result['count']}   "
            f"avg edge {fmt.pct(result['avg_edge'])}")
        self.equity_curve.setData(list(range(len(result["curve"]))), result["curve"])
