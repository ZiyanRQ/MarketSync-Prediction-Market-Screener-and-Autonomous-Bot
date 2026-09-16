"""Pure arbitrage / simulation maths — no Qt, no I/O.

The model is a per-selection cross-exchange hedge: BACK the selection on the venue
offering the higher back price, LAY it on the venue offering the lower lay price.
Capital is split as back stake + lay liability. Everything is depth-aware — larger
stakes walk down the ladder to worse prices, so ROI falls as capital rises, which is
what makes the profit-vs-investment curve and "max executable" meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from ..models.exchange_price import PriceLevel

# Default commissions (net winnings). Overridable from settings. Betfair's headline
# rate is 5%, but arb-focused accounts commonly sit near 2% — the demo defaults there
# so opportunities are achievable; raise it in Settings to model the 5% base rate.
DEFAULT_COMMISSION = {"Betfair": 0.02, "Matchbook": 0.02}


def _fill(levels: List[PriceLevel], stake: float, backing: bool) -> Tuple[float, float]:
    """Walk a ladder filling `stake`, returning (avg_odds, filled_stake).

    Levels are best-first (highest odds first when backing, lowest first when
    laying). Each level absorbs up to its size; anything unfilled is capped, so
    filled_stake < stake signals the book ran out of depth.
    """
    if not levels or stake <= 0:
        return (levels[0].odds if levels else 0.0), 0.0
    remaining, weighted, filled = stake, 0.0, 0.0
    for level in levels:
        take = min(remaining, level.size)
        weighted += take * level.odds
        filled += take
        remaining -= take
        if remaining <= 1e-9:
            break
    avg = weighted / filled if filled else levels[0].odds
    return avg, filled


def hedge_unit(back_odds: float, lay_odds: float, c_back: float, c_lay: float) -> float:
    """Lay stake per £1 back stake that equalises the two outcomes (a full hedge)."""
    return ((back_odds - 1) * (1 - c_back) + 1) / (lay_odds - c_lay)


def net_edge(back_odds: float, lay_odds: float, c_back: float, c_lay: float) -> float:
    """Guaranteed net return as % of back stake, after both commissions."""
    m = hedge_unit(back_odds, lay_odds, c_back, c_lay)
    profit = m * (1 - c_lay) - 1
    return profit * 100


def gross_edge(back_odds: float, lay_odds: float) -> float:
    return (back_odds / lay_odds - 1) * 100


@dataclass
class SimResult:
    capital: float
    back_stake: float
    lay_stake: float
    lay_liability: float
    avg_back: float
    avg_lay: float
    gross_profit: float
    commission: float
    net_profit: float
    net_roi: float
    profit_if_win: float
    profit_if_lose: float
    executable: bool  # False if the book couldn't absorb the requested capital


def simulate(back_levels: List[PriceLevel], lay_levels: List[PriceLevel], capital: float,
             c_back: float, c_lay: float, iterations: int = 8) -> SimResult:
    """Depth-aware hedge for a given capital (back stake + lay liability = capital).

    Back stake and lay liability are interdependent (the lay stake depends on the
    filled odds, which depend on the stakes), so we iterate to convergence.
    """
    if capital <= 0 or not back_levels or not lay_levels:
        b0 = back_levels[0].odds if back_levels else 0.0
        l0 = lay_levels[0].odds if lay_levels else 0.0
        return SimResult(capital, 0, 0, 0, b0, l0, 0, 0, 0, 0, 0, 0, True)

    back_stake = capital / 2
    avg_back = back_levels[0].odds
    avg_lay = lay_levels[0].odds
    executable = True

    for _ in range(iterations):
        avg_back, filled_back = _fill(back_levels, back_stake, backing=True)
        m = hedge_unit(avg_back, avg_lay, c_back, c_lay)
        lay_stake = back_stake * m
        avg_lay, filled_lay = _fill(lay_levels, lay_stake, backing=False)
        liability = lay_stake * (avg_lay - 1)
        total = back_stake + liability
        executable = filled_back >= back_stake - 1e-6 and filled_lay >= lay_stake - 1e-6
        if total <= 1e-9:
            break
        back_stake *= capital / total  # rescale so back stake + liability == capital

    lay_stake = back_stake * hedge_unit(avg_back, avg_lay, c_back, c_lay)
    liability = lay_stake * (avg_lay - 1)

    profit_win = back_stake * (avg_back - 1) * (1 - c_back) - liability
    profit_lose = -back_stake + lay_stake * (1 - c_lay)
    net_profit = min(profit_win, profit_lose)

    # Commission is charged per venue, on that venue's NET WINNINGS only, so the
    # amount depends on which way the selection goes: if it wins, the back venue
    # charges on the back profit and the losing lay venue charges nothing; if it
    # loses, only the lay venue charges, on the lay stake it keeps.
    # Report the charge for the outcome net_profit represents (the worst case),
    # which keeps gross - commission == net.
    commission = (back_stake * (avg_back - 1) * c_back if profit_win <= profit_lose
                  else lay_stake * c_lay)
    gross = net_profit + commission
    roi = (net_profit / capital * 100) if capital else 0.0

    return SimResult(capital, back_stake, lay_stake, liability, avg_back, avg_lay,
                     gross, commission, net_profit, roi, profit_win, profit_lose, executable)


def max_executable(back_levels: List[PriceLevel], lay_levels: List[PriceLevel],
                   c_back: float, c_lay: float, ceiling: float = 50000.0) -> float:
    """Largest capital that still yields a non-negative guaranteed net profit.

    Coarse scan up the capital axis until the depth-eroded edge turns negative.
    """
    step = max(ceiling / 200.0, 1.0)
    best = 0.0
    capital = step
    while capital <= ceiling:
        result = simulate(back_levels, lay_levels, capital, c_back, c_lay)
        if result.net_profit <= 0 or not result.executable:
            break
        best = capital
        capital += step
    return best


def profit_curve(back_levels: List[PriceLevel], lay_levels: List[PriceLevel],
                 c_back: float, c_lay: float, points: int = 40) -> List[SimResult]:
    """Sample the profit-vs-capital curve up to (a bit past) max executable."""
    cap = max_executable(back_levels, lay_levels, c_back, c_lay)
    if cap <= 0:
        return []
    top = cap * 1.15
    return [simulate(back_levels, lay_levels, top * i / points, c_back, c_lay)
            for i in range(1, points + 1)]


def quality_components(net: float, liquidity: float, price_age: float, volatility: float,
                       edge_stability: float, match_confidence: float):
    """Return a QualityScore (imported lazily to avoid a model import cycle)."""
    from ..models.opportunity import QualityScore
    profitability = max(0.0, min(20.0, net / 3.0 * 20.0))          # ~3% net = full
    liq = max(0.0, min(20.0, liquidity / 2000.0 * 20.0))           # £2k = full
    fresh = max(0.0, min(20.0, (1 - price_age / 60.0) * 20.0))     # <60s window
    stability = max(0.0, min(20.0, (1 - edge_stability) * 20.0))   # low variance = full
    match = max(0.0, min(10.0, match_confidence * 10.0))
    execution = max(0.0, min(10.0, (1 - volatility / 50.0) * 10.0))
    return QualityScore(profitability, liq, fresh, stability, match, execution)
