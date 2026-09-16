"""Editable risk / buffer presets."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict


@dataclass
class RiskProfile:
    """A named risk tolerance: the safety buffer plus the filters an opportunity
    must clear to be shown. Buffer and min_net are the two headline numbers; the
    rest are optional gates that default to permissive."""
    name: str
    safety_buffer: float          # percentage points subtracted from net edge
    min_net_edge: float           # minimum net edge % to surface at all
    min_liquidity: float = 0.0    # £
    max_price_age: float = 60.0   # seconds
    min_quality: float = 0.0      # 0..100
    max_volatility: float = 100.0 # %
    max_exposure: float = 100000.0
    max_stake: float = 100000.0
    builtin: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "RiskProfile":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def default_profiles() -> Dict[str, RiskProfile]:
    """The three built-in profiles. MODERATE is the default active profile."""
    return {
        "SAFE": RiskProfile("SAFE", 2.0, 2.0, min_liquidity=500, builtin=True),
        "MODERATE": RiskProfile("MODERATE", 1.0, 0.5, builtin=True),
        "RISKY": RiskProfile("RISKY", 0.0, 0.01, builtin=True),
    }
