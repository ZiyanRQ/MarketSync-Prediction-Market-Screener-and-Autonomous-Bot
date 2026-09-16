"""The derived arbitrage opportunity — one per screener row.

An Opportunity is computed from a Market by the arbitrage engine. It carries the
display fields the screener shows plus a rolling history used for the lifetime
panel and sparkline. Buffer-adjusted fields are recomputed locally whenever the
active risk profile changes — never by refetching data.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, List, Optional

from .enums import Direction, OppStatus, RiskLevel
from .market import Market


@dataclass
class QualityScore:
    profitability: float = 0.0   # /20
    liquidity: float = 0.0       # /20
    freshness: float = 0.0       # /20
    stability: float = 0.0       # /20
    market_match: float = 0.0    # /10
    execution_risk: float = 0.0  # /10

    @property
    def total(self) -> float:
        return (self.profitability + self.liquidity + self.freshness
                + self.stability + self.market_match + self.execution_risk)


@dataclass
class Opportunity:
    market: Market
    direction: Direction
    back_venue: str
    lay_venue: str
    back_odds: float
    lay_odds: float
    liquidity: float
    gross_edge: float            # %
    net_edge: float              # % after commission (worst-case)
    quality: QualityScore
    volatility: float            # %
    created: datetime
    status: OppStatus = OppStatus.LIVE
    favourite: bool = False

    # Buffer-dependent, recomputed locally on risk-profile change:
    safety_buffer: float = 0.0
    buffered_edge: float = 0.0
    min_required_edge: float = 0.0
    risk: RiskLevel = RiskLevel.SKIP

    # Lifetime tracking:
    peak_edge: float = field(default=0.0)
    low_edge: float = field(default=999.0)
    edge_history: Deque[float] = field(default_factory=lambda: deque(maxlen=120))
    price_changes: int = 0
    time_above_1pct: float = 0.0  # seconds

    @property
    def key(self) -> str:
        return f"{self.market.market_id}"

    @property
    def age_seconds(self) -> float:
        return (datetime.now() - self.created).total_seconds()

    @property
    def price_age(self) -> float:
        return (datetime.now() - self.market.price_ts).total_seconds()

    @property
    def estimated_profit(self) -> float:
        """Rough profit on a nominal £100 at the current net edge (display only)."""
        return max(0.0, self.net_edge) * 100 / 100.0

    def observe(self) -> None:
        """Fold the current net edge into the rolling history stats."""
        self.edge_history.append(self.net_edge)
        self.peak_edge = max(self.peak_edge, self.net_edge)
        self.low_edge = min(self.low_edge, self.net_edge)

    def average_edge(self) -> float:
        return sum(self.edge_history) / len(self.edge_history) if self.edge_history else 0.0

    def apply_buffer(self, buffer: float, min_required: float) -> None:
        """Recompute buffer-adjusted figures + risk tier for the active profile."""
        self.safety_buffer = buffer
        self.buffered_edge = self.net_edge - buffer
        self.min_required_edge = min_required
        if self.buffered_edge >= 0 and self.net_edge >= max(min_required, 0.0) + buffer:
            self.risk = RiskLevel.SAFE
        elif self.net_edge > 0:
            self.risk = RiskLevel.THIN
        else:
            self.risk = RiskLevel.SKIP
