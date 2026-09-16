"""Placeholder for the future live Matchbook provider (see betfair_provider)."""

from __future__ import annotations

from typing import List

from ..models.market import Market
from .base_provider import BaseProvider


class MatchbookProvider(BaseProvider):
    mode = "LIVE"

    def name(self) -> str:
        return "Matchbook"

    def fetch(self) -> List[Market]:
        raise NotImplementedError("Live Matchbook integration is not enabled in this build.")
