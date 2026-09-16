"""Placeholder for the future live Betfair provider.

Intentionally not implemented — the current build is DEMO only and must not make
real exchange requests. When wired up, this implements BaseProvider using the
Betfair JSON-RPC Betting API (see src/betfair.py for the request shapes).
"""

from __future__ import annotations

from typing import List

from ..models.market import Market
from .base_provider import BaseProvider


class BetfairProvider(BaseProvider):
    mode = "LIVE"

    def name(self) -> str:
        return "Betfair"

    def fetch(self) -> List[Market]:
        raise NotImplementedError("Live Betfair integration is not enabled in this build.")
