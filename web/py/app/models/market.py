"""A single tradable selection with both venues' prices attached."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .enums import Sport, Venue
from .exchange_price import ExchangePrice


@dataclass
class Market:
    """One selection in one market, priced on both exchanges.

    Rows in the screener map 1:1 to a Market. The two ExchangePrice objects carry
    the full ladders; the arbitrage engine derives an Opportunity from them.
    """
    market_id: str
    sport: Sport
    league: str
    event: str
    market_name: str
    selection: str
    start_time: datetime
    in_play: bool
    betfair: ExchangePrice
    matchbook: ExchangePrice
    price_ts: datetime  # when these prices were last refreshed

    def price_for(self, venue: Venue) -> ExchangePrice:
        return self.betfair if venue is Venue.BETFAIR else self.matchbook
