"""Mock API-usage metrics + a developer call inspector.

No real requests are made. The market-data service feeds synthetic call records
here each tick so the API Usage panel and call inspector show realistic activity
and the design is ready for a live integration to report against.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Deque, Dict, List

from ..models.enums import UsageState


@dataclass
class ApiCall:
    ts: datetime
    provider: str
    operation: str
    target: str
    cache_hit: bool
    cost: int
    duration_ms: int
    reason: str


@dataclass
class ApiBudget:
    max_per_minute: int = 120
    max_per_hour: int = 5000
    max_active_markets: int = 200
    metadata_refresh: int = 300       # seconds
    cache_expiry: int = 5             # seconds
    auto_unsubscribe: int = 90        # seconds


class ApiUsageTracker:
    def __init__(self) -> None:
        self.calls: Deque[ApiCall] = deque(maxlen=500)
        self.budget = ApiBudget()
        self._today = 0

    def record(self, call: ApiCall) -> None:
        self.calls.append(call)
        if not call.cache_hit:
            self._today += 1

    def _since(self, seconds: float) -> List[ApiCall]:
        cutoff = datetime.now() - timedelta(seconds=seconds)
        return [c for c in self.calls if c.ts >= cutoff and not c.cache_hit]

    def per_minute(self) -> int:
        return len(self._since(60))

    def per_hour_estimate(self) -> int:
        return self.per_minute() * 60

    def today(self) -> int:
        return self._today

    def state(self) -> UsageState:
        ratio = self.per_minute() / max(1, self.budget.max_per_minute)
        if ratio >= 0.9:
            return UsageState.CRITICAL
        if ratio >= 0.6:
            return UsageState.HIGH
        if ratio >= 0.3:
            return UsageState.MODERATE
        return UsageState.LOW

    def provider_metrics(self, provider: str, cache: "object") -> Dict[str, str]:
        recent = [c for c in self.calls if c.provider == provider]
        live = [c for c in self._since(60) if c.provider == provider]
        avg_ms = int(sum(c.duration_ms for c in recent) / len(recent)) if recent else 0
        return {
            "Requests / min": str(len(live)),
            "Requests today": str(sum(1 for c in recent if not c.cache_hit)),
            "Avg response": f"{avg_ms}ms",
        }
