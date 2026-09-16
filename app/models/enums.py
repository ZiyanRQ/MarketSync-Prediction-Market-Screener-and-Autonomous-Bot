"""Shared enumerations used across models, services and UI."""

from __future__ import annotations

from enum import Enum


class Venue(str, Enum):
    BETFAIR = "Betfair"
    MATCHBOOK = "Matchbook"


class Sport(str, Enum):
    FOOTBALL = "Football"
    TENNIS = "Tennis"
    BASKETBALL = "Basketball"
    HORSE_RACING = "Horse Racing"


class Direction(str, Enum):
    """Which venue to back and which to lay for a selection's cross-exchange arb."""
    BACK_BF_LAY_MB = "Back BF / Lay MB"
    BACK_MB_LAY_BF = "Back MB / Lay BF"
    NONE = "—"


class OppStatus(str, Enum):
    LIVE = "LIVE"
    THIN = "THIN"
    EXPIRED = "EXPIRED"


class RiskLevel(str, Enum):
    """Coarse rating of an opportunity against the active risk buffer."""
    SAFE = "SAFE"
    THIN = "THIN"
    SKIP = "SKIP"


class UsageState(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
