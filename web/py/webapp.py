"""Browser-side glue between the real MarketSync engine and the web UI.

Everything that matters here is imported, not reimplemented: `MockProvider`
generates the markets, `ArbitrageEngine` derives the opportunities and keeps
their lifetime history, `calculations` does the depth-aware hedge maths, and
`Opportunity.apply_buffer` sets the risk tier. This module only drives them on a
tick and flattens the result to JSON for JavaScript to draw.

It exists because the desktop equivalents of those two jobs - MarketDataService
(a QTimer) and RiskEngine (a QObject) - are Qt-bound and cannot load in Pyodide.

NOTE: `_passes` below duplicates `RiskEngine._passes_profile`. It is the one
piece of logic copied rather than imported. The clean fix is to move that
predicate onto `RiskProfile` in `app/models/` so both the desktop RiskEngine and
this module call the same code; that would be a change to `app/`, so it is left
as a follow-up rather than done silently here.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List

from app.models.risk_profile import default_profiles
from app.providers.mock_provider import MockProvider
from app.services.arbitrage_engine import ArbitrageEngine
from app.utils import calculations as calc


class WebTerminal:
    """One terminal session: provider, engine, risk profiles and a tick counter."""

    def __init__(self) -> None:
        self.commission: Dict[str, float] = dict(calc.DEFAULT_COMMISSION)
        self.provider = MockProvider()
        self.engine = ArbitrageEngine(self.commission)
        self.profiles = default_profiles()
        self.enabled = {"MODERATE"}
        self.ticks = 0
        self._opps: List = []

    # -- risk ---------------------------------------------------------------
    @property
    def primary(self):
        """Most conservative enabled profile - biggest buffer, then strictest min-net."""
        names = [n for n in self.enabled if n in self.profiles] or ["MODERATE"]
        return self.profiles[max(names, key=lambda n: (self.profiles[n].safety_buffer,
                                                       self.profiles[n].min_net_edge))]

    def _passes(self, opp, profile) -> bool:
        """Mirror of RiskEngine._passes_profile - see the note in the module docstring."""
        return (opp.net_edge >= profile.min_net_edge
                and (opp.net_edge - profile.safety_buffer) >= 0
                and opp.liquidity >= profile.min_liquidity
                and opp.price_age <= profile.max_price_age
                and opp.quality.total >= profile.min_quality
                and opp.volatility <= profile.max_volatility)

    def passes_any(self, opp) -> bool:
        """Surfaced if it clears ANY enabled profile (the union, as on the desktop)."""
        return any(self._passes(opp, self.profiles[n])
                   for n in self.enabled if n in self.profiles)

    def set_enabled(self, names) -> None:
        valid = {n for n in list(names) if n in self.profiles}
        self.enabled = valid or {"MODERATE"}

    def set_commission(self, venue: str, rate: float) -> None:
        if venue in self.commission:
            self.commission[venue] = rate
            self.engine.commission[venue] = rate

    # -- tick ---------------------------------------------------------------
    def tick(self) -> str:
        """Advance the simulation one step and return the full snapshot as JSON."""
        self.provider.tick()
        markets = self.provider.fetch()
        self._opps = self.engine.rebuild(markets)

        profile = self.primary
        for opp in self._opps:
            opp.apply_buffer(profile.safety_buffer, profile.min_net_edge)

        self.ticks += 1
        return json.dumps(self._snapshot(profile))

    def _snapshot(self, profile) -> dict:
        rows = [self._row(o) for o in self._opps]
        surfaced = [r for r in rows if r["passes"]]
        return {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "ticks": self.ticks,
            "rows": rows,
            "stats": {
                "markets": len(rows),
                "surfaced": len(surfaced),
                "safe": sum(1 for r in surfaced if r["risk"] == "SAFE"),
                "thin": sum(1 for r in surfaced if r["risk"] == "THIN"),
                "best": max((r["net_edge"] for r in surfaced), default=0.0),
                "profile": profile.name,
                "buffer": profile.safety_buffer,
                "min_net": profile.min_net_edge,
            },
        }

    def _row(self, opp) -> dict:
        market = opp.market
        return {
            "id": market.market_id,
            "sport": market.sport.value,
            "league": market.league,
            "event": market.event,
            "selection": market.selection,
            "in_play": market.in_play,
            "direction": opp.direction.value,
            "back_venue": opp.back_venue,
            "lay_venue": opp.lay_venue,
            "back_odds": round(opp.back_odds, 2),
            "lay_odds": round(opp.lay_odds, 2),
            "liquidity": round(opp.liquidity, 0),
            "gross_edge": round(opp.gross_edge, 3),
            "net_edge": round(opp.net_edge, 3),
            "buffered_edge": round(opp.buffered_edge, 3),
            "quality": round(opp.quality.total, 1),
            "volatility": round(opp.volatility, 2),
            "risk": opp.risk.value,
            "status": opp.status.value,
            "age": round(opp.age_seconds, 0),
            "price_age": round(opp.price_age, 1),
            "peak": round(opp.peak_edge, 2),
            "low": round(opp.low_edge, 2) if opp.low_edge < 999 else 0.0,
            "avg": round(opp.average_edge(), 2),
            "changes": opp.price_changes,
            "history": [round(v, 3) for v in list(opp.edge_history)[-60:]],
            "passes": self.passes_any(opp),
        }

    # -- inspector ----------------------------------------------------------
    def _legs(self, opp):
        """The two ladders actually used: back on one venue, lay on the other."""
        market = opp.market
        if opp.back_venue == "Betfair":
            return market.betfair.back, market.matchbook.lay
        return market.matchbook.back, market.betfair.lay

    def detail(self, market_id: str) -> str:
        """Ladders, quality breakdown and a depth-aware profit curve, as JSON."""
        opp = next((o for o in self._opps if o.market.market_id == market_id), None)
        if opp is None:
            return json.dumps({"found": False})

        market = opp.market
        back_levels, lay_levels = self._legs(opp)
        c_back = self.commission[opp.back_venue]
        c_lay = self.commission[opp.lay_venue]

        ceiling = calc.max_executable(back_levels, lay_levels, c_back, c_lay)
        curve = calc.profit_curve(back_levels, lay_levels, c_back, c_lay, points=24)
        q = opp.quality

        return json.dumps({
            "found": True,
            "id": market_id,
            "event": market.event,
            "selection": market.selection,
            "market_name": market.market_name,
            "league": market.league,
            "quality": {
                "Profitability": [round(q.profitability, 1), 20],
                "Liquidity": [round(q.liquidity, 1), 20],
                "Freshness": [round(q.freshness, 1), 20],
                "Stability": [round(q.stability, 1), 20],
                "Market match": [round(q.market_match, 1), 10],
                "Execution": [round(q.execution_risk, 1), 10],
            },
            "ladders": {
                "Betfair": self._ladder(market.betfair),
                "Matchbook": self._ladder(market.matchbook),
            },
            "max_executable": round(ceiling, 0),
            "curve": [{"capital": round(r.capital, 0), "profit": round(r.net_profit, 2),
                       "roi": round(r.net_roi, 3)} for r in curve],
            "sim": self._sim(back_levels, lay_levels, min(200.0, ceiling) or 100.0,
                             c_back, c_lay),
        })

    def simulate(self, market_id: str, capital: float) -> str:
        """Depth-aware hedge for an explicit stake - the inspector's slider."""
        opp = next((o for o in self._opps if o.market.market_id == market_id), None)
        if opp is None:
            return json.dumps({"found": False})
        back_levels, lay_levels = self._legs(opp)
        return json.dumps({"found": True, **self._sim(
            back_levels, lay_levels, float(capital),
            self.commission[opp.back_venue], self.commission[opp.lay_venue])})

    @staticmethod
    def _sim(back_levels, lay_levels, capital, c_back, c_lay) -> dict:
        r = calc.simulate(back_levels, lay_levels, capital, c_back, c_lay)
        return {
            "capital": round(r.capital, 2), "back_stake": round(r.back_stake, 2),
            "lay_stake": round(r.lay_stake, 2), "liability": round(r.lay_liability, 2),
            "avg_back": round(r.avg_back, 3), "avg_lay": round(r.avg_lay, 3),
            "commission": round(r.commission, 2), "net_profit": round(r.net_profit, 2),
            "roi": round(r.net_roi, 3), "if_win": round(r.profit_if_win, 2),
            "if_lose": round(r.profit_if_lose, 2), "executable": r.executable,
        }

    @staticmethod
    def _ladder(price) -> dict:
        return {
            "back": [{"odds": l.odds, "size": l.size} for l in price.back],
            "lay": [{"odds": l.odds, "size": l.size} for l in price.lay],
        }


TERMINAL = WebTerminal()
