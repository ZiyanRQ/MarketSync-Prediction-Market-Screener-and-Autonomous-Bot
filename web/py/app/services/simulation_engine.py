"""Paper-trading bankroll, investment simulation and what-if strategy runs.

All local. `simulate` is the depth-aware investment model behind the Opportunity
Inspector; `record_trade` books a paper trade against the bankroll; `whatif` and
`compare_presets` drive the analytics panels. No real orders ever leave here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

from ..models.enums import Venue
from ..models.opportunity import Opportunity
from ..models.risk_profile import RiskProfile, default_profiles
from ..models.trade import SimulatedTrade
from ..utils import calculations as calc


@dataclass
class Bankroll:
    starting: float = 5000.0
    realised: float = 0.0
    locked: float = 0.0
    trades: int = 0

    @property
    def current(self) -> float:
        return self.starting + self.realised

    @property
    def available(self) -> float:
        return self.current - self.locked

    @property
    def roi(self) -> float:
        return (self.realised / self.starting * 100) if self.starting else 0.0


class SimulationEngine:
    def __init__(self, commission: Dict[str, float] | None = None) -> None:
        self.commission = commission or dict(calc.DEFAULT_COMMISSION)
        self.bankroll = Bankroll()
        self.history: List[SimulatedTrade] = []

    # -- ladders -----------------------------------------------------------
    def _ladders(self, opp: Opportunity):
        back_ex = opp.market.price_for(Venue(opp.back_venue))
        lay_ex = opp.market.price_for(Venue(opp.lay_venue))
        return back_ex.back, lay_ex.lay

    def simulate(self, opp: Opportunity, capital: float) -> calc.SimResult:
        back_levels, lay_levels = self._ladders(opp)
        return calc.simulate(back_levels, lay_levels, capital,
                             self.commission[opp.back_venue], self.commission[opp.lay_venue])

    def profit_curve(self, opp: Opportunity) -> List[calc.SimResult]:
        back_levels, lay_levels = self._ladders(opp)
        return calc.profit_curve(back_levels, lay_levels,
                                 self.commission[opp.back_venue], self.commission[opp.lay_venue])

    def max_executable(self, opp: Opportunity) -> float:
        back_levels, lay_levels = self._ladders(opp)
        return calc.max_executable(back_levels, lay_levels,
                                   self.commission[opp.back_venue], self.commission[opp.lay_venue])

    # -- paper trading -----------------------------------------------------
    def record_trade(self, opp: Opportunity, capital: float, preset: str) -> SimulatedTrade:
        sim = self.simulate(opp, capital)
        trade = SimulatedTrade(
            trade_id=uuid.uuid4().hex[:8], ts=datetime.now(),
            event=opp.market.event, market=opp.market.market_name,
            selection=opp.market.selection, direction=opp.direction.value,
            capital=capital, betfair_odds=opp.market.betfair.best_back or 0.0,
            matchbook_odds=opp.market.matchbook.best_back or 0.0,
            net_edge=opp.net_edge, risk_preset=preset, buffer=opp.safety_buffer,
            theoretical_profit=sim.net_profit, roi=sim.net_roi, status="SETTLED",
        )
        self.history.append(trade)
        self.bankroll.realised += sim.net_profit
        self.bankroll.trades += 1
        return trade

    def reset_bankroll(self, starting: float) -> None:
        self.bankroll = Bankroll(starting=starting)
        self.history.clear()

    # -- analytics ---------------------------------------------------------
    def compare_presets(self, opps: List[Opportunity], stake: float = 100.0) -> Dict[str, dict]:
        """Signals / avg edge / simulated profit under each built-in preset."""
        out: Dict[str, dict] = {}
        for name, prof in default_profiles().items():
            picked = [o for o in opps
                      if o.net_edge >= prof.min_net_edge
                      and (o.net_edge - prof.safety_buffer) >= 0
                      and o.liquidity >= prof.min_liquidity]
            profit = sum(self.simulate(o, stake).net_profit for o in picked)
            avg = sum(o.net_edge for o in picked) / len(picked) if picked else 0.0
            out[name] = {"signals": len(picked), "avg_edge": avg, "profit": profit}
        return out

    def whatif(self, opps: List[Opportunity], stake: float, min_edge: float,
               profile: RiskProfile, starting: float) -> dict:
        """Deploy `stake` into every opportunity clearing the filters; equity curve."""
        bankroll = starting
        curve = [starting]
        deployed = 0.0
        edges: List[float] = []
        for opp in opps:
            if opp.net_edge < max(min_edge, profile.min_net_edge):
                continue
            if opp.liquidity < profile.min_liquidity:
                continue
            if (opp.net_edge - profile.safety_buffer) < 0:
                continue
            sim = self.simulate(opp, min(stake, opp.liquidity))
            bankroll += sim.net_profit
            deployed += sim.capital
            edges.append(opp.net_edge)
            curve.append(bankroll)
        return {
            "ending": bankroll, "deployed": deployed, "profit": bankroll - starting,
            "roi": ((bankroll - starting) / starting * 100) if starting else 0.0,
            "count": len(edges), "avg_edge": (sum(edges) / len(edges)) if edges else 0.0,
            "curve": curve,
        }
