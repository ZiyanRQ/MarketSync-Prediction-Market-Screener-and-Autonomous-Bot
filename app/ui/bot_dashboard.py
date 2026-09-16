"""Bot Terminal — the Auto-Trader's own rich dashboard.

Metric tiles, a drawdown gauge, performance charts (equity / per-trade / edge), a
full editable strategy with saved presets, and an activity feed. Lives as a dock
AND pops out into its own window (DetachWindow), reparented so state is preserved.

Money model shown to the user: DEPOSIT (allocated capital) → BALANCE (deposit + P&L),
with a MIN/MAX stake band per trade. No "capital vs bankroll" ambiguity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, Tuple

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QMainWindow, QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ..services.auto_trader import AutoTrader
from ..utils import formatting as fmt
from . import style
from .gauge import GaugeWidget

STAKE_MODES = {"Fixed £": "fixed", "% of liquidity": "pct_liquidity", "% of deposit": "pct_deposit"}
STAKE_MODES_REV = {v: k for k, v in STAKE_MODES.items()}
SPORTS = ["ALL", "Football", "Tennis", "Basketball", "Horse Racing"]

METRICS = ["Balance", "Deposit", "Bot P&L", "ROI", "Trades", "Win %", "Avg / Trade",
           "Best", "Worst", "Max DD", "Staked", "Trades Left"]


class DetachWindow(QMainWindow):
    """Top-level window that hosts the dashboard when popped out."""
    closed = Signal()

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)


class BotDashboard(QWidget):
    detach_toggled = Signal(bool)

    def __init__(self, bot: AutoTrader, on_change: Callable[[], None],
                 get_presets: Callable[[], dict], save_presets: Callable[[dict], None]) -> None:
        super().__init__()
        self.bot = bot
        self.cfg = bot.config
        self.on_change = on_change
        self.get_presets = get_presets
        self.save_presets = save_presets
        self.detached = False

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.addLayout(self._control_bar())
        root.addWidget(self._metrics_row())
        self.strategy_summary = QLabel("—")
        self.strategy_summary.setProperty("role", "hint")
        self.strategy_summary.setWordWrap(True)
        root.addWidget(self.strategy_summary)
        root.addWidget(self._body(), 1)

        self.bot.stats_changed.connect(self.refresh)
        self.bot.logline.connect(self._log)
        self._reload_presets()
        self._load_from_config()
        self.refresh()

    # -- control bar -------------------------------------------------------
    def _control_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.enable_btn = QPushButton("BOT: OFF")
        self.enable_btn.setObjectName("botToggle")
        self.enable_btn.setCheckable(True)
        self.enable_btn.toggled.connect(self._toggle_enabled)
        self.status = QLabel("idle")
        self.status.setProperty("role", "value")
        reset = QPushButton("Reset stats")
        reset.clicked.connect(self.bot.reset_stats)
        self.detach_btn = QPushButton("Pop out ↗")
        self.detach_btn.setToolTip("Open the bot in its own window")
        self.detach_btn.clicked.connect(self._toggle_detach)
        row.addWidget(self.enable_btn)
        row.addWidget(self.status)
        row.addStretch(1)
        row.addWidget(QLabel("PAPER — no real orders"))
        row.addWidget(reset)
        row.addWidget(self.detach_btn)
        return row

    # -- metrics + gauge ---------------------------------------------------
    def _metrics_row(self) -> QWidget:
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.tiles: Dict[str, QLabel] = {}
        for i, name in enumerate(METRICS):
            frame = QFrame(); frame.setObjectName("tile")
            fl = QVBoxLayout(frame); fl.setContentsMargins(6, 3, 6, 3); fl.setSpacing(0)
            hdr = QLabel(name.upper()); hdr.setObjectName("tileHdr")
            val = QLabel("—"); val.setObjectName("tileVal")
            fl.addWidget(hdr); fl.addWidget(val)
            grid.addWidget(frame, i // 4, i % 4)
            self.tiles[name] = val
        layout.addWidget(grid_holder, 1)

        self.gauge = GaugeWidget("DRAWDOWN")
        self.gauge.setMaximumWidth(180)
        layout.addWidget(self.gauge)
        return wrap

    # -- body --------------------------------------------------------------
    def _body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._charts())
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self._strategy())
        right.addWidget(self._feed())
        right.setSizes([460, 200])
        splitter.addWidget(right)
        splitter.setSizes([600, 440])
        return splitter

    def _charts(self) -> QTabWidget:
        tabs = QTabWidget()
        self.equity_plot, self.equity_curve = self._plot("trade #", "cumulative P&L £", style.POS)
        tabs.addTab(self.equity_plot, "Equity")
        self.pertrade_plot, _ = self._plot("trade #", "P&L £", style.ACCENT)
        self.pertrade_bars = pg.BarGraphItem(x=[0], height=[0], width=0.6, brush=style.POS)
        self.pertrade_plot.addItem(self.pertrade_bars)
        tabs.addTab(self.pertrade_plot, "Per-Trade")
        self.edge_plot, self.edge_curve = self._plot("trade #", "net edge %", style.WARN)
        tabs.addTab(self.edge_plot, "Edge taken")
        return tabs

    def _plot(self, xlabel: str, ylabel: str, colour: str) -> Tuple[pg.PlotWidget, object]:
        plot = pg.PlotWidget()
        plot.setBackground(style.PANEL)
        plot.showGrid(x=True, y=True, alpha=0.15)
        for ax in ("left", "bottom"):
            plot.getAxis(ax).setPen(style.MUTED)
            plot.getAxis(ax).setTextPen(style.MUTED)
        plot.setLabel("bottom", xlabel)
        plot.setLabel("left", ylabel)
        curve = plot.plot([], [], pen=pg.mkPen(colour, width=2))
        return plot, curve

    def _strategy(self) -> QScrollArea:
        area = QScrollArea(); area.setWidgetResizable(True)
        inner = QWidget()
        outer = QVBoxLayout(inner); outer.setContentsMargins(2, 2, 2, 2)

        presets = QGroupBox("Saved presets")
        pl = QHBoxLayout(presets)
        self.preset_combo = QComboBox()
        apply_btn = QPushButton("Apply"); apply_btn.clicked.connect(self._apply_preset)
        save_btn = QPushButton("Save as…"); save_btn.clicked.connect(self._save_preset)
        del_btn = QPushButton("Delete"); del_btn.clicked.connect(self._delete_preset)
        pl.addWidget(self.preset_combo, 1)
        pl.addWidget(apply_btn); pl.addWidget(save_btn); pl.addWidget(del_btn)
        outer.addWidget(presets)

        strat = QGroupBox("Strategy")
        f1 = QFormLayout(strat)
        self.profile = QComboBox(); self.profile.addItem("ACTIVE (follow screener)")
        self.profile.currentTextChanged.connect(self._apply)
        self.sport = QComboBox(); self.sport.addItems(SPORTS)
        self.sport.currentTextChanged.connect(self._apply)
        self.min_edge = self._spin(0, 20, 0.25, "%")
        self.min_quality = self._spin(0, 100, 5, "")
        self.min_liq = self._spin(0, 100000, 100, "£", prefix=True)
        f1.addRow("Risk profile", self.profile)
        f1.addRow("Sport", self.sport)
        f1.addRow("Min net edge", self.min_edge)
        f1.addRow("Min quality", self.min_quality)
        f1.addRow("Min liquidity", self.min_liq)
        outer.addWidget(strat)

        money = QGroupBox("Deposit & stake")
        f2 = QFormLayout(money)
        self.deposit = self._spin(50, 10000000, 250, "£", prefix=True)
        self.mode = QComboBox(); self.mode.addItems(list(STAKE_MODES.keys()))
        self.mode.currentTextChanged.connect(self._apply)
        self.fixed_stake = self._spin(1, 100000, 25, "£", prefix=True)
        self.pct_liq = self._spin(0, 100, 1, "%")
        self.pct_deposit = self._spin(0, 100, 1, "%")
        self.min_stake = self._spin(1, 100000, 5, "£", prefix=True)
        self.max_stake = self._spin(1, 100000, 25, "£", prefix=True)
        f2.addRow("Deposit", self.deposit)
        f2.addRow("Stake mode", self.mode)
        f2.addRow("Fixed stake", self.fixed_stake)
        f2.addRow("% liquidity", self.pct_liq)
        f2.addRow("% deposit", self.pct_deposit)
        f2.addRow("Min stake", self.min_stake)
        f2.addRow("Max stake", self.max_stake)
        outer.addWidget(money)

        limits = QGroupBox("Limits & stops")
        f3 = QFormLayout(limits)
        self.slippage = self._spin(0, 10, 0.25, "%")
        self.cooldown = self._spin(0, 120, 1, "s")
        self.max_trades = QSpinBox(); self.max_trades.setRange(1, 100000); self.max_trades.setValue(50)
        self.max_trades.valueChanged.connect(self._apply)
        self.target = self._spin(0, 1000000, 25, "£", prefix=True)
        self.loss = self._spin(0, 1000000, 25, "£", prefix=True)
        self.budget = self._spin(0, 10000000, 500, "£", prefix=True)
        f3.addRow("Slippage (max % stake)", self.slippage)
        f3.addRow("Cooldown", self.cooldown)
        f3.addRow("Max trades", self.max_trades)
        f3.addRow("Profit target (0=off)", self.target)
        f3.addRow("Loss limit (0=off)", self.loss)
        f3.addRow("Staking budget (0=off)", self.budget)
        outer.addWidget(limits)
        outer.addStretch(1)
        area.setWidget(inner)
        return area

    def _feed(self) -> QGroupBox:
        box = QGroupBox("Activity feed")
        layout = QVBoxLayout(box)
        self.feed = QListWidget(); self.feed.setUniformItemSizes(True)
        layout.addWidget(self.feed)
        return box

    def _spin(self, lo, hi, step, suffix, prefix=False) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(lo, hi); box.setSingleStep(step)
        if prefix:
            box.setPrefix(suffix)
        elif suffix:
            box.setSuffix(suffix)
        box.valueChanged.connect(self._apply)
        return box

    # -- presets -----------------------------------------------------------
    def _reload_presets(self, select: str | None = None) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(list(self.get_presets().keys()))
        if select:
            idx = self.preset_combo.findText(select)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)

    def _apply_preset(self) -> None:
        name = self.preset_combo.currentText()
        data = self.get_presets().get(name)
        if not data:
            return
        for key, value in data.items():
            if key != "enabled" and hasattr(self.cfg, key):
                setattr(self.cfg, key, value)
        self._load_from_config()
        self.on_change()
        self._log(f"Applied preset: {name}")

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save strategy preset", "Preset name:")
        if ok and name:
            presets = self.get_presets()
            data = self.cfg.to_dict(); data["enabled"] = False
            presets[name] = data
            self.save_presets(presets)
            self._reload_presets(select=name)
            self._log(f"Saved preset: {name}")

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        presets = self.get_presets()
        if name in presets:
            del presets[name]
            self.save_presets(presets)
            self._reload_presets()

    # -- profiles / config sync -------------------------------------------
    def set_profiles(self, names) -> None:
        current = self.profile.currentText()
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItem("ACTIVE (follow screener)")
        self.profile.addItems(list(names))
        idx = self.profile.findText(current)
        self.profile.setCurrentIndex(idx if idx >= 0 else 0)
        self.profile.blockSignals(False)

    def _load_from_config(self) -> None:
        c = self.cfg
        self._loading = True
        self.enable_btn.setChecked(c.enabled)
        self.sport.setCurrentText(c.sport if c.sport in SPORTS else "ALL")
        self.min_edge.setValue(c.min_edge)
        self.min_quality.setValue(c.min_quality)
        self.min_liq.setValue(c.min_liquidity)
        self.deposit.setValue(c.deposit)
        self.mode.setCurrentText(STAKE_MODES_REV.get(c.stake_mode, "Fixed £"))
        self.fixed_stake.setValue(c.fixed_stake)
        self.pct_liq.setValue(c.pct_liquidity)
        self.pct_deposit.setValue(c.pct_deposit)
        self.min_stake.setValue(c.min_stake)
        self.max_stake.setValue(c.max_stake)
        self.slippage.setValue(c.slippage_pct)
        self.cooldown.setValue(c.cooldown_s)
        self.max_trades.setValue(c.max_trades)
        self.target.setValue(c.target_profit)
        self.loss.setValue(c.loss_limit)
        self.budget.setValue(c.max_total_staked)
        prof = "ACTIVE (follow screener)" if c.profile == "ACTIVE" else c.profile
        idx = self.profile.findText(prof)
        if idx >= 0:
            self.profile.setCurrentIndex(idx)
        self._loading = False
        self._sync_stake_fields()
        self._update_summary()

    def _paint_enable(self, on: bool) -> None:
        self.enable_btn.setText("BOT: ON" if on else "BOT: OFF")
        self.enable_btn.setStyleSheet(f"color: {style.POS};" if on else "")

    def _toggle_enabled(self, on: bool) -> None:
        self._paint_enable(on)
        self.bot.set_enabled(on)

    def _toggle_detach(self) -> None:
        self.detached = not self.detached
        self.detach_btn.setText("Re-dock" if self.detached else "Pop out ↗")
        self.detach_toggled.emit(self.detached)

    def _sync_stake_fields(self) -> None:
        self.fixed_stake.setEnabled(self.cfg.stake_mode == "fixed")
        self.pct_liq.setEnabled(self.cfg.stake_mode == "pct_liquidity")
        self.pct_deposit.setEnabled(self.cfg.stake_mode == "pct_deposit")

    def _apply(self, *_):
        if getattr(self, "_loading", False):
            return
        c = self.cfg
        text = self.profile.currentText()
        c.profile = "ACTIVE" if text.startswith("ACTIVE") else text
        c.sport = self.sport.currentText()
        c.min_edge = self.min_edge.value()
        c.min_quality = self.min_quality.value()
        c.min_liquidity = self.min_liq.value()
        c.deposit = self.deposit.value()
        c.stake_mode = STAKE_MODES.get(self.mode.currentText(), "fixed")
        c.fixed_stake = self.fixed_stake.value()
        c.pct_liquidity = self.pct_liq.value()
        c.pct_deposit = self.pct_deposit.value()
        c.min_stake = self.min_stake.value()
        c.max_stake = max(self.min_stake.value(), self.max_stake.value())
        c.slippage_pct = self.slippage.value()
        c.cooldown_s = self.cooldown.value()
        c.max_trades = self.max_trades.value()
        c.target_profit = self.target.value()
        c.loss_limit = self.loss.value()
        c.max_total_staked = self.budget.value()
        self._sync_stake_fields()
        self._update_summary()
        self.on_change()

    def _update_summary(self) -> None:
        c = self.cfg
        stake = {"fixed": f"£{c.fixed_stake:.0f}",
                 "pct_liquidity": f"{c.pct_liquidity:.0f}% liq",
                 "pct_deposit": f"{c.pct_deposit:.0f}% deposit"}.get(c.stake_mode, "—")
        stops = []
        if c.target_profit > 0:
            stops.append(f"target £{c.target_profit:.0f}")
        if c.loss_limit > 0:
            stops.append(f"stop -£{c.loss_limit:.0f}")
        stop_txt = ("  ·  " + ", ".join(stops)) if stops else ""
        self.strategy_summary.setText(
            f"STRATEGY  ·  {c.profile}  ·  {c.sport}  ·  edge≥{c.min_edge:.2f}%  ·  "
            f"deposit £{c.deposit:.0f}  ·  stake {stake} (£{c.min_stake:.0f}–£{c.max_stake:.0f})  ·  "
            f"cooldown {c.cooldown_s:.0f}s{stop_txt}")

    # -- live refresh ------------------------------------------------------
    def refresh(self) -> None:
        bot, cfg = self.bot, self.cfg
        self.status.setText("running" if cfg.enabled else "idle")
        self.status.setStyleSheet(f"color: {style.POS if cfg.enabled else style.MUTED};")
        if self.enable_btn.isChecked() != cfg.enabled:
            self.enable_btn.blockSignals(True)
            self.enable_btn.setChecked(cfg.enabled)
            self.enable_btn.blockSignals(False)
            self._paint_enable(cfg.enabled)

        values = {
            "Balance": fmt.money(bot.balance), "Deposit": fmt.money(cfg.deposit),
            "Bot P&L": fmt.signed_money(bot.profit), "ROI": fmt.pct(bot.roi),
            "Trades": str(bot.count), "Win %": fmt.pct(bot.win_rate, 0),
            "Avg / Trade": fmt.money(bot.avg_profit), "Best": fmt.money(bot.best_trade),
            "Worst": fmt.money(bot.worst_trade), "Max DD": fmt.money(bot.max_drawdown),
            "Staked": fmt.money(bot.staked), "Trades Left": str(max(0, cfg.max_trades - bot.count)),
        }
        for name, text in values.items():
            self.tiles[name].setText(text)
        self._colour(self.tiles["Bot P&L"], bot.profit)
        self._colour(self.tiles["Worst"], bot.worst_trade)
        self._colour(self.tiles["Max DD"], bot.max_drawdown)

        # Drawdown gauge — magnitude against the loss limit (or 20% of deposit).
        dd = abs(bot.max_drawdown)
        limit = cfg.loss_limit if cfg.loss_limit > 0 else max(1.0, cfg.deposit * 0.2)
        self.gauge.set_value(dd, limit, f"£{dd:.0f}")
        self._draw_charts()

    def _colour(self, label: QLabel, value: float) -> None:
        label.setStyleSheet(f"#tileVal {{ color: {style.POS if value >= 0 else style.NEG}; }}")

    def _draw_charts(self) -> None:
        eq = self.bot.equity
        self.equity_curve.setData(list(range(len(eq))), eq)
        profits = self.bot.trade_profits
        if profits:
            brushes = [style.POS if p >= 0 else style.NEG for p in profits]
            self.pertrade_bars.setOpts(x=list(range(len(profits))), height=profits,
                                       width=0.6, brushes=brushes)
        self.edge_curve.setData(list(range(len(self.bot.trade_edges))), self.bot.trade_edges)

    def _log(self, message: str) -> None:
        item = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
        self.feed.insertItem(0, item)
        colour = style.POS if "TRADE" in message else style.MUTED
        self.feed.item(0).setForeground(QColor(colour))
        if self.feed.count() > 200:
            self.feed.takeItem(self.feed.count() - 1)
