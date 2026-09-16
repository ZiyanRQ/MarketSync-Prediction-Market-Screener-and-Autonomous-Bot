"""Owns the provider and the refresh clock. The ONLY component that fetches.

On each timer tick it advances the provider, pulls a fresh snapshot, records
synthetic API activity, rebuilds opportunities and emits them. UI widgets connect
to `updated` — they never call a provider, and local UI changes (filters, risk,
simulator) do not trigger a fetch.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import List

from PySide6.QtCore import QObject, QTimer, Signal

from ..models.opportunity import Opportunity
from ..providers.base_provider import BaseProvider
from .api_usage_tracker import ApiCall, ApiUsageTracker
from .arbitrage_engine import ArbitrageEngine
from .cache_service import CacheService


class MarketDataService(QObject):
    updated = Signal(list)          # List[Opportunity]
    logged = Signal(str)            # human event-log line

    def __init__(self, provider: BaseProvider, engine: ArbitrageEngine,
                 usage: ApiUsageTracker, cache: CacheService,
                 interval_ms: int = 1500) -> None:
        super().__init__()
        self.provider = provider
        self.engine = engine
        self.usage = usage
        self.cache = cache
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)
        self._last: List[Opportunity] = []

    def start(self) -> None:
        self._tick()
        self._timer.start()

    def set_interval(self, ms: int) -> None:
        self._timer.setInterval(ms)

    def snapshot(self) -> List[Opportunity]:
        return self._last

    def _tick(self) -> None:
        self.provider.tick()
        markets = self.provider.fetch()
        self._log_activity(markets)
        self._last = self.engine.rebuild(markets)
        self.updated.emit(self._last)

    def _log_activity(self, markets) -> None:
        """Emit a couple of synthetic API-call records so the usage panel is live."""
        now = datetime.now()
        for market in random.sample(markets, k=min(3, len(markets))):
            key = f"price:{market.market_id}"
            hit = self.cache.get(key) is not None
            self.cache.set(key, market.price_ts)
            for provider in ("Betfair", "Matchbook"):
                self.usage.record(ApiCall(
                    ts=now, provider=provider, operation="MARKET PRICE",
                    target=market.event, cache_hit=hit, cost=0 if hit else 1,
                    duration_ms=random.randint(2, 90) if not hit else 2,
                    reason="Already Cached" if hit else "Visible Screener Market",
                ))
