"""Opportunity Inspector: depth-aware investment simulator, risk breakdown,
profit-vs-investment chart, quality breakdown, lifetime sparkline and ladder.

Everything here is computed locally from the selected Opportunity — changing the
capital or clicking the chart never refetches market data.
"""

from __future__ import annotations

from typing import List, Optional

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

from ..models.opportunity import Opportunity
from ..services.risk_engine import RiskEngine
from ..services.simulation_engine import SimulationEngine
from ..utils import calculations as calc
from ..utils import formatting as fmt
from . import style
from .order_book import LadderWidget

QUICK_AMOUNTS = [10, 25, 50, 100, 250, 500, 1000]


class _Val(QLabel):
    def __init__(self, text="—"):
        super().__init__(text)
        self.setProperty("role", "value")


class InspectorWidget(QWidget):
    simulate_requested = Signal(object, float)   # (Opportunity, capital)
    watch_toggled = Signal(object)

    def __init__(self, sim: SimulationEngine, risk: RiskEngine) -> None:
        super().__init__()
        self.sim = sim
        self.risk = risk
        self.opp: Optional[Opportunity] = None
        self._curve: List[calc.SimResult] = []
        self._max_exec = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.header = QLabel("No opportunity selected")
        self.header.setWordWrap(True)
        self.header.setProperty("role", "value")
        root.addWidget(self.header)

        root.addLayout(self._build_capital_controls())
        root.addLayout(self._build_quick_buttons())
        root.addWidget(self._build_values_grid())
        root.addWidget(self._build_tabs(), 1)

        self.sim_btn = QPushButton("SIMULATE TRADE  (S)")
        self.sim_btn.clicked.connect(self._simulate)
        root.addWidget(self.sim_btn)

    # -- build -------------------------------------------------------------
    def _build_capital_controls(self):
        row = QHBoxLayout()
        row.setSpacing(4)
        self.capital = QDoubleSpinBox()
        self.capital.setRange(0, 100000)
        self.capital.setPrefix("£")
        self.capital.setValue(100)
        self.capital.valueChanged.connect(self._on_capital)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self._on_slider)
        row.addWidget(QLabel("CAPITAL"))
        row.addWidget(self.capital)
        row.addWidget(self.slider, 1)
        return row

    def _build_quick_buttons(self):
        row = QHBoxLayout()
        row.setSpacing(3)
        for amount in QUICK_AMOUNTS:
            btn = QPushButton(f"£{amount}")
            btn.setMaximumWidth(52)
            btn.clicked.connect(lambda _, a=amount: self.capital.setValue(a))
            row.addWidget(btn)
        for label, fn in [("MAX", self._set_max_exec), ("BEST ROI", self._set_best_roi),
                          ("MAX £", self._set_max_profit)]:
            btn = QPushButton(label)
            btn.setMaximumWidth(64)
            btn.clicked.connect(fn)
            row.addWidget(btn)
        return row

    def _build_values_grid(self) -> QWidget:
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(1)
        self.vals = {}
        fields = ["Capital", "BF Stake", "MB Stake", "Liability", "Gross Profit",
                  "Commission", "Net Profit", "Net ROI", "Safety Buffer", "Buffered Edge",
                  "Max Executable", "Max Profit", "If Win", "If Lose"]
        for i, name in enumerate(fields):
            hdr = QLabel(name.upper())
            hdr.setProperty("role", "hdr")
            val = _Val()
            r, c = divmod(i, 2)
            grid.addWidget(hdr, r, c * 2)
            grid.addWidget(val, r, c * 2 + 1)
            self.vals[name] = val
        return box

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        # Profit vs investment
        self.profit_plot = pg.PlotWidget()
        self._style_plot(self.profit_plot, "capital £", "net profit £")
        self.profit_curve_item = self.profit_plot.plot([], [], pen=pg.mkPen(style.ACCENT, width=2))
        self.markers = pg.ScatterPlotItem(size=9, pen=pg.mkPen(None))
        self.profit_plot.addItem(self.markers)
        self.cursor = pg.InfiniteLine(angle=90, pen=pg.mkPen(style.WARN, style=Qt.PenStyle.DashLine))
        self.profit_plot.addItem(self.cursor)
        self.profit_plot.scene().sigMouseClicked.connect(self._chart_click)
        tabs.addTab(self.profit_plot, "Profit")

        # Quality breakdown
        self.quality_label = QLabel()
        self.quality_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        tabs.addTab(self.quality_label, "Quality")

        # Lifetime sparkline
        self.life_plot = pg.PlotWidget()
        self._style_plot(self.life_plot, "", "net edge %")
        self.life_curve = self.life_plot.plot([], [], pen=pg.mkPen(style.POS, width=2))
        self.life_label = QLabel()
        life_box = QWidget()
        life_layout = QVBoxLayout(life_box)
        life_layout.setContentsMargins(0, 0, 0, 0)
        life_layout.addWidget(self.life_label)
        life_layout.addWidget(self.life_plot, 1)
        tabs.addTab(life_box, "Lifetime")

        # Ladder
        self.ladder = LadderWidget()
        tabs.addTab(self.ladder, "Ladder")
        return tabs

    def _style_plot(self, plot: pg.PlotWidget, xlabel: str, ylabel: str) -> None:
        plot.setBackground(style.PANEL)
        plot.showGrid(x=True, y=True, alpha=0.15)
        plot.getAxis("left").setPen(style.MUTED)
        plot.getAxis("bottom").setPen(style.MUTED)
        plot.getAxis("left").setTextPen(style.MUTED)
        plot.getAxis("bottom").setTextPen(style.MUTED)
        if xlabel:
            plot.setLabel("bottom", xlabel)
        if ylabel:
            plot.setLabel("left", ylabel)

    # -- selection ---------------------------------------------------------
    def set_opportunity(self, opp: Optional[Opportunity]) -> None:
        self.opp = opp
        if opp is None:
            self.header.setText("No opportunity selected")
            self._curve = []
            self.profit_curve_item.setData([], [])
            self.markers.setData([])
            return
        self.header.setText(
            f"{opp.market.event} — {opp.market.selection}   [{opp.direction.value}]   "
            f"back {fmt.odds(opp.back_odds)}@{opp.back_venue} / lay {fmt.odds(opp.lay_odds)}@{opp.lay_venue}")
        self._max_exec = self.sim.max_executable(opp)
        self._curve = self.sim.profit_curve(opp)
        top = max(self._max_exec * 1.15, 100)
        self.capital.blockSignals(True)
        self.capital.setMaximum(max(top, 1000))
        self.capital.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setRange(0, int(max(top, 1)))
        self.slider.blockSignals(False)
        if self.capital.value() > top:
            self.capital.setValue(min(100, top))
        self._draw_curve()
        self._recompute()

    # -- capital handlers --------------------------------------------------
    def _on_capital(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.slider.blockSignals(False)
        self._recompute()

    def _on_slider(self, value):
        self.capital.setValue(float(value))

    def _set_max_exec(self):
        self.capital.setValue(round(self._max_exec, 2))

    def _set_best_roi(self):
        if self._curve:
            best = max(self._curve, key=lambda r: r.net_roi)
            self.capital.setValue(round(best.capital, 2))

    def _set_max_profit(self):
        if self._curve:
            best = max(self._curve, key=lambda r: r.net_profit)
            self.capital.setValue(round(best.capital, 2))

    def _chart_click(self, event):
        vb = self.profit_plot.getViewBox()
        point = vb.mapSceneToView(event.scenePos())
        if point.x() > 0:
            self.capital.setValue(round(point.x(), 2))

    # -- compute + render --------------------------------------------------
    def _recompute(self):
        if self.opp is None:
            return
        opp = self.opp
        res = self.sim.simulate(opp, self.capital.value())
        best_roi = max(self._curve, key=lambda r: r.net_roi) if self._curve else res
        max_profit = max(self._curve, key=lambda r: r.net_profit) if self._curve else res
        v = self.vals
        v["Capital"].setText(fmt.money(res.capital))
        v["BF Stake"].setText(fmt.money(res.back_stake if opp.back_venue == "Betfair" else res.lay_stake))
        v["MB Stake"].setText(fmt.money(res.lay_stake if opp.back_venue == "Betfair" else res.back_stake))
        v["Liability"].setText(fmt.money(res.lay_liability))
        v["Gross Profit"].setText(fmt.money(res.gross_profit))
        v["Commission"].setText(fmt.signed_money(-res.commission))
        v["Net Profit"].setText(fmt.signed_money(res.net_profit))
        v["Net ROI"].setText(fmt.pct(res.net_roi))
        v["Safety Buffer"].setText(fmt.pct(opp.safety_buffer))
        v["Buffered Edge"].setText(fmt.pct(opp.buffered_edge))
        v["Max Executable"].setText(fmt.money(self._max_exec))
        v["Max Profit"].setText(fmt.money(max_profit.net_profit))
        v["If Win"].setText(fmt.signed_money(res.profit_if_win))
        v["If Lose"].setText(fmt.signed_money(res.profit_if_lose))
        self._color(v["Net Profit"], res.net_profit)
        self._color(v["Buffered Edge"], opp.buffered_edge)
        self.cursor.setValue(res.capital)
        self._render_quality()
        self._render_lifetime()
        self.ladder.update_market(opp.market)

    def _color(self, label, value):
        label.setStyleSheet(f"color: {style.POS if value >= 0 else style.NEG};")

    def _draw_curve(self):
        if not self._curve:
            self.profit_curve_item.setData([], [])
            self.markers.setData([])
            return
        xs = [r.capital for r in self._curve]
        ys = [r.net_profit for r in self._curve]
        self.profit_curve_item.setData(xs, ys)
        best_roi = max(self._curve, key=lambda r: r.net_roi)
        max_profit = max(self._curve, key=lambda r: r.net_profit)
        self.markers.setData([
            {"pos": (best_roi.capital, best_roi.net_profit), "brush": style.POS, "symbol": "o"},
            {"pos": (max_profit.capital, max_profit.net_profit), "brush": style.WARN, "symbol": "t"},
            {"pos": (self._max_exec, 0), "brush": style.NEG, "symbol": "x"},
        ])

    def _render_quality(self):
        q = self.opp.quality
        rows = [("Profitability", q.profitability, 20), ("Liquidity", q.liquidity, 20),
                ("Freshness", q.freshness, 20), ("Stability", q.stability, 20),
                ("Market Match", q.market_match, 10), ("Execution Risk", q.execution_risk, 10)]
        lines = [f"<b>QUALITY {q.total:.0f}/100</b>", ""]
        for name, val, mx in rows:
            bars = int(val / mx * 12)
            lines.append(f"{name:<14} {val:4.0f}/{mx:<2}  {'█' * bars}{'·' * (12 - bars)}")
        self.quality_label.setText("<pre>" + "\n".join(lines) + "</pre>")

    def _render_lifetime(self):
        opp = self.opp
        hist = list(opp.edge_history)
        self.life_curve.setData(list(range(len(hist))), hist)
        self.life_label.setText(
            f"<pre>edge {opp.net_edge:5.2f}%   peak {opp.peak_edge:5.2f}%   "
            f"avg {opp.average_edge():5.2f}%   low {opp.low_edge:5.2f}%\n"
            f"age {fmt.age(opp.age_seconds):>5}   price-changes {opp.price_changes:<4}   "
            f"vol {opp.volatility:.1f}%</pre>")

    def live_refresh(self) -> None:
        """Refresh values for the selected opportunity as prices tick (no curve
        rebuild — the profit curve is recomputed only when the selection changes)."""
        if self.opp is not None:
            self._recompute()

    def _simulate(self):
        if self.opp is not None:
            self.simulate_requested.emit(self.opp, self.capital.value())
