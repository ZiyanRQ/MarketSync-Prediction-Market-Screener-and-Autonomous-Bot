"""Simulated market-data provider.

Generates a realistic universe of selections across a few sports with layered
order books, then mutates them every tick — prices drift, ladders refill, some
selections drift in and out of arbitrage. This is what drives the live terminal
without any exchange credentials.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List

from ..models.enums import Sport, Venue
from ..models.exchange_price import ExchangePrice, PriceLevel
from ..models.market import Market
from .base_provider import BaseProvider

_FIXTURES = [
    (Sport.FOOTBALL, "Premier League", "Liverpool v Arsenal", ["Liverpool", "Draw", "Arsenal"]),
    (Sport.FOOTBALL, "Premier League", "Man City v Chelsea", ["Man City", "Draw", "Chelsea"]),
    (Sport.FOOTBALL, "Premier League", "Spurs v Newcastle", ["Spurs", "Draw", "Newcastle"]),
    (Sport.FOOTBALL, "La Liga", "Real Madrid v Barcelona", ["Real Madrid", "Draw", "Barcelona"]),
    (Sport.FOOTBALL, "La Liga", "Atletico v Sevilla", ["Atletico", "Draw", "Sevilla"]),
    (Sport.FOOTBALL, "Serie A", "Inter v Juventus", ["Inter", "Draw", "Juventus"]),
    (Sport.FOOTBALL, "Bundesliga", "Bayern v Dortmund", ["Bayern", "Draw", "Dortmund"]),
    (Sport.TENNIS, "ATP", "Alcaraz v Sinner", ["Alcaraz", "Sinner"]),
    (Sport.TENNIS, "WTA", "Swiatek v Gauff", ["Swiatek", "Gauff"]),
    (Sport.TENNIS, "ATP", "Djokovic v Medvedev", ["Djokovic", "Medvedev"]),
    (Sport.TENNIS, "ATP", "Zverev v Rublev", ["Zverev", "Rublev"]),
    (Sport.BASKETBALL, "NBA", "Lakers v Celtics", ["Lakers", "Celtics"]),
    (Sport.BASKETBALL, "NBA", "Warriors v Nuggets", ["Warriors", "Nuggets"]),
    (Sport.BASKETBALL, "NBA", "Bucks v Heat", ["Bucks", "Heat"]),
    (Sport.HORSE_RACING, "Ascot 15:40", "Ascot 15:40", ["Thunderbolt", "Grey Dawn", "Iron Duke"]),
    (Sport.HORSE_RACING, "York 16:10", "York 16:10", ["Night Fox", "Sea Breeze", "Old Oak"]),
]


def _ladder(base_odds: float, backing: bool, depth: int = 5) -> List[PriceLevel]:
    """Build a 5-deep ladder around base_odds with plausible increasing size."""
    step = 0.02 if base_odds < 3 else 0.05
    levels = []
    for i in range(depth):
        # Back ladder steps DOWN in odds; lay ladder steps UP.
        odds = base_odds - i * step if backing else base_odds + i * step
        size = round(random.uniform(80, 250) * (i + 1), 0)
        levels.append(PriceLevel(round(max(1.01, odds), 2), size))
    return levels


class MockProvider(BaseProvider):
    mode = "DEMO"

    def __init__(self, seed: int = 7) -> None:
        self._rng = random.Random(seed)
        random.seed(seed)
        self._markets: List[Market] = []
        self._fair: dict[str, float] = {}
        self._build()

    def name(self) -> str:
        return "Simulated"

    def _build(self) -> None:
        now = datetime.now()
        idx = 0
        for sport, league, event, selections in _FIXTURES:
            in_play = self._rng.random() < 0.35
            start = now + timedelta(minutes=self._rng.randint(-30, 240))
            for sel in selections:
                idx += 1
                fair = round(self._rng.uniform(1.6, 6.0), 2)
                self._fair[f"M{idx}"] = fair
                market = Market(
                    market_id=f"M{idx}", sport=sport, league=league, event=event,
                    market_name="Match Odds", selection=sel, start_time=start,
                    in_play=in_play,
                    betfair=self._quote(fair), matchbook=self._quote(fair),
                    price_ts=now,
                )
                self._maybe_bias(market)
                self._markets.append(market)

    def _quote(self, fair: float) -> ExchangePrice:
        """Two ladders straddling a slightly jittered fair value per venue."""
        skew = self._rng.uniform(-0.06, 0.06)
        mid = max(1.05, fair + skew)
        spread = self._rng.uniform(0.02, 0.08)
        return ExchangePrice(
            back=_ladder(mid + spread, backing=True),
            lay=_ladder(mid + spread + self._rng.uniform(0.0, 0.06), backing=False),
        )

    def _maybe_bias(self, market: Market, prob: float = 0.55) -> None:
        """With probability `prob`, nudge the higher-back venue up so a genuine
        cross-exchange back>lay edge exists. Keeps the demo lively without pretending
        real markets are this generous."""
        if self._rng.random() > prob:
            return
        bf, mb = market.betfair, market.matchbook
        if not (bf.best_lay and mb.best_lay):
            return
        margin = 1 + self._rng.uniform(0.01, 0.07)
        if self._rng.random() < 0.5:  # back BF over lay MB
            delta = mb.best_lay * margin - bf.best_back
            for lvl in bf.back:
                lvl.odds = round(lvl.odds + delta, 2)
        else:                         # back MB over lay BF
            delta = bf.best_lay * margin - mb.best_back
            for lvl in mb.back:
                lvl.odds = round(lvl.odds + delta, 2)

    def tick(self) -> None:
        """Drift markets; refresh ladders; re-seed cross-venue edges."""
        now = datetime.now()
        for market in self._markets:
            if self._rng.random() < 0.45:
                continue  # not every market changes every tick
            fair = self._fair[market.market_id]
            fair = max(1.05, fair + self._rng.uniform(-0.05, 0.05))
            self._fair[market.market_id] = fair
            market.betfair = self._quote(fair)
            market.matchbook = self._quote(fair)
            self._maybe_bias(market)
            market.in_play = market.in_play or self._rng.random() < 0.02
            market.price_ts = now

    def fetch(self) -> List[Market]:
        return list(self._markets)
