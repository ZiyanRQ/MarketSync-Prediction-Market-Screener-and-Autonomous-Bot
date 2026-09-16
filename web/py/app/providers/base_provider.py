"""Provider interface. Services depend on this, never on a concrete exchange.

The UI calls services; services call a Provider. Swapping the mock for real
Betfair/Matchbook providers later means implementing this interface only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models.market import Market


class BaseProvider(ABC):
    """Read-only market-data source."""

    #: Shown in the status bar, e.g. "DEMO" or "LIVE".
    mode: str = "DEMO"

    @abstractmethod
    def name(self) -> str:
        """Human name, e.g. 'Simulated'."""

    @abstractmethod
    def fetch(self) -> List[Market]:
        """Return the current snapshot of all markets (both venues priced)."""

    def tick(self) -> None:
        """Advance internal state one step (mock providers mutate prices here)."""
