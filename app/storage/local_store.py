"""Local persistence. No cloud.

QSettings holds simple UI prefs, window/table layout and JSON blobs (risk presets,
watchlist, alert rules, saved filters). SQLite holds the structured trade history.
Everything degrades gracefully if a value is missing or corrupt.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Dict, List

from PySide6.QtCore import QByteArray, QSettings, QStandardPaths

from ..models.risk_profile import RiskProfile, default_profiles
from ..models.trade import SimulatedTrade


class LocalStore:
    def __init__(self) -> None:
        self.settings = QSettings("MarketSync", "Terminal")
        data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        os.makedirs(data_dir or ".", exist_ok=True)
        self.db_path = os.path.join(data_dir or ".", "marketsync.db")
        self._init_db()

    # -- generic JSON-in-QSettings ----------------------------------------
    def _get_json(self, key: str, default):
        raw = self.settings.value(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default

    def _set_json(self, key: str, value) -> None:
        self.settings.setValue(key, json.dumps(value))

    # -- risk presets ------------------------------------------------------
    def load_profiles(self) -> Dict[str, RiskProfile]:
        raw = self._get_json("risk/profiles", None)
        if not raw:
            return default_profiles()
        try:
            return {name: RiskProfile.from_dict(data) for name, data in raw.items()}
        except (TypeError, KeyError):
            return default_profiles()

    def save_profiles(self, profiles: Dict[str, RiskProfile]) -> None:
        self._set_json("risk/profiles", {n: p.to_dict() for n, p in profiles.items()})

    def load_active_profile(self) -> str:
        return self.settings.value("risk/active", "MODERATE")

    def save_active_profile(self, name: str) -> None:
        self.settings.setValue("risk/active", name)

    def load_enabled_profiles(self) -> list:
        return self._get_json("risk/enabled", ["MODERATE"])

    def save_enabled_profiles(self, names) -> None:
        self._set_json("risk/enabled", list(names))

    # -- watchlist & alerts ------------------------------------------------
    def load_watchlist(self) -> List[str]:
        return self._get_json("watchlist", [])

    def save_watchlist(self, ids: List[str]) -> None:
        self._set_json("watchlist", list(ids))

    def load_alerts(self) -> List[dict]:
        return self._get_json("alerts", [])

    def save_alerts(self, rules: List[dict]) -> None:
        self._set_json("alerts", rules)

    def load_settings(self) -> dict:
        return self._get_json("app/settings", {})

    def save_settings(self, data: dict) -> None:
        self._set_json("app/settings", data)

    def load_bot_config(self) -> dict:
        return self._get_json("bot/config", {})

    def save_bot_config(self, data: dict) -> None:
        self._set_json("bot/config", data)

    def load_bot_presets(self) -> dict:
        from ..services.auto_trader import default_bot_presets
        return self._get_json("bot/presets", None) or default_bot_presets()

    def save_bot_presets(self, presets: dict) -> None:
        self._set_json("bot/presets", presets)

    # -- window / table layout --------------------------------------------
    def save_geometry(self, window) -> None:
        self.settings.setValue("ui/geometry", window.saveGeometry())
        self.settings.setValue("ui/state", window.saveState())

    def restore_geometry(self, window) -> None:
        geo = self.settings.value("ui/geometry")
        state = self.settings.value("ui/state")
        if isinstance(geo, QByteArray):
            window.restoreGeometry(geo)
        if isinstance(state, QByteArray):
            window.restoreState(state)

    def save_table_state(self, header_state: QByteArray) -> None:
        self.settings.setValue("ui/table", header_state)

    def load_table_state(self):
        return self.settings.value("ui/table")

    def load_bankroll(self) -> float:
        try:
            return float(self.settings.value("sim/bankroll", 5000.0))
        except (TypeError, ValueError):
            return 5000.0

    def save_bankroll(self, starting: float) -> None:
        self.settings.setValue("sim/bankroll", starting)

    # -- trades (SQLite) ---------------------------------------------------
    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY, ts TEXT, event TEXT, market TEXT,
                    selection TEXT, direction TEXT, capital REAL, betfair_odds REAL,
                    matchbook_odds REAL, net_edge REAL, risk_preset TEXT, buffer REAL,
                    theoretical_profit REAL, roi REAL, status TEXT)
            """)

    def add_trade(self, trade: SimulatedTrade) -> None:
        d = trade.to_dict()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trades VALUES
                   (:trade_id,:ts,:event,:market,:selection,:direction,:capital,
                    :betfair_odds,:matchbook_odds,:net_edge,:risk_preset,:buffer,
                    :theoretical_profit,:roi,:status)""", d)

    def load_trades(self) -> List[SimulatedTrade]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades ORDER BY ts").fetchall()
        return [SimulatedTrade.from_dict(dict(r)) for r in rows]

    def clear_trades(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM trades")
