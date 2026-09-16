"""Order-book price structures for one selection on one venue."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class PriceLevel:
    """A single rung of the ladder: decimal odds and available size (£ stake)."""
    odds: float
    size: float


@dataclass
class ExchangePrice:
    """One venue's back and lay ladders for a selection, best price first."""
    back: List[PriceLevel] = field(default_factory=list)
    lay: List[PriceLevel] = field(default_factory=list)

    @property
    def best_back(self) -> float | None:
        return self.back[0].odds if self.back else None

    @property
    def best_lay(self) -> float | None:
        return self.lay[0].odds if self.lay else None

    @property
    def back_liquidity(self) -> float:
        return sum(level.size for level in self.back)

    @property
    def lay_liquidity(self) -> float:
        return sum(level.size for level in self.lay)
