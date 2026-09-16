"""Turns Markets into Opportunities and keeps their lifetime history.

Stateful: it holds one Opportunity per market across ticks and updates it in place,
so peak/low/average edge, price-change counts and volatility accumulate. Direction
is always cross-exchange — back on the higher-back venue, lay on the lower-lay one.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Dict, List

from ..models.enums import Direction, OppStatus, Venue
from ..models.market import Market
from ..models.opportunity import Opportunity
from ..utils import calculations as calc


class ArbitrageEngine:
    def __init__(self, commission: Dict[str, float] | None = None) -> None:
        self.commission = commission or dict(calc.DEFAULT_COMMISSION)
        self._opps: Dict[str, Opportunity] = {}

    def _best_direction(self, market: Market):
        """Choose the more profitable cross-exchange back/lay orientation."""
        bf, mb = market.betfair, market.matchbook
        candidates = []
        if bf.best_back and mb.best_lay:
            candidates.append((Direction.BACK_BF_LAY_MB, Venue.BETFAIR, Venue.MATCHBOOK,
                               bf.best_back, mb.best_lay, bf.back, mb.lay))
        if mb.best_back and bf.best_lay:
            candidates.append((Direction.BACK_MB_LAY_BF, Venue.MATCHBOOK, Venue.BETFAIR,
                               mb.best_back, bf.best_lay, mb.back, bf.lay))
        if not candidates:
            return None
        scored = []
        for direction, bv, lv, back, lay, back_levels, lay_levels in candidates:
            net = calc.net_edge(back, lay, self.commission[bv.value], self.commission[lv.value])
            scored.append((net, direction, bv, lv, back, lay, back_levels, lay_levels))
        return max(scored, key=lambda s: s[0])

    def rebuild(self, markets: List[Market]) -> List[Opportunity]:
        now = datetime.now()
        live_ids = set()
        for market in markets:
            best = self._best_direction(market)
            if best is None:
                continue
            net, direction, bv, lv, back, lay, back_levels, lay_levels = best
            gross = calc.gross_edge(back, lay)
            liquidity = min(sum(l.size for l in back_levels), sum(l.size for l in lay_levels))
            live_ids.add(market.market_id)

            opp = self._opps.get(market.market_id)
            if opp is None:
                opp = Opportunity(
                    market=market, direction=direction, back_venue=bv.value, lay_venue=lv.value,
                    back_odds=back, lay_odds=lay, liquidity=liquidity, gross_edge=gross,
                    net_edge=net, quality=calc.quality_components(net, liquidity, 0, 0, 0, 0.95),
                    volatility=0.0, created=now,
                )
                self._opps[market.market_id] = opp
            else:
                if abs(opp.net_edge - net) > 1e-6:
                    opp.price_changes += 1
                opp.market = market
                opp.direction, opp.back_venue, opp.lay_venue = direction, bv.value, lv.value
                opp.back_odds, opp.lay_odds = back, lay
                opp.liquidity, opp.gross_edge, opp.net_edge = liquidity, gross, net

            opp.observe()
            hist = list(opp.edge_history)
            opp.volatility = (statistics.pstdev(hist) * 10) if len(hist) > 1 else 0.0
            stability = min(1.0, opp.volatility / 5.0)
            opp.quality = calc.quality_components(
                net, liquidity, opp.price_age, opp.volatility, stability, 0.95)
            opp.status = OppStatus.LIVE if net > 1.0 else OppStatus.THIN if net > 0 else OppStatus.EXPIRED

        # Keep every priced selection as a row (dense, stable table); the risk
        # proxy filters to the qualifying ones. Only genuinely dropped markets vanish.
        return [o for o in self._opps.values() if o.market.market_id in live_ids]
