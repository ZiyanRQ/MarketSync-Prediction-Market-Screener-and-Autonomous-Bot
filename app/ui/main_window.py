"""The trading workstation shell: docks, toolbar, status bar, shortcuts, wiring.

Owns the services and connects them to the panels via signals. UI interactions
(risk, filters, simulator, watchlist) are all local — none trigger a data fetch.
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDockWidget,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
                               QVBoxLayout, QWidget)

from ..models.opportunity import Opportunity
from ..providers.mock_provider import MockProvider
from ..services.api_usage_tracker import ApiUsageTracker
from ..services.arbitrage_engine import ArbitrageEngine
from ..services.auto_trader import AutoTrader, BotConfig
from ..services.cache_service import CacheService
from ..services.market_data_service import MarketDataService
from ..services.risk_engine import RiskEngine
from ..services.simulation_engine import SimulationEngine
from ..storage.local_store import LocalStore
from ..utils import formatting as fmt
from . import style
from .alerts import AlertsWidget
from .analytics import AnalyticsWidget
from .api_usage import ApiUsageWidget
from .bot_dashboard import BotDashboard, DetachWindow
from .command_palette import CommandPalette
from .event_log import EventLogWidget
from .opportunity_inspector import InspectorWidget
from .screener import ScreenerWidget
from .settings_dialog import SettingsDialog
from .simulator import SimulatorWidget
from .watchlist import WatchlistWidget


class MainWindow(QMainWindow):
    def __init__(self, store: LocalStore) -> None:
        super().__init__()
        self.store = store
        self.setWindowTitle("MarketSync Terminal — Betfair ↔ Matchbook (DEMO)")
        self.resize(1500, 900)

        self.settings = store.load_settings()
        commission = self._commission_dict()

        # --- services -----------------------------------------------------
        self.cache = CacheService()
        self.usage = ApiUsageTracker()
        self.engine = ArbitrageEngine(commission)
        self.risk = RiskEngine()
        self.risk.profiles = store.load_profiles()
        self.risk.set_enabled(store.load_enabled_profiles())
        self.provider = MockProvider()
        self.market_data = MarketDataService(
            self.provider, self.engine, self.usage, self.cache,
            interval_ms=int(self.settings.get("refresh_ms", 1500)))
        self.sim = SimulationEngine(commission)
        self.sim.bankroll.starting = store.load_bankroll()
        self.bot = AutoTrader(self.sim, self.risk, BotConfig.from_dict(store.load_bot_config()))

        self.watchlist: set[str] = set(store.load_watchlist())
        self._surfaced_keys: set[str] = set()
        self._alerted_keys: set[str] = set()

        # --- widgets ------------------------------------------------------
        self.screener = ScreenerWidget(self.risk)
        self.inspector = InspectorWidget(self.sim, self.risk)
        self.watchlist_widget = WatchlistWidget()
        self.event_log = EventLogWidget()
        self.simulator = SimulatorWidget(self.sim, self.market_data.snapshot)
        self.analytics = AnalyticsWidget(self.sim)
        self.api_usage = ApiUsageWidget(self.usage, self.cache)
        self.alerts = AlertsWidget(store.load_alerts())
        self.bot_panel = BotDashboard(self.bot, self._save_bot,
                                      store.load_bot_presets, store.save_bot_presets)
        self.bot_panel.set_profiles(list(self.risk.profiles.keys()))
        self._bot_window = None

        self.setCentralWidget(self.screener)
        self._build_docks()
        self._build_toolbar()
        self._build_statusbar()
        self._build_menus()
        self._build_shortcuts()
        self._connect()

        self.simulator.load_history(store.load_trades())
        store.restore_geometry(self)
        header_state = store.load_table_state()
        if header_state is not None:
            self.screener.table.horizontalHeader().restoreState(header_state)

        self._on_risk_changed(self.risk.active_name)
        self.market_data.start()

    # --- construction -----------------------------------------------------
    def _commission_dict(self) -> Dict[str, float]:
        return {
            "Betfair": self.settings.get("commission_betfair", 2.0) / 100.0,
            "Matchbook": self.settings.get("commission_matchbook", 2.0) / 100.0,
        }

    def _dock(self, title: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                         | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self) -> None:
        # Any panel can be dragged to any edge, floated, nested or tabbed together.
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks
                            | QMainWindow.DockOption.AllowTabbedDocks
                            | QMainWindow.DockOption.AnimatedDocks)
        self.watch_dock = self._dock("WATCHLIST", self.watchlist_widget,
                                     Qt.DockWidgetArea.LeftDockWidgetArea)
        self.inspector_dock = self._dock("OPPORTUNITY INSPECTOR", self.inspector,
                                         Qt.DockWidgetArea.RightDockWidgetArea)
        self.bot_dock = self._dock("AUTO-TRADER", self.bot_panel, Qt.DockWidgetArea.RightDockWidgetArea)
        self.log_dock = self._dock("EVENT LOG", self.event_log, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.sim_dock = self._dock("SIMULATIONS", self.simulator, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.analytics_dock = self._dock("ANALYTICS", self.analytics, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.api_dock = self._dock("API USAGE", self.api_usage, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.alerts_dock = self._dock("ALERTS", self.alerts, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.panels = {
            "Watchlist": self.watch_dock, "Inspector": self.inspector_dock,
            "Auto-Trader": self.bot_dock, "Events": self.log_dock,
            "Simulations": self.sim_dock, "Analytics": self.analytics_dock,
            "API Usage": self.api_dock, "Alerts": self.alerts_dock,
        }
        self.tabifyDockWidget(self.inspector_dock, self.bot_dock)
        for dock in (self.sim_dock, self.analytics_dock, self.api_dock, self.alerts_dock):
            self.tabifyDockWidget(self.log_dock, dock)
        self.bot_dock.raise_()   # bot terminal visible by default — it's a headline feature
        self.log_dock.raise_()
        self.resizeDocks([self.inspector_dock], [470], Qt.Orientation.Horizontal)

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Main")
        bar.setObjectName("MainToolbar")
        bar.setMovable(False)

        self.bot_button = QPushButton("BOT TERMINAL")
        self.bot_button.setStyleSheet(
            f"font-weight: bold; color: {style.ACCENT}; padding: 3px 14px;")
        self.bot_button.setToolTip("Open the Auto-Trader terminal (Ctrl+B)")
        self.bot_button.clicked.connect(self._open_bot_terminal)
        bar.addWidget(self.bot_button)
        bar.addSeparator()

        bar.addWidget(QLabel(" RISK "))
        self.risk_bar = QWidget()
        self.risk_bar_layout = QHBoxLayout(self.risk_bar)
        self.risk_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.risk_bar_layout.setSpacing(2)
        self.risk_buttons: Dict[str, QPushButton] = {}
        bar.addWidget(self.risk_bar)
        self._rebuild_risk_buttons()
        self.buf_label = QLabel("BUF —")
        self.minnet_label = QLabel("MIN NET —")
        bar.addWidget(self.buf_label)
        bar.addWidget(self.minnet_label)
        bar.addSeparator()

        bar.addWidget(QLabel(" SEARCH "))
        search = QLineEdit()
        search.setMaximumWidth(200)
        search.setPlaceholderText("event / selection…")
        search.textChanged.connect(lambda v: self.screener.proxy.set_criteria(search=v))
        bar.addWidget(search)
        bar.addSeparator()

        bar.addWidget(QLabel(" PANELS "))
        for name in list(self.panels.keys()) + ["Settings"]:
            if name == "Auto-Trader":
                continue  # has its own prominent button
            btn = QPushButton(name)
            btn.setMaximumWidth(96)
            btn.clicked.connect(lambda _, n=name: self._show_panel(n))
            bar.addWidget(btn)
        bar.addSeparator()

        for text in ("BETFAIR: DEMO", "MATCHBOOK: DEMO", "DATA: SIMULATED"):
            lbl = QLabel(f" {text} ")
            lbl.setStyleSheet(f"color: {style.WARN}; font-weight: bold;")
            bar.addWidget(lbl)

    def _rebuild_risk_buttons(self) -> None:
        while self.risk_bar_layout.count():
            item = self.risk_bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.risk_buttons = {}
        for name in self.risk.profiles:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(name in self.risk.enabled)
            btn.setMaximumWidth(96)
            btn.toggled.connect(lambda on, n=name: self.risk.toggle(n, on))
            self.risk_bar_layout.addWidget(btn)
            self.risk_buttons[name] = btn

    def _sync_risk_buttons(self, enabled: set) -> None:
        for name, btn in self.risk_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(name in enabled)
            btn.blockSignals(False)

    def _show_panel(self, name: str) -> None:
        if name == "Settings":
            self._open_settings()
            return
        dock = self.panels.get(name)
        if dock:
            dock.show()
            dock.raise_()

    def _build_statusbar(self) -> None:
        self.status_labels: Dict[str, QLabel] = {}
        bar = self.statusBar()
        for key in ("venues", "risk", "arbs", "over1", "api", "pnl"):
            lbl = QLabel("—")
            self.status_labels[key] = lbl
            bar.addPermanentWidget(lbl)
        self.status_labels["venues"].setText("BF DEMO | MB DEMO")

    def _build_menus(self) -> None:
        view = self.menuBar().addMenu("&View")
        for dock in self.panels.values():
            view.addAction(dock.toggleViewAction())
        workspace = self.menuBar().addMenu("&Workspace")
        workspace.addAction("Save layout", lambda: self.store.save_geometry(self))
        workspace.addAction("Reset layout", self._reset_layout)
        workspace.addAction("Settings…", self._open_settings)

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._open_palette)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._open_bot_terminal)

    def _open_bot_terminal(self) -> None:
        """Bring the Auto-Trader to the front — its window if detached, else its dock."""
        if self._bot_window is not None:
            self._bot_window.show()
            self._bot_window.raise_()
            self._bot_window.activateWindow()
        else:
            self.bot_dock.show()
            self.bot_dock.raise_()

    def _connect(self) -> None:
        self.market_data.updated.connect(self._on_data)
        self.risk.profile_changed.connect(self._on_risk_changed)
        self.risk.profiles_changed.connect(self._on_profiles_changed)
        self.risk.enabled_changed.connect(self._sync_risk_buttons)
        self.screener.selection_changed.connect(self.inspector.set_opportunity)
        self.screener.open_requested.connect(self._open_in_inspector)
        self.screener.context_action.connect(self._context_action)
        self.inspector.simulate_requested.connect(self._paper_trade)
        self.watchlist_widget.open_requested.connect(self._open_in_inspector)
        self.alerts.rules_changed.connect(self.store.save_alerts)
        self.bot.logline.connect(lambda msg: self.event_log.log(msg, style.ACCENT))
        self.bot_panel.detach_toggled.connect(self._toggle_bot_detach)

    # --- data flow --------------------------------------------------------
    def _on_data(self, opps: List[Opportunity]) -> None:
        self.risk.apply(opps)
        self.bot.evaluate(opps)
        self.screener.set_opportunities(opps)
        self.screener.refilter()
        self.inspector.live_refresh()
        self.watchlist_widget.refresh(opps, self.watchlist)
        self.analytics.refresh(opps)
        self.api_usage.refresh()
        self.simulator.refresh_stats()
        self._log_changes(opps)
        self._check_alerts(opps)
        self._update_status(opps)

    def _surfaced(self, opps: List[Opportunity]) -> List[Opportunity]:
        return [o for o in opps if self.risk.passes(o)]

    def _log_changes(self, opps: List[Opportunity]) -> None:
        surfaced = self._surfaced(opps)
        keys = {o.key: o for o in surfaced}
        for key, opp in keys.items():
            if key not in self._surfaced_keys:
                self.event_log.log(
                    f"ARB DETECTED  {opp.market.event} — {opp.market.selection}  "
                    f"+{opp.net_edge:.2f}%", style.POS)
        for key in self._surfaced_keys - set(keys):
            self.event_log.log(f"ARB EXPIRED  {key}", style.MUTED)
        self._surfaced_keys = set(keys)

    def _check_alerts(self, opps: List[Opportunity]) -> None:
        current = set()
        for opp in self._surfaced(opps):
            if self.alerts.evaluate(opp):
                current.add(opp.key)
                if opp.key not in self._alerted_keys:
                    self.event_log.log(
                        f"ALERT  {opp.market.event} net {opp.net_edge:.2f}% "
                        f"liq {fmt.money_short(opp.liquidity)} qual {opp.quality.total:.0f}",
                        style.WARN)
                    if any(r.get("sound") for r in self.alerts.rules):
                        QApplication.beep()
        self._alerted_keys = current

    def _update_status(self, opps: List[Opportunity]) -> None:
        surfaced = self._surfaced(opps)
        over1 = sum(1 for o in surfaced if o.net_edge > 1.0)
        prof = self.risk.active
        extra = f" +{len(self.risk.enabled) - 1}" if len(self.risk.enabled) > 1 else ""
        self.status_labels["risk"].setText(f"RISK {prof.name}{extra} {prof.safety_buffer:.1f}%")
        self.status_labels["arbs"].setText(f"{len(surfaced)} ARBS")
        self.status_labels["over1"].setText(f"{over1} >1%")
        self.status_labels["api"].setText(f"API {self.usage.state().value}")
        self.status_labels["pnl"].setText(f"SIM P&L {fmt.signed_money(self.sim.bankroll.realised)}")

    # --- risk -------------------------------------------------------------
    def _on_risk_changed(self, name: str) -> None:
        prof = self.risk.active
        self.buf_label.setText(f"BUF {prof.safety_buffer:.2f}%")
        self.minnet_label.setText(f"MIN NET {prof.min_net_edge:.2f}%")
        self.store.save_enabled_profiles(list(self.risk.enabled))
        opps = self.market_data.snapshot()
        self.risk.apply(opps)
        self.screener.refilter()
        self.analytics.refresh(opps)
        self._update_status(opps)
        self.event_log.log(f"RISK ACTIVE → {', '.join(sorted(self.risk.enabled))}", style.ACCENT)

    def _on_profiles_changed(self) -> None:
        self.store.save_profiles(self.risk.profiles)
        self._rebuild_risk_buttons()
        self.bot_panel.set_profiles(list(self.risk.profiles.keys()))

    def _reset_layout(self) -> None:
        for area, dock in [(Qt.DockWidgetArea.LeftDockWidgetArea, self.watch_dock),
                           (Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock),
                           (Qt.DockWidgetArea.RightDockWidgetArea, self.bot_dock),
                           (Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock),
                           (Qt.DockWidgetArea.BottomDockWidgetArea, self.sim_dock),
                           (Qt.DockWidgetArea.BottomDockWidgetArea, self.analytics_dock),
                           (Qt.DockWidgetArea.BottomDockWidgetArea, self.api_dock),
                           (Qt.DockWidgetArea.BottomDockWidgetArea, self.alerts_dock)]:
            dock.setFloating(False)
            dock.show()
            self.addDockWidget(area, dock)
        self.tabifyDockWidget(self.inspector_dock, self.bot_dock)
        for dock in (self.sim_dock, self.analytics_dock, self.api_dock, self.alerts_dock):
            self.tabifyDockWidget(self.log_dock, dock)
        self.inspector_dock.raise_()
        self.log_dock.raise_()

    # --- actions ----------------------------------------------------------
    def _open_in_inspector(self, opp: Opportunity) -> None:
        self.inspector.set_opportunity(opp)
        self.inspector_dock.raise_()

    def _context_action(self, action: str, opp: Opportunity) -> None:
        if action == "favourite":
            opp.favourite = not opp.favourite
            self.screener.refilter()
        elif action == "watch":
            self.watchlist.add(opp.key)
            self.store.save_watchlist(list(self.watchlist))
            self.screener.set_watchlist(self.watchlist)
            self.watchlist_widget.refresh(self.market_data.snapshot(), self.watchlist)
        elif action == "simulate":
            self._paper_trade(opp, self.inspector.capital.value())

    def _paper_trade(self, opp: Opportunity, capital: float) -> None:
        trade = self.sim.record_trade(opp, capital, self.risk.active_name)
        self.store.add_trade(trade)
        self.simulator.add_trade(trade)
        self.event_log.log(
            f"SIM TRADE  {opp.market.event} £{capital:.0f} → "
            f"{fmt.signed_money(trade.theoretical_profit)} ({trade.roi:.2f}%)", style.ACCENT)
        self._update_status(self.market_data.snapshot())

    def _save_bot(self) -> None:
        self.store.save_bot_config(self.bot.config.to_dict())

    def _toggle_bot_detach(self, detached: bool) -> None:
        if detached and self._bot_window is None:
            window = DetachWindow()
            window.setWindowTitle("MarketSync — Auto-Trader Terminal (PAPER)")
            window.setCentralWidget(self.bot_panel)   # reparents the dashboard out of the dock
            window.resize(1040, 760)
            window.closed.connect(self._redock_bot)
            self._bot_window = window
            self.bot_dock.setWidget(self._bot_placeholder())
            window.show()
            window.raise_()
        elif not detached:
            self._redock_bot()

    def _redock_bot(self) -> None:
        window, self._bot_window = self._bot_window, None
        self.bot_dock.setWidget(self.bot_panel)     # reparents it back into the dock
        self.bot_panel.detached = False
        self.bot_panel.detach_btn.setText("Pop out ↗")
        self.bot_dock.show()
        self.bot_dock.raise_()
        if window is not None:
            window.closed.disconnect(self._redock_bot)
            if window.isVisible():
                window.close()

    def _bot_placeholder(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.addStretch(1)
        label = QLabel("Auto-Trader is running in its own window.")
        label.setProperty("role", "hint")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        button = QPushButton("Re-dock Auto-Trader")
        button.clicked.connect(self._redock_bot)
        layout.addWidget(label)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        return holder

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.risk, self.settings, self)
        dialog.exec()
        self.settings.update(dialog.result_settings())
        self.store.save_settings(self.settings)
        commission = self._commission_dict()
        self.engine.commission = commission
        self.sim.commission = commission
        self.market_data.set_interval(int(self.settings.get("refresh_ms", 1500)))

    def _open_palette(self) -> None:
        commands = [
            ("Show football arbs", lambda: self.screener.proxy.set_criteria(sport="Football")),
            ("Show >2% arbs", lambda: self.screener.proxy.set_criteria(min_net=2.0)),
            ("Reset filters", lambda: self.screener._quick_all()),
            ("Open watchlist", lambda: self._show_panel("Watchlist")),
            ("Open simulations", lambda: self._show_panel("Simulations")),
            ("Open analytics", lambda: self._show_panel("Analytics")),
            ("Open API Usage", lambda: self._show_panel("API Usage")),
            ("Open Auto-Trader", lambda: self._show_panel("Auto-Trader")),
            ("Enable auto-trader", lambda: self.bot.set_enabled(True)),
            ("Disable auto-trader", lambda: self.bot.set_enabled(False)),
            ("Pop out Auto-Trader terminal", lambda: self._toggle_bot_detach(True)),
            ("Simulate £500", lambda: self.inspector.capital.setValue(500)),
            ("Set minimum liquidity £1,000", lambda: self.screener.proxy.set_criteria(min_liq=1000)),
            ("Only SAFE", lambda: self.risk.set_active("SAFE")),
            ("Only MODERATE", lambda: self.risk.set_active("MODERATE")),
            ("Only RISKY", lambda: self.risk.set_active("RISKY")),
            ("Enable all risk profiles", lambda: self.risk.set_enabled(set(self.risk.profiles))),
        ]
        CommandPalette(commands, self).exec()

    # --- keyboard (suppressed while typing) -------------------------------
    def _is_editing(self) -> bool:
        widget = QApplication.focusWidget()
        return isinstance(widget, (QLineEdit, QAbstractSpinBox, QComboBox))

    def keyPressEvent(self, event) -> None:
        if self._is_editing():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Down:
            self.screener.select_row(1)
        elif key == Qt.Key.Key_Up:
            self.screener.select_row(-1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            opp = self.screener.current_opportunity()
            if opp:
                self._open_in_inspector(opp)
        elif key == Qt.Key.Key_S:
            opp = self.screener.current_opportunity()
            if opp:
                self._paper_trade(opp, self.inspector.capital.value())
        elif key == Qt.Key.Key_W:
            opp = self.screener.current_opportunity()
            if opp:
                self._context_action("watch", opp)
        elif key == Qt.Key.Key_Escape:
            pass
        else:
            super().keyPressEvent(event)

    # --- persistence ------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self._bot_window is not None:
            self._bot_window.closed.disconnect(self._redock_bot)
            self._bot_window.close()
        self.store.save_geometry(self)
        self.store.save_table_state(self.screener.table.horizontalHeader().saveState())
        self.store.save_profiles(self.risk.profiles)
        self.store.save_enabled_profiles(list(self.risk.enabled))
        self.store.save_watchlist(list(self.watchlist))
        self.store.save_alerts(self.alerts.rules)
        self.store.save_settings(self.settings)
        self.store.save_bankroll(self.sim.bankroll.starting)
        self.store.save_bot_config(self.bot.config.to_dict())
        super().closeEvent(event)
