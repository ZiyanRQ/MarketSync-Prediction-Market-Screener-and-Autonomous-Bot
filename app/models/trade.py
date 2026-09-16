"""Paper-trade record for the simulated bankroll."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict


@dataclass
class SimulatedTrade:
    """One recorded paper trade. Never touches a real exchange."""
    trade_id: str
    ts: datetime
    event: str
    market: str
    selection: str
    direction: str
    capital: float
    betfair_odds: float
    matchbook_odds: float
    net_edge: float
    risk_preset: str
    buffer: float
    theoretical_profit: float
    roi: float
    status: str = "OPEN"

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["ts"] = self.ts.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "SimulatedTrade":
        data = dict(data)
        if isinstance(data.get("ts"), str):
            data["ts"] = datetime.fromisoformat(data["ts"])
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)
